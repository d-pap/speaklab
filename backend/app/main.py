import json
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path
from threading import Lock

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool
from starlette.staticfiles import StaticFiles

from . import db, models, pipeline, progress
from .audio import decode, detect_container
from .config import ROOT, settings
from .curriculum import CATALOG, TOPICS, lesson, prompt, public_topic, recommend
from .schemas import (
    Completion,
    ModelSelection,
    Reanalysis,
    SessionCreate,
    StageChange,
    TranscriptEdit,
    TutorInput,
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
tutor_lock = Lock()


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.initialize()
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


@app.put("/api/settings/model")
def select_model(body: ModelSelection):
    with mutation_lock:
        if db.one("SELECT id FROM attempts WHERE status IN ('pending','processing') LIMIT 1"):
            raise HTTPException(409, "Wait for recording analysis to finish before changing models.")
        if not tutor_lock.acquire(blocking=False):
            raise HTTPException(409, "Wait for the tutor to finish answering before changing models.")
        try:
            models.validate_model_selection(body.model)
            db.execute(
                "INSERT INTO app_settings(key,value) VALUES('ollama_model',?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (body.model,),
            )
            settings.ollama_model = body.model
        except models.ServiceUnavailable as exc:
            raise HTTPException(503, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        finally:
            tutor_lock.release()
    return {"selected": settings.ollama_model}


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
        "SELECT s.topic_id, a.assessment FROM sessions s JOIN attempts a ON a.session_id=s.id AND a.number=2 WHERE s.completed_at IS NOT NULL ORDER BY s.created_at"
    ):
        score = progress.mastery(json.loads(row["assessment"]) if row["assessment"] else None)
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
        row["topic"] = public_topic(CATALOG[row["topic_id"]])
        attempts = db.all_rows(
            "SELECT number, assessment, acoustics FROM attempts WHERE session_id=? ORDER BY number",
            (row["id"],),
        )
        row["attempt_count"] = len(attempts)
        row["coverage"] = []
        for attempt in attempts:
            a = json.loads(attempt["assessment"]) if attempt["assessment"] else None
            m = json.loads(attempt["acoustics"]) if attempt["acoustics"] else {}
            row["coverage"].append(
                {
                    "attempt": attempt["number"],
                    "correct": sum(c["status"] == "correct" for c in a["concepts"]) if a else None,
                    "total": len(CATALOG[row["topic_id"]]["concepts"]),
                    "wpm": m.get("wpm"),
                    "pitch_range_semitones": m.get("pitch_range_semitones"),
                    "filler_count": m.get("filler_count"),
                }
            )
    return rows


@app.get("/api/reviews")
def reviews():
    rows = db.all_rows("SELECT * FROM reviews ORDER BY due")
    return [
        {**r, "topic": public_topic(CATALOG[r["topic_id"]]), "overdue": r["due"] <= date.today().isoformat()}
        for r in rows
    ]


@app.get("/api/sessions/{session_id}")
def session_detail(session_id: str):
    session = get_session(session_id)
    topic = CATALOG[session["topic_id"]]
    session["topic"] = public_topic(topic)
    session["prompt"] = prompt(topic, session["prompt_kind"])
    session["attempts"] = [
        db.attempt_public(a)
        for a in db.all_rows("SELECT * FROM attempts WHERE session_id=? ORDER BY number", (session_id,))
    ]
    session["messages"] = db.all_rows("SELECT * FROM messages WHERE session_id=? ORDER BY id", (session_id,))
    return session


@app.put("/api/sessions/{session_id}/stage")
def stage(session_id: str, body: StageChange):
    with mutation_lock:
        session = get_session(session_id)
        if session["completed_at"]:
            raise HTTPException(409, "This session is complete.")
        if body.stage != "record1":
            require_first(session_id)
        if body.stage == "record1" and session["stage"] != "record1":
            raise HTTPException(409, "The cold attempt is preserved after feedback is revealed.")
        if body.stage == "compare" and not db.one(
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
                conn.execute(
                    "INSERT INTO attempts(id,session_id,number,created_at,audio_file,wav_file,mime,duration) VALUES(?,?,?,?,?,?,?,?)",
                    (identifier, session_id, number, db.now(), str(source), str(wav), mime, duration),
                )
                conn.execute(
                    "UPDATE sessions SET stage=? WHERE id=?",
                    ("feedback" if number == 1 else "compare", session_id),
                )
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
        db.execute("UPDATE attempts SET status='pending', errors='{}' WHERE id=?", (attempt_id,))
        pipeline.submit(attempt_id)
    return {"status": "pending"}


@app.put("/api/attempts/{attempt_id}/transcript")
def edit_transcript(attempt_id: str, body: TranscriptEdit):
    if not body.text.strip():
        raise HTTPException(422, "Enter a nonempty transcript.")
    with mutation_lock:
        attempt = get_attempt(attempt_id)
        require_editable(attempt)
        db.execute(
            "UPDATE attempts SET transcript=?, transcript_source='manual', transcription_version=0, retranscribe=0, segments='[]', assessment=NULL, acoustics=NULL, status='pending', errors='{}' WHERE id=?",
            (body.text.strip(), attempt_id),
        )
        pipeline.submit(attempt_id)
    return {"status": "pending"}


@app.post("/api/attempts/{attempt_id}/reanalyze")
def reanalyze(attempt_id: str, body: Reanalysis):
    with mutation_lock:
        attempt = get_attempt(attempt_id)
        if attempt["status"] in {"pending", "processing"}:
            raise HTTPException(409, "Analysis is already running.")
        if body.retranscribe and attempt["transcript_source"] == "manual":
            raise HTTPException(
                409, "A manually edited transcript is preserved. Reanalyze without retranscribing."
            )
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO analysis_history(attempt_id,created_at,snapshot) VALUES(?,?,?)",
                (attempt_id, db.now(), json.dumps(db.attempt_public(attempt))),
            )
            conn.execute(
                "UPDATE attempts SET assessment=NULL, acoustics=NULL, retranscribe=?, status='pending', errors='{}' WHERE id=?",
                (int(body.retranscribe), attempt_id),
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


@app.get("/api/sessions/{session_id}/lesson")
def get_lesson(session_id: str):
    session = get_session(session_id)
    require_first(session_id)
    attempt = db.one("SELECT assessment FROM attempts WHERE session_id=? AND number=1", (session_id,))
    assessment = json.loads(attempt["assessment"]) if attempt["assessment"] else None
    return lesson(CATALOG[session["topic_id"]], assessment)


@app.post("/api/sessions/{session_id}/tutor")
def chat(session_id: str, body: TutorInput):
    session = get_session(session_id)
    require_first(session_id)
    if session["completed_at"]:
        raise HTTPException(409, "This session is complete. Start a new session to continue tutoring.")
    if not tutor_lock.acquire(blocking=False):
        raise HTTPException(409, "The local tutor is already answering. Try again shortly.")
    try:
        first = db.attempt_public(
            db.one("SELECT * FROM attempts WHERE session_id=? AND number=1", (session_id,))
        )
        history = db.all_rows("SELECT * FROM messages WHERE session_id=? ORDER BY id", (session_id,))
        reply = models.tutor(
            CATALOG[session["topic_id"]],
            first["transcript"] or "No transcript available.",
            first["assessment"],
            history,
            body.message,
        )
        answer = reply["answer"] + (
            "\n\nCheck your understanding: " + reply["check_question"] if reply["check_question"] else ""
        )
        with db.connect() as conn:
            for role, text in (("user", body.message), ("assistant", answer)):
                conn.execute(
                    "INSERT INTO messages(session_id,role,content,created_at) VALUES(?,?,?,?)",
                    (session_id, role, text, db.now()),
                )
        return {"answer": answer}
    except models.ServiceUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    finally:
        tutor_lock.release()


@app.get("/api/sessions/{session_id}/comparison")
def comparison(session_id: str):
    session = session_detail(session_id)
    if len(session["attempts"]) != 2:
        raise HTTPException(409, "Save both attempts to compare them.")
    prior_row = db.one(
        "SELECT a.assessment, s.created_at, s.id FROM sessions s JOIN attempts a ON s.id=a.session_id AND a.number=2 WHERE s.topic_id=? AND s.completed_at IS NOT NULL AND s.created_at<? ORDER BY s.created_at DESC LIMIT 1",
        (session["topic_id"], session["created_at"]),
    )
    prior = None
    if prior_row:
        before = json.loads(prior_row["assessment"]) if prior_row["assessment"] else None
        cold = session["attempts"][0]["assessment"]
        demonstrated = (
            {c["concept_id"] for c in before["concepts"] if c["status"] == "correct"} if before else set()
        )
        recalled = {c["concept_id"] for c in cold["concepts"] if c["status"] == "correct"} if cold else set()
        prior = {
            "id": prior_row["id"],
            "date": prior_row["created_at"],
            "available": bool(before and cold),
            "previously_demonstrated": len(demonstrated),
            "recalled": len(demonstrated & recalled),
            "days_elapsed": (
                datetime.fromisoformat(session["created_at"]).astimezone().date()
                - datetime.fromisoformat(prior_row["created_at"]).astimezone().date()
            ).days,
        }
    return {
        **progress.compare(*session["attempts"], prior),
        "concepts": [{"id": c["id"], "name": c["name"]} for c in CATALOG[session["topic_id"]]["concepts"]],
    }


@app.post("/api/sessions/{session_id}/complete")
def complete(session_id: str, body: Completion):
    with mutation_lock:
        session = get_session(session_id)
        if session["completed_at"]:
            return session_detail(session_id)
        attempts = db.all_rows("SELECT * FROM attempts WHERE session_id=? ORDER BY number", (session_id,))
        if len(attempts) != 2:
            raise HTTPException(409, "Save both recordings before completing the session.")
        if any(a["status"] in {"pending", "processing"} for a in attempts):
            raise HTTPException(409, "Let the current analysis finish before scheduling your review.")
        assessment = json.loads(attempts[1]["assessment"]) if attempts[1]["assessment"] else None
        previous = db.one(
            "SELECT r.*, s.completed_at AS last_completed_at FROM reviews r JOIN sessions s ON s.id=r.last_session_id WHERE r.topic_id=?",
            (session["topic_id"],),
        )
        interval, repetitions, due = progress.schedule(previous, body.recall, progress.mastery(assessment))
        with db.connect() as conn:
            conn.execute(
                "UPDATE sessions SET completed_at=?, recall=?, review_due=?, stage='compare' WHERE id=?",
                (db.now(), body.recall, due, session_id),
            )
            conn.execute(
                "INSERT INTO reviews(topic_id,interval_days,repetitions,due,last_session_id) VALUES(?,?,?,?,?) ON CONFLICT(topic_id) DO UPDATE SET interval_days=excluded.interval_days,repetitions=excluded.repetitions,due=excluded.due,last_session_id=excluded.last_session_id",
                (session["topic_id"], interval, repetitions, due, session_id),
            )
    return session_detail(session_id)
