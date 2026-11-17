import json
import logging
import uuid
from contextlib import asynccontextmanager, contextmanager
from datetime import date, timedelta
from pathlib import Path
from threading import Lock

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool
from starlette.staticfiles import StaticFiles

from . import chat, db, llm, markers, memory, models, pipeline, progress
from .audio import decode, detect_container
from .config import ROOT, settings
from .curriculum import CATALOG, TOPICS, prompt, public_topic, recommend, topic_for
from .schemas import (
    ChatInput,
    CoachNotesEdit,
    LearnerNote,
    ModelSelection,
    PassSettings,
    SessionCreate,
    StageChange,
    TranscriptEdit,
)
from .security import configure_browser_security


class JSONFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps(
            {
                "time": db.now(),
                "level": record.levelname,
                "event": record.getMessage(),
                **{
                    k: getattr(record, k)
                    for k in ("attempt_id", "components_failed", "method", "route", "status", "elapsed_ms")
                    if hasattr(record, k)
                },
            }
        )


handler = logging.StreamHandler()
handler.setFormatter(JSONFormatter())
log = logging.getLogger("speaklab")
log.handlers = [handler]
log.setLevel(logging.INFO)
log.propagate = False
mutation_lock = Lock()
tutor_lock = Lock()  # one coach chat reply at a time


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.initialize()
    pipeline.complete_legacy_sessions()  # migrated compare sessions have no review still to come
    pipeline.recover_writers()  # a writer queued before a restart still runs
    pipeline.sweep_note_deadlines()  # a restart during the note wait can't leave a review stuck
    selection = db.one("SELECT value FROM app_settings WHERE key='ollama_model'")
    if selection:
        settings.ollama_model = selection["value"]
    frontend = None
    if settings.serve_frontend:
        app.mount("/", StaticFiles(directory=ROOT / "frontend" / "dist", html=True), name="frontend")
        frontend = app.routes[-1]
    try:
        yield
    finally:
        if frontend is not None:
            app.routes.remove(frontend)


app = FastAPI(title="SpeakLab local API", version="0.1.0", lifespan=lifespan)
configure_browser_security(app, settings, log)


def get_session(session_id: str) -> dict:
    result = db.one("SELECT * FROM sessions WHERE id=?", (session_id,))
    if not result:
        raise HTTPException(404, "Session not found.")
    return result


def get_attempt(attempt_id: str) -> dict:
    result = db.one("SELECT * FROM attempts WHERE id=?", (attempt_id,))
    if not result:
        raise HTTPException(404, "Attempt not found.")
    return result


def require_first(session_id: str):
    if not db.one("SELECT id FROM attempts WHERE session_id=? AND number=1", (session_id,)):
        raise HTTPException(409, "Save your cold attempt before revealing reference material.")


def archive(conn, attempt: dict):
    """Keep the public attempt and its review message before they are replaced."""
    snapshot = db.attempt_public(attempt)
    review = conn.execute(
        "SELECT content FROM messages WHERE session_id=? AND attempt_number=? AND kind='review'",
        (attempt["session_id"], attempt["number"]),
    ).fetchone()
    snapshot["review_message"] = review["content"] if review else None
    conn.execute(
        "INSERT INTO analysis_history(attempt_id,created_at,snapshot) VALUES(?,?,?)",
        (attempt["id"], db.now(), json.dumps(snapshot)),
    )


def require_editable(attempt: dict):
    if get_session(attempt["session_id"])["completed_at"]:
        raise HTTPException(409, "Completed sessions are preserved. Start a new practice session.")
    if attempt["status"] in {"pending", "processing"}:
        raise HTTPException(409, "Analysis is already running. Wait for it to finish.")


@app.get("/api/health")
def health():
    return {"status": "ok", **models.health()}


@app.get("/api/models")
def available_models():
    try:
        return {"selected": settings.ollama_model, "models": models.installed_models()}
    except models.ServiceUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc


