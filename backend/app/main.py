import json
import logging
import uuid
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from threading import Lock
from typing import get_args

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import ValidationError
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool
from starlette.staticfiles import StaticFiles

from . import chat, db, feedback, llm, markers, memory, models, pipeline, progress, threads
from .audio import decode, detect_container
from .config import ROOT, settings
from .curriculum import CATALOG, TOPICS, prompt, public_topic, recommend, topic_for
from .schemas import (
    AttemptSettings,
    ChatInput,
    CoachNotesEdit,
    LearnerNote,
    ModelSelection,
    PassSettings,
    PromptKind,
    ResponseFeedback,
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


def _concept_weakness() -> dict[str, float]:
    """Per practised topic, 1 - mastery of the thread's latest attempt that has concept results
    (the new technical pass, else a legacy assessment)."""
    weak = {}
    for thread in threads.all_threads():
        for attempt in reversed(threads.attempts(thread["id"])):
            score = progress.mastery(progress.concept_results(attempt))
            if score is not None:
                weak[thread["topic_id"]] = 1 - score
                break
    return weak


@app.get("/api/topics/recommend")
def recommendation(
    category: str | None = None,
    difficulty: str | None = None,
    exclude: str | None = None,
    include_practised: bool = False,
):
    practised = {t["topic_id"] for t in threads.all_threads()}
    pool = [
        t
        for t in TOPICS
        if (not category or t["category"] == category)
        and (not difficulty or t["difficulty"] == difficulty)
        and (include_practised or t["id"] not in practised)
    ]
    if not pool:
        raise HTTPException(
            404,
            "No topics match those filters. Try a broader selection."
            if include_practised
            else "You have practised every topic that matches. Include practised topics to see them.",
        )
    candidates = [t for t in pool if t["id"] != exclude] or pool
    reviews = {r["topic_id"]: r for r in db.all_rows("SELECT * FROM reviews")}
    weak = _concept_weakness()
    selected = recommend(candidates, reviews, weak)
    review = reviews.get(selected["id"])
    return {
        "topic": public_topic(selected),
        "practised": selected["id"] in practised,
        "reason": "Due for a memory check"
        if review and review["due"] <= threads.today().isoformat()
        else "Room to deepen your understanding"
        if weak.get(selected["id"], 0) > 0.3
        else "A fresh perspective for your next practice",
    }


def _thread_summary(thread: dict) -> dict:
    """The fields History and Today share for one topic thread."""
    attempts = threads.attempts(thread["id"])
    latest = attempts[-1]
    topic = topic_for(thread["topic_id"])
    return {
        "topic_id": thread["topic_id"],
        "topic": public_topic(topic),
        "session_id": thread["id"],
        "attempt_count": len(attempts),
        "last_attempt_at": latest["created_at"],
        "next_attempt_after": threads.next_attempt_after(thread["id"]),
        "can_record": threads.recording_state(thread["topic_id"])["can_record"],
        "_latest": latest,
    }


def _coverage(attempt: dict, topic_id: str) -> dict:
    results = progress.concept_results(attempt)
    metrics = json.loads(attempt["acoustics"]) if attempt["acoustics"] else {}
    return {
        "attempt": attempt["number"],
        "correct": sum(c["status"] == "correct" for c in results["concepts"]) if results else None,
        "total": len(topic_for(topic_id)["concepts"]),
        "wpm": metrics.get("wpm"),
        "pitch_range_semitones": metrics.get("pitch_range_semitones"),
        "filler_count": metrics.get("filler_count"),
    }


@app.get("/api/history")
def history():
    """One row per topic with at least one recording, most recently practised first."""
    rows = []
    for thread in threads.all_threads():
        row = _thread_summary(thread)
        row["coverage"] = _coverage(row.pop("_latest"), thread["topic_id"])
        rows.append(row)
    return sorted(rows, key=lambda r: r["last_attempt_at"], reverse=True)


@app.get("/api/practice/ready")
def practice_ready():
    """Practised topics where a new attempt is open: spaced reviews that are due first, then the
    oldest last attempt."""
    today = threads.today().isoformat()
    reviews = {r["topic_id"]: r for r in db.all_rows("SELECT * FROM reviews")}
    rows = []
    for thread in threads.all_threads():
        row = _thread_summary(thread)
        row.pop("_latest")
        if not row["can_record"]:
            continue
        review = reviews.get(thread["topic_id"])
        row["review_due"] = review["due"] if review else None
        row["due"] = bool(review and review["due"] <= today)
        rows.append(row)
    return sorted(rows, key=lambda r: (not r["due"], r["last_attempt_at"]))


def _attempt_view(attempt: dict, session: dict) -> dict:
    """The public attempt with the question type, style and target length it was recorded with."""
    chosen = threads.attempt_settings(attempt, session)
    result = {**db.attempt_public(attempt), **chosen}
    result["prompt"] = prompt(topic_for(session["topic_id"]), chosen["prompt_kind"])
    return result


@app.get("/api/topics/{topic_id}/thread")
def topic_thread(topic_id: str):
    thread = threads.thread_for_topic(topic_id)
    if not thread and topic_id not in CATALOG:
        raise HTTPException(404, "Topic not found.")
    pipeline.sweep_note_deadlines()
    topic = topic_for(topic_id)
    result = {
        "topic": public_topic(topic),
        # The question for each type, for the recording screen's "Try a different angle".
        "prompts": {kind: prompt(topic, kind) for kind in get_args(PromptKind)},
        "session_id": None,
        "attempts": [],
        "messages": [],
        "recording": threads.recording_state(topic_id),
        "latest_checklist": [],
        "next_attempt_after": None,
    }
    if thread:
        attempts = [_attempt_view(a, thread) for a in threads.attempts(thread["id"])]
        lines = {a["number"]: a["lines"] or [] for a in attempts}
        result.update(
            session_id=thread["id"],
            attempts=attempts,
            messages=[
                {**m, "parts": markers.resolve(m["content"], lines.get(m["attempt_number"], []))}
                for m in feedback.messages_for_session(thread["id"])
            ],
            latest_checklist=threads.latest_checklist(thread["id"]),
            next_attempt_after=threads.next_attempt_after(thread["id"]),
        )
    return result


@app.get("/api/sessions/{session_id}")
def session_detail(session_id: str):
    """A session as stored. Kept so old #/session links can find their topic (topic_id)."""
    session = get_session(session_id)
    pipeline.sweep_note_deadlines()
    topic = topic_for(session["topic_id"])
    session["topic"] = public_topic(topic)
    session["prompt"] = prompt(topic, session["prompt_kind"])
    session["attempts"] = [
        _attempt_view(a, session)
        for a in db.all_rows("SELECT * FROM attempts WHERE session_id=? ORDER BY number", (session_id,))
    ]
    lines = {a["number"]: a["lines"] or [] for a in session["attempts"]}
    session["messages"] = [
        {**m, "parts": markers.resolve(m["content"], lines.get(m["attempt_number"], []))}
        for m in feedback.messages_for_session(session_id)
    ]
    return session


def _refuse_unless_open(state: dict):
    if not state["can_record"]:
        raise HTTPException(409, state["reason"])


@app.post("/api/topics/{topic_id}/attempts", status_code=201)
async def upload(
    topic_id: str,
    file: UploadFile = File(...),
    prompt_kind: str | None = Form(None),
    style: str | None = Form(None),
    duration: int | None = Form(None),
):
    """Record the next attempt on the topic's thread, creating the thread with attempt 1, or
    replace a too-short latest attempt. Omitted settings carry over from the latest attempt."""
    if topic_id not in CATALOG:
        raise HTTPException(404, "Topic not found.")
    try:
        chosen = AttemptSettings(prompt_kind=prompt_kind, style=style, duration=duration)
    except ValidationError as exc:
        raise HTTPException(422, exc.errors(include_url=False, include_context=False)) from exc
    _refuse_unless_open(threads.recording_state(topic_id))  # before reading the audio
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
            seconds = await run_in_threadpool(decode, source, wav)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        with mutation_lock:
            # Checked again: the thread may have changed while the audio was uploading.
            state = threads.recording_state(topic_id)
            _refuse_unless_open(state)
            thread = threads.thread_for_topic(topic_id)
            latest = threads.attempts(thread["id"])[-1] if thread else None
            inherited = threads.attempt_settings(latest, thread) if latest else {}
            values = {
                "prompt_kind": chosen.prompt_kind or inherited.get("prompt_kind") or "Concept explanation",
                "style": chosen.style or inherited.get("style") or "Conversational",
                "target_duration": chosen.duration or inherited.get("target_duration") or 120,
            }
            number = state["next_number"]
            old = (
                db.one("SELECT * FROM attempts WHERE session_id=? AND number=?", (thread["id"], number))
                if thread and state["replace_number"]
                else None
            )
            with db.connect() as conn:
                if thread:
                    session_id = thread["id"]
                else:
                    # The thread is created only now, with its first recording.
                    session_id = str(uuid.uuid4())
                    conn.execute(
                        "INSERT INTO sessions(id,topic_id,created_at,duration,style,prompt_kind) VALUES(?,?,?,?,?,?)",
                        (
                            session_id,
                            topic_id,
                            db.now(),
                            values["target_duration"],
                            values["style"],
                            values["prompt_kind"],
                        ),
                    )
                if old:
                    conn.execute("DELETE FROM attempts WHERE id=?", (old["id"],))
                    # Messages hang off the session, so the replaced attempt's review and chat go
                    # explicitly. Its running summary went with the attempt row.
                    conn.execute(
                        "DELETE FROM messages WHERE session_id=? AND attempt_number=?", (session_id, number)
                    )
                conn.execute(
                    "INSERT INTO attempts(id,session_id,number,created_at,audio_file,wav_file,mime,duration,"
                    "prompt_kind,style,target_duration) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        identifier,
                        session_id,
                        number,
                        db.now(),
                        str(source),
                        str(wav),
                        mime,
                        seconds,
                        values["prompt_kind"],
                        values["style"],
                        values["target_duration"],
                    ),
                )
            kept = True
            if old:
                Path(old["audio_file"]).unlink(missing_ok=True)
                Path(old["wav_file"]).unlink(missing_ok=True)
            pipeline.submit(identifier)
        attempt = get_attempt(identifier)
        return _attempt_view(attempt, get_session(attempt["session_id"]))
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
    get_attempt(attempt_id)
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
    snapshot and review message are archived; the recording, transcript and schedule are kept:
    an attempt that already had a review doesn't reschedule the spaced review again."""
    with mutation_lock, coach_reply_guard():
        attempt = get_attempt(attempt_id)
        if attempt["status"] in {"pending", "processing"}:
            raise HTTPException(409, "The coach is still reviewing this attempt. Wait for it to finish.")
        # A too-short attempt has a review with no scores: it never scheduled, so it still may.
        review = (json.loads(attempt["analysis"]) if attempt["analysis"] else {}).get("review") or {}
        reviewed = bool(attempt["assessment"]) or bool(review.get("scores"))
        with db.connect() as conn:
            archive(conn, attempt)
            if reviewed:
                conn.execute(
                    "UPDATE attempts SET scheduled_at=COALESCE(scheduled_at,?) WHERE id=?", (db.now(), attempt_id)
                )
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