@contextmanager
def model_change_guard():
    """Serialize model-setting changes and refuse them while analysis or a coach reply is active."""
    with mutation_lock:
        if db.one("SELECT id FROM attempts WHERE status IN ('pending','processing') LIMIT 1"):
            raise HTTPException(409, "Wait for recording analysis to finish before changing models.")
        if not tutor_lock.acquire(blocking=False):
            raise HTTPException(409, "Wait for the coach to finish answering before changing models.")
        try:
            yield
        finally:
            tutor_lock.release()


@app.put("/api/settings/model")
def select_model(body: ModelSelection):
    with model_change_guard():
        try:
            models.validate_model_selection(body.model)
            llm.save_global_model(body.model)
            settings.ollama_model = body.model
        except models.ServiceUnavailable as exc:
            raise HTTPException(503, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    return {"selected": settings.ollama_model}


@app.get("/api/settings/passes")
def get_pass_settings():
    return llm.pass_settings()


@app.put("/api/settings/passes")
def put_pass_settings(body: PassSettings):
    with model_change_guard():
        try:
            return llm.save_pass_settings({k: v.model_dump() for k, v in body.passes.items()})
        except models.ServiceUnavailable as exc:
            raise HTTPException(503, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc


@app.get("/api/topics")
def topics():
    return [public_topic(t) for t in TOPICS]


@app.get("/api/topics/recommend")
def recommendation(category: str | None = None, difficulty: str | None = None, exclude: str | None = None):
    candidates = [
        t
        for t in TOPICS
        if (not category or t["category"] == category)
        and (not difficulty or t["difficulty"] == difficulty)
        and t["id"] != exclude
    ]
    if not candidates:
        candidates = [
            t
            for t in TOPICS
            if (not category or t["category"] == category)
            and (not difficulty or t["difficulty"] == difficulty)
        ]
    if not candidates:
        raise HTTPException(404, "No topics match those filters. Try a broader selection.")
    reviews = {r["topic_id"]: r for r in db.all_rows("SELECT * FROM reviews")}
    weak = {}
    for row in db.all_rows(
        "SELECT s.topic_id, a.assessment, a.analysis FROM sessions s JOIN attempts a ON a.session_id=s.id AND a.number=2 WHERE s.completed_at IS NOT NULL ORDER BY s.created_at"
    ):
        score = progress.mastery(progress.concept_results(row))
        if score is not None:
            weak[row["topic_id"]] = 1 - score
    selected = recommend(candidates, reviews, weak)
    review = reviews.get(selected["id"])
    return {
        "topic": public_topic(selected),
        "reason": "Due for a memory check"
        if review and review["due"] <= date.today().isoformat()
        else "Room to deepen your understanding"
        if weak.get(selected["id"], 0) > 0.3
        else "A fresh perspective for your next practice",
    }


@app.post("/api/sessions", status_code=201)
def create_session(body: SessionCreate):
    if body.topic_id not in CATALOG:
        raise HTTPException(404, "Topic not found.")
    session_id = str(uuid.uuid4())
    db.execute(
        "INSERT INTO sessions(id,topic_id,created_at,duration,style,prompt_kind) VALUES(?,?,?,?,?,?)",
        (session_id, body.topic_id, db.now(), body.duration, body.style, body.prompt_kind),
    )
    return session_detail(session_id)


@app.get("/api/sessions")
def history():
    rows = db.all_rows("SELECT * FROM sessions ORDER BY created_at DESC LIMIT 200")
    for row in rows:
        row["topic"] = public_topic(topic_for(row["topic_id"]))
        attempts = db.all_rows(
            "SELECT number, assessment, analysis, acoustics FROM attempts WHERE session_id=? ORDER BY number",
            (row["id"],),
        )
        row["attempt_count"] = len(attempts)
        row["coverage"] = []
        for attempt in attempts:
            a = progress.concept_results(attempt)
            m = json.loads(attempt["acoustics"]) if attempt["acoustics"] else {}
            row["coverage"].append(
                {
                    "attempt": attempt["number"],
                    "correct": sum(c["status"] == "correct" for c in a["concepts"]) if a else None,
                    "total": len(topic_for(row["topic_id"])["concepts"]),
                    "wpm": m.get("wpm"),
                    "pitch_range_semitones": m.get("pitch_range_semitones"),
                    "filler_count": m.get("filler_count"),
                }
            )
    return rows


@app.get("/api/reviews")
def reviews():
    # A topic with a second attempt still to do shows in the attempt 2 queue instead.
    rows = db.all_rows(
        "SELECT * FROM reviews WHERE topic_id NOT IN ("
        "SELECT topic_id FROM sessions WHERE stage IN ('review1','record2') AND completed_at IS NULL"
        ") ORDER BY due"
    )
    return [
        {**r, "topic": public_topic(topic_for(r["topic_id"])), "overdue": r["due"] <= date.today().isoformat()}
        for r in rows
    ]


@app.get("/api/attempt2")
def attempt2_queue():
    """Second attempts still to do. They never expire; each opens the day after attempt 1."""
    today = date.today().isoformat()
    rows = db.all_rows(
        "SELECT * FROM sessions WHERE stage IN ('review1','record2') AND completed_at IS NULL "
        "ORDER BY attempt2_after, created_at"
    )
    return [
        {
            "session_id": r["id"],
            "topic": public_topic(topic_for(r["topic_id"])),
            "attempt2_after": r["attempt2_after"],
            "available": not r["attempt2_after"] or r["attempt2_after"] <= today,
        }
        for r in rows
    ]


@app.get("/api/sessions/{session_id}")
def session_detail(session_id: str):
    session = get_session(session_id)
    pipeline.sweep_note_deadlines()
    topic = topic_for(session["topic_id"])
    session["topic"] = public_topic(topic)
    session["prompt"] = prompt(topic, session["prompt_kind"])
    session["attempts"] = [
        db.attempt_public(a)
        for a in db.all_rows("SELECT * FROM attempts WHERE session_id=? ORDER BY number", (session_id,))
    ]
    lines = {a["number"]: a["lines"] or [] for a in session["attempts"]}
    session["messages"] = [
        {**m, "parts": markers.resolve(m["content"], lines.get(m["attempt_number"], []))}
        for m in db.all_rows("SELECT * FROM messages WHERE session_id=? ORDER BY id", (session_id,))
    ]
    return session


def _attempt1_too_short(session_id: str) -> bool:
    """A too-short attempt 1 got no feedback, so it may be recorded again."""
    row = db.one("SELECT analysis FROM attempts WHERE session_id=? AND number=1", (session_id,))
    analysis = json.loads(row["analysis"]) if row and row["analysis"] else {}
    return bool((analysis.get("review") or {}).get("too_short"))


@app.put("/api/sessions/{session_id}/stage")
def stage(session_id: str, body: StageChange):
    with mutation_lock:
        session = get_session(session_id)
        if session["completed_at"]:
            raise HTTPException(409, "This session is complete.")
        if body.stage != "record1":
            require_first(session_id)
        if body.stage == "record1" and session["stage"] != "record1" and not (
            session["stage"] == "review1" and _attempt1_too_short(session_id)
        ):
            raise HTTPException(409, "The cold attempt is preserved after feedback is revealed.")
        if (
            body.stage == "record2"
            and session["stage"] != "record2"
            and db.one("SELECT id FROM attempts WHERE session_id=? AND number=2", (session_id,))
        ):
            raise HTTPException(409, "Attempt 2 is preserved after it is saved.")
        if (
            body.stage == "record2"
            and session["attempt2_after"]
            and date.today().isoformat() < session["attempt2_after"]
        ):
            raise HTTPException(409, "Attempt 2 opens tomorrow so it tests what you remember.")
        if body.stage == "review2" and not db.one(
            "SELECT id FROM attempts WHERE session_id=? AND number=2", (session_id,)
        ):
            raise HTTPException(409, "Save your second attempt first.")
        db.execute("UPDATE sessions SET stage=? WHERE id=?", (body.stage, session_id))
    return session_detail(session_id)


@app.post("/api/sessions/{session_id}/attempts/{number}", status_code=201)
async def upload(session_id: str, number: int, file: UploadFile = File(...)):
    if number not in (1, 2):
        raise HTTPException(422, "Attempt number must be 1 or 2.")
    session = get_session(session_id)
    if session["completed_at"] or session["stage"] != f"record{number}":
        raise HTTPException(409, "Open the appropriate recording step before saving an attempt.")
    if number == 2:
        require_first(session_id)
    identifier = str(uuid.uuid4())
    folder = settings.data_dir / "recordings"
    source = folder / (identifier + ".upload")
    wav = folder / (identifier + ".decoded.wav")
    kept = False
    try:
        first = await file.read(65536)
        try:
            suffix, mime = detect_container(first)
        except ValueError as exc:
            raise HTTPException(415, str(exc)) from exc
        source = source.with_suffix(suffix)
        size = len(first)
        if size > settings.max_upload_bytes:
            raise HTTPException(413, "Audio must be smaller than 30 MB.")
        with source.open("wb") as out:
            out.write(first)
            while chunk := await file.read(65536):
                size += len(chunk)
                if size > settings.max_upload_bytes:
                    raise HTTPException(413, "Audio must be smaller than 30 MB.")
                out.write(chunk)
        try:
            duration = await run_in_threadpool(decode, source, wav)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        with mutation_lock:
            session = get_session(session_id)
            if session["completed_at"] or session["stage"] != f"record{number}":
                raise HTTPException(409, "The session changed while audio was being uploaded.")
            old = db.one("SELECT * FROM attempts WHERE session_id=? AND number=?", (session_id, number))
            if old:
                require_editable(old)
            with db.connect() as conn:
                if old:
                    conn.execute("DELETE FROM attempts WHERE id=?", (old["id"],))
                    # Messages hang off the session, so the replaced attempt's review and chat go
                    # explicitly. Its running summary went with the attempt row.
                    conn.execute(
                        "DELETE FROM messages WHERE session_id=? AND attempt_number=?", (session_id, number)
                    )
                conn.execute(
                    "INSERT INTO attempts(id,session_id,number,created_at,audio_file,wav_file,mime,duration) VALUES(?,?,?,?,?,?,?,?)",
                    (identifier, session_id, number, db.now(), str(source), str(wav), mime, duration),
                )
                if number == 1:
                    conn.execute(
                        "UPDATE sessions SET stage='review1', attempt2_after=? WHERE id=?",
                        ((date.today() + timedelta(days=1)).isoformat(), session_id),
                    )
                else:
                    conn.execute("UPDATE sessions SET stage='review2' WHERE id=?", (session_id,))
            kept = True
            if old:
                Path(old["audio_file"]).unlink(missing_ok=True)
                Path(old["wav_file"]).unlink(missing_ok=True)
            pipeline.submit(identifier)
        return db.attempt_public(get_attempt(identifier))
    finally:
        await file.close()
        if not kept:
            source.unlink(missing_ok=True)
            wav.unlink(missing_ok=True)


@app.get("/api/attempts/{attempt_id}/audio")
def playback(attempt_id: str):
    attempt = get_attempt(attempt_id)
    path = Path(attempt["audio_file"])
    if not path.is_file():
        raise HTTPException(404, "The saved audio file is missing from disk.")
    return FileResponse(
        path, media_type=attempt["mime"], filename=f"speaklab-attempt-{attempt['number']}{path.suffix}"
    )


@app.post("/api/attempts/{attempt_id}/retry")
def retry(attempt_id: str):
    with mutation_lock:
        attempt = get_attempt(attempt_id)
        # Completed sessions can recover missing processing, without altering original evidence.
        if attempt["status"] in {"pending", "processing"}:
            raise HTTPException(409, "Analysis is already running.")
        pipeline.retry(attempt_id)
    return {"status": "pending"}


@app.post("/api/attempts/{attempt_id}/note")
def learner_note(attempt_id: str, body: LearnerNote):
    text = (body.text or "").strip()
    if not body.skip and not text:
        raise HTTPException(422, "Write how it went, or skip.")
    if get_session(get_attempt(attempt_id)["session_id"])["completed_at"]:
        raise HTTPException(409, "Completed sessions are preserved. Start a new practice session.")
    if not pipeline.submit_note(attempt_id, None if body.skip else text, body.skip):
        raise HTTPException(409, "Your note for this attempt was already sent or skipped.")
    return db.attempt_public(get_attempt(attempt_id))


@app.put("/api/attempts/{attempt_id}/transcript")
def edit_transcript(attempt_id: str, body: TranscriptEdit):
    if not body.text.strip():
        raise HTTPException(422, "Enter a nonempty transcript.")
    with mutation_lock:
        attempt = get_attempt(attempt_id)
        require_editable(attempt)
        with db.connect() as conn:
            if attempt["analysis"] or attempt["assessment"]:
                archive(conn, attempt)  # the new transcript replaces the analysis, review or legacy assessment
            conn.execute(
                "UPDATE attempts SET transcript=?, transcript_source='manual', transcription_version=0, retranscribe=0, segments='[]', assessment=NULL, acoustics=NULL, status='pending', errors='{}' WHERE id=?",
                (body.text.strip(), attempt_id),
            )
        pipeline.submit(attempt_id)
    return {"status": "pending"}


@app.post("/api/attempts/{attempt_id}/rereview")
def rereview(attempt_id: str):
    """Run the current pipeline again on a saved attempt, legacy ones included. The earlier
    snapshot and review message are archived; the recording, transcript and schedule are kept."""
    with mutation_lock:
        attempt = get_attempt(attempt_id)
        if attempt["status"] in {"pending", "processing"}:
            raise HTTPException(409, "The coach is still reviewing this attempt. Wait for it to finish.")
        with db.connect() as conn:
            archive(conn, attempt)
            conn.execute(
                "DELETE FROM messages WHERE session_id=? AND attempt_number=? AND kind='review'",
                (attempt["session_id"], attempt["number"]),
            )
            conn.execute(
                "UPDATE attempts SET analysis=NULL, note_state='skipped', note_deadline=NULL, "
                "retranscribe=0, status='pending', errors='{}' WHERE id=?",
                (attempt_id,),
            )
        pipeline.submit(attempt_id)
    return {"status": "pending"}


@app.get("/api/attempts/{attempt_id}/analysis-history")
def analysis_history(attempt_id: str):
    get_attempt(attempt_id)
    return [
        {"id": row["id"], "created_at": row["created_at"], "attempt": json.loads(row["snapshot"])}
        for row in db.all_rows(
            "SELECT * FROM analysis_history WHERE attempt_id=? ORDER BY id DESC", (attempt_id,)
        )
    ]


@app.post("/api/sessions/{session_id}/chat")
def coach_chat(session_id: str, body: ChatInput):
    message = body.message.strip()
    if not message:
        raise HTTPException(422, "Write a message for the coach.")
    get_session(session_id)
    attempt = db.one(
        "SELECT * FROM attempts WHERE session_id=? AND number=?", (session_id, body.attempt_number)
    )
    if not attempt:
        raise HTTPException(
            409,
            "Record attempt 2 before chatting about it."
            if body.attempt_number == 2
            else "Record your first attempt before chatting with the coach.",
        )
    if chat.still_reviewing(attempt):
        raise HTTPException(409, chat.REVIEWING)
    if not tutor_lock.acquire(blocking=False):
        raise HTTPException(409, "The coach is already answering. Try again shortly.")
    released = Lock()

    def release():
        # Runs from the stream's finally and as a background task: a stream the client drops
        # before it starts never reaches its finally.
        if released.acquire(blocking=False):
            tutor_lock.release()

    def events():
        try:
            yield from chat.stream_reply(session_id, body.attempt_number, message)
        finally:
            release()

    return StreamingResponse(events(), media_type="text/event-stream", background=BackgroundTask(release))


@app.get("/api/coach-notes")
def coach_notes():
    return {"current": memory.current_notes(), "versions": memory.versions()}


# Edit and restore answer with the same {current, versions} view as GET, which the panel shows.
@app.put("/api/coach-notes")
def edit_coach_notes(body: CoachNotesEdit):
    try:
        memory.save_learner_edit(body.content)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return coach_notes()


@app.post("/api/coach-notes/{version_id}/restore")
def restore_coach_notes(version_id: int):
    try:
        memory.restore(version_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    return coach_notes()