@contextmanager
def coach_reply_guard():
    if not tutor_lock.acquire(blocking=False):
        raise HTTPException(409, "Wait for the coach to finish answering before regenerating the review.")
    try:
        yield
    finally:
        tutor_lock.release()


@app.get("/api/attempts/{attempt_id}/analysis-history")
def analysis_history(attempt_id: str):
    get_attempt(attempt_id)
    result = []
    for row in db.all_rows("SELECT * FROM analysis_history WHERE attempt_id=? ORDER BY id DESC", (attempt_id,)):
        snapshot = json.loads(row["snapshot"])
        snapshot["review_parts"] = markers.resolve(snapshot.get("review_message") or "", snapshot.get("lines") or [])
        result.append({"id": row["id"], "created_at": row["created_at"], "attempt": snapshot})
    return result


@app.put("/api/messages/{message_id}/feedback")
def rate_response(message_id: int, body: ResponseFeedback):
    try:
        return {"feedback": feedback.save(message_id, body.model_dump())}
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/api/feedback/export")
def export_feedback():
    return JSONResponse(feedback.export(), headers={
        "Content-Disposition": 'attachment; filename="speaklab-feedback.json"',
    })


@app.post("/api/sessions/{session_id}/chat")
def coach_chat(session_id: str, body: ChatInput):
    message = body.message.strip()
    if not message:
        raise HTTPException(422, "Write a message for the coach.")
    # Atomically check the attempt and reserve the model, against model changes/regeneration.
    with mutation_lock:
        get_session(session_id)
        attempt = db.one(
            "SELECT * FROM attempts WHERE session_id=? AND number=?", (session_id, body.attempt_number)
        )
        if not attempt:
            raise HTTPException(409, f"Record attempt {body.attempt_number} before chatting about it.")
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
