"""Two-phase analysis of an attempt.

Phase 1 (`process`): acoustics, transcription, transcript lines and the voice summary,
then the memory, technical and communication passes. Phase 2 (`write`): the review
structure and the review message, once the learner has sent or skipped their note,
or the note has timed out. Each pass is saved as it finishes, so a later failure keeps
earlier results, and a retry re-runs only the passes that are not done.
"""

import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import coach, db, feedback, llm, memory, models, progress, threads, transcript, voice
from .audio import acoustic_features, delivery_suggestions, transcript_metrics
from .curriculum import prompt, topic_for
from .speech import speech_observations, vocal_foundations

log = logging.getLogger("speaklab.pipeline")
executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="speaklab-analysis")

NOTE_TIMEOUT_SECONDS = 300
PASS_ORDER = ("memory", "technical", "communication", "writer")
FAILED_UNEXPECTEDLY = "This step stopped unexpectedly. Your recording is safe; retry."
# Guards the hand-off between phase 1, the learner's note and the note timeout.
_handoff = threading.RLock()


def submit(attempt_id: str):
    executor.submit(process, attempt_id)


def submit_writer(attempt_id: str):
    executor.submit(write, attempt_id)


def after_review_written(attempt_id: str) -> None:
    """Reschedule the topic's spaced review from this attempt's technical results.

    Once per attempt (retries, transcript edits and re-reviews don't schedule it again), and only
    for the thread's latest attempt. An attempt without concept results, such as a too-short one,
    never reaches here with results and leaves the schedule alone.
    """
    attempt = db.one(
        "SELECT a.*, s.topic_id FROM attempts a JOIN sessions s ON s.id=a.session_id WHERE a.id=?",
        (attempt_id,),
    )
    if not attempt or attempt["scheduled_at"]:
        return
    latest = db.one("SELECT MAX(number) AS number FROM attempts WHERE session_id=?", (attempt["session_id"],))
    if attempt["number"] != latest["number"]:
        return
    score = progress.mastery(progress.concept_results(attempt))
    if score is None:
        return
    recall = progress.derived_recall(score)
    previous = db.one("SELECT * FROM reviews WHERE topic_id=?", (attempt["topic_id"],))
    if previous:
        # For the same-day cap in progress.schedule: when the latest earlier attempt that scheduled
        # this topic was recorded. Next attempts open the next day, so this rarely caps anything.
        earlier = db.one(
            "SELECT created_at FROM attempts WHERE session_id=? AND id<>? AND scheduled_at IS NOT NULL "
            "ORDER BY number DESC LIMIT 1",
            (attempt["session_id"], attempt_id),
        )
        previous["last_completed_at"] = earlier["created_at"] if earlier else None
    interval, repetitions, due = progress.schedule(previous, recall, score)
    with db.connect() as conn:
        claimed = conn.execute(
            "UPDATE attempts SET scheduled_at=? WHERE id=? AND scheduled_at IS NULL", (db.now(), attempt_id)
        )
        if claimed.rowcount:
            conn.execute(
                "INSERT INTO reviews(topic_id,interval_days,repetitions,due,last_session_id) VALUES(?,?,?,?,?) "
                "ON CONFLICT(topic_id) DO UPDATE SET interval_days=excluded.interval_days,"
                "repetitions=excluded.repetitions,due=excluded.due,last_session_id=excluded.last_session_id",
                (attempt["topic_id"], interval, repetitions, due, attempt["session_id"]),
            )


# Stored state


def _new_analysis() -> dict:
    return {
        "version": 1,
        "voice_summary": [],
        "stats": {},
        "passes": {name: {"status": "pending", "model": None, "error": None} for name in PASS_ORDER},
        "technical": None,
        "communication": None,
        "timing": [],
        "review": None,
    }


def _load(attempt_id: str) -> tuple[dict | None, dict | None]:
    attempt = db.one("SELECT * FROM attempts WHERE id=?", (attempt_id,))
    analysis = json.loads(attempt["analysis"]) if attempt and attempt["analysis"] else None
    return attempt, analysis


def _save(attempt_id: str, analysis: dict):
    db.execute("UPDATE attempts SET analysis=? WHERE id=?", (json.dumps(analysis), attempt_id))


def _prerequisites_done(analysis: dict | None) -> bool:
    if not analysis or (analysis.get("review") or {}).get("too_short"):
        return False
    passes = analysis["passes"]
    return passes["technical"]["status"] == "done" and passes["communication"]["status"] == "done"


def phase1_done(attempt: dict) -> bool:
    """Phase 1 finished and the writer's inputs are ready. The one definition used by the note
    endpoint, the timeout and the restart sweep."""
    if attempt["status"] in ("pending", "processing") or not attempt["analysis"]:
        return False
    return _prerequisites_done(json.loads(attempt["analysis"]))


def _final_status(attempt_id: str, errors: dict, analysis: dict | None) -> str:
    failed = analysis and any(p["status"] == "failed" for p in analysis["passes"].values())
    status = "partial" if errors or failed else "ready"
    db.execute("UPDATE attempts SET status=?, errors=? WHERE id=?", (status, json.dumps(errors), attempt_id))
    return status


def _delete_review(attempt: dict):
    db.execute(
        "DELETE FROM messages WHERE session_id=? AND attempt_number=? AND kind='review'",
        (attempt["session_id"], attempt["number"]),
    )


def _run_pass(attempt_id: str, analysis: dict, name: str, run) -> bool:
    """Run one pass, saving its status, model and error before and after. True when done."""
    if analysis["passes"][name]["status"] == "done":
        return True
    analysis["passes"][name] = {"status": "running", "model": None, "error": None}
    _save(attempt_id, analysis)
    try:
        model_used = run()
        analysis["passes"][name] = {"status": "done", "model": model_used, "error": None}
    except models.ServiceUnavailable as exc:
        analysis["passes"][name] = {"status": "failed", "model": None, "error": str(exc)}
    except Exception:
        log.exception("pass_failed", extra={"attempt_id": attempt_id})
        analysis["passes"][name] = {"status": "failed", "model": None, "error": FAILED_UNEXPECTEDLY}
    _save(attempt_id, analysis)
    return analysis["passes"][name]["status"] == "done"


# Phase 1


def _measure(attempt: dict, session: dict, errors: dict) -> tuple[dict | None, str | None, list[dict]]:
    attempt_id = attempt["id"]
    metrics = json.loads(attempt["acoustics"]) if attempt["acoustics"] else None
    text = attempt["transcript"]
    segments = json.loads(attempt["segments"]) if attempt["segments"] else []
    if metrics is None or metrics.get("acoustic_version") != 2:
        try:
            metrics = acoustic_features(Path(attempt["wav_file"]))
            db.execute("UPDATE attempts SET acoustics=? WHERE id=?", (json.dumps(metrics), attempt_id))
        except Exception:
            errors["acoustics"] = "Acoustic extraction failed. Your audio is saved; retry analysis."
            log.warning("acoustics_failed", extra={"attempt_id": attempt_id})
    if not text or attempt.get("retranscribe"):
        try:
            text, segments = models.transcribe(Path(attempt["wav_file"]), attempt["duration"])
            db.execute(
                "UPDATE attempts SET transcript=?, segments=?, transcript_source='whisper', transcription_version=2, retranscribe=0 WHERE id=?",
                (text, json.dumps(segments), attempt_id),
            )
        except models.ServiceUnavailable as exc:
            errors["transcription"] = str(exc)
    if text and "transcription" not in errors:
        metrics = {**(metrics or {}), **transcript_metrics(text, attempt["duration"], segments)}
        metrics.update(speech_observations(text, attempt["duration"], segments))
        style = threads.attempt_settings(attempt, session)["style"]
        metrics["suggestions"] = delivery_suggestions(metrics, style)
        metrics["vocal_foundations"] = vocal_foundations(metrics, style)
        db.execute("UPDATE attempts SET acoustics=? WHERE id=?", (json.dumps(metrics), attempt_id))
    return metrics, text, segments


def _analyse(attempt: dict, session: dict, metrics: dict | None, text: str, segments: list[dict]) -> dict:
    attempt_id = attempt["id"]
    metrics = metrics or {}
    lines = transcript.build_lines(text, segments)
    tokens = transcript.inline_tokens(
        lines, segments, metrics.get("filler_events") or [], metrics.get("pauses") or []
    )
    analysis = json.loads(attempt["analysis"]) if attempt["analysis"] else None
    stored_lines = json.loads(attempt["lines"]) if attempt["lines"] else None
    if analysis is None or stored_lines != lines:
        # New or changed transcript: earlier results cite line IDs that no longer match.
        if analysis is not None:
            _delete_review(attempt)
        analysis = _new_analysis()
        if attempt["note_state"] == "legacy":
            # A legacy attempt reviewed by the new coach no longer shows the legacy summary.
            db.execute("UPDATE attempts SET note_state='skipped' WHERE id=?", (attempt_id,))
    analysis["stats"] = transcript.stats(tokens, attempt["duration"])
    analysis["voice_summary"] = voice.voice_summary(metrics, lines, tokens)
    db.execute(
        "UPDATE attempts SET lines=?, tokens=?, analysis=? WHERE id=?",
        (json.dumps(lines), json.dumps(tokens), json.dumps(analysis), attempt_id),
    )

    if coach.too_short(lines):
        # No scores for a microphone test; the review page says to record again.
        analysis["review"] = {"too_short": True}
        for entry in analysis["passes"].values():
            entry.update(status="skipped", error=None)
        _save(attempt_id, analysis)
        return analysis

    topic = topic_for(session["topic_id"])
    question = prompt(topic, threads.attempt_settings(attempt, session)["prompt_kind"])

    def run_memory():
        result = memory.fold_in()
        if result is None and memory.call_state.error:
            raise models.ServiceUnavailable(memory.call_state.error)
        return result["model"] if result else None

    def run_technical():
        analysis["technical"], model_used = coach.technical_pass(topic, question, lines)
        return model_used

    def run_communication():
        analysis["communication"], model_used = coach.communication_pass(
            lines,
            analysis["voice_summary"],
            memory.current_notes()["content"],
            {"prompt": question, "duration": attempt["duration"]},
        )
        analysis["communication"] = coach.check_coaching_findings(analysis["communication"], topic, question, lines)
        analysis["timing"] = coach.section_timing(
            analysis["communication"]["sections"], lines, attempt["duration"]
        )
        return model_used

    # Memory first, so the communication pass judges focus areas with everything said before.
    # Its failure is recorded but doesn't block the other passes.
    _run_pass(attempt_id, analysis, "memory", run_memory)
    _run_pass(attempt_id, analysis, "technical", run_technical)
    _run_pass(attempt_id, analysis, "communication", run_communication)
    return analysis


def process(attempt_id: str):
    attempt = db.one("SELECT * FROM attempts WHERE id=?", (attempt_id,))
    if not attempt:
        return
    db.execute("UPDATE attempts SET status='processing' WHERE id=?", (attempt_id,))
    session = db.one("SELECT * FROM sessions WHERE id=?", (attempt["session_id"],))
    errors: dict = {}
    analysis = None
    try:
        metrics, text, segments = _measure(attempt, session, errors)
        if text and "transcription" not in errors:
            attempt = db.one("SELECT * FROM attempts WHERE id=?", (attempt_id,))
            analysis = _analyse(attempt, session, metrics, text, segments)
        elif not text:
            errors["review"] = "The coach needs a transcript. Retry transcription or enter the transcript manually."
    except Exception:
        errors["processing"] = "Analysis stopped unexpectedly. Your recording is safe; retry."
        log.exception("analysis_failed", extra={"attempt_id": attempt_id})

    start_writer, timer_delay = False, None
    with _handoff:
        current = _load(attempt_id)[1]
        if analysis is not None and not (analysis["review"] or {}).get("too_short"):
            ready = _prerequisites_done(analysis)
            note = db.one("SELECT note_state, note_deadline FROM attempts WHERE id=?", (attempt_id,))
            writer = analysis["passes"]["writer"]
            if note["note_state"] != "pending":
                start_writer = ready and writer["status"] != "done"
                if start_writer:
                    writer.update(status="pending", error=None)
            else:
                # A failed prerequisite leaves the writer pending, not waiting; the note still times out.
                writer.update(status="waiting" if ready else "pending", error=None)
                deadline = note["note_deadline"] or (
                    datetime.now(timezone.utc) + timedelta(seconds=NOTE_TIMEOUT_SECONDS)
                ).isoformat()
                db.execute("UPDATE attempts SET note_deadline=? WHERE id=?", (deadline, attempt_id))
                remaining = datetime.fromisoformat(deadline) - datetime.now(timezone.utc)
                timer_delay = max(0.0, remaining.total_seconds())
            _save(attempt_id, analysis)
            current = analysis
        # Finalize before any hand-off: the writer may run inline and sets its own status.
        status = _final_status(attempt_id, errors, current)
    log.info("analysis_finished", extra={"attempt_id": attempt_id, "components_failed": list(errors)})
    if start_writer:
        submit_writer(attempt_id)
    elif timer_delay is not None:
        # The fast path; sweep_note_deadlines covers a restart during the wait.
        timer = threading.Timer(timer_delay, auto_skip, args=(attempt_id,))
        timer.daemon = True
        timer.start()
    return status


# The learner's note and its timeout


def _queue_writer(attempt_id: str) -> bool:
    """With the hand-off lock held: mark the writer queued if phase 1 is done and it hasn't run."""
    attempt, analysis = _load(attempt_id)
    if not attempt or not phase1_done(attempt):
        return False
    writer = analysis["passes"]["writer"]
    if writer["status"] not in ("waiting", "pending"):
        return False
    writer.update(status="pending", error=None)
    _save(attempt_id, analysis)
    return True


def submit_note(attempt_id: str, text: str | None, skip: bool) -> bool:
    """Record the learner's note, or a skip. False when it was already sent or skipped."""
    with _handoff:
        with db.connect() as conn:
            changed = conn.execute(
                "UPDATE attempts SET note_state=?, learner_note=? WHERE id=? AND note_state='pending'",
                ("skipped" if skip else "submitted", None if skip else text, attempt_id),
            ).rowcount
        if not changed:
            return False
        start = _queue_writer(attempt_id)  # otherwise phase 1 picks the note up when it finishes
    if start:
        submit_writer(attempt_id)
    return True


def auto_skip(attempt_id: str):
    with _handoff:
        with db.connect() as conn:
            changed = conn.execute(
                "UPDATE attempts SET note_state='skipped' WHERE id=? AND note_state='pending'", (attempt_id,)
            ).rowcount
        start = bool(changed) and _queue_writer(attempt_id)
    if start:
        submit_writer(attempt_id)


def recover_writers() -> None:
    """At startup: re-queue writers that were queued, but not started, when the process stopped.

    A note sent or skipped commits before the writer runs, so a restart in between would
    otherwise leave the review missing with no error. An attempt interrupted mid-write is
    marked `interrupted` by db.initialize() and recovers through Retry instead.
    """
    for row in db.all_rows(
        "SELECT * FROM attempts WHERE note_state<>'pending' AND status IN ('ready','partial') AND analysis IS NOT NULL"
    ):
        writer = json.loads(row["analysis"])["passes"]["writer"]
        if phase1_done(row) and writer["status"] in ("pending", "waiting"):
            with _handoff:
                queued = _queue_writer(row["id"])
            if queued:
                submit_writer(row["id"])


def sweep_note_deadlines() -> None:
    """Skip every overdue note whose phase 1 is done. Runs at startup and on session reads,
    so a restart during the wait can't leave a review stuck."""
    now = datetime.now(timezone.utc).isoformat()
    for row in db.all_rows(
        "SELECT * FROM attempts WHERE note_state='pending' AND note_deadline IS NOT NULL AND note_deadline<=?",
        (now,),
    ):
        if phase1_done(row):
            auto_skip(row["id"])


# Phase 2


def _previous_attempt(attempt: dict) -> tuple[dict | None, dict | None]:
    """The previous attempt's review on the same thread, and both questions when its question
    type differs from this attempt's."""
    if attempt["number"] < 2:
        return None, None
    before = db.one(
        "SELECT * FROM attempts WHERE session_id=? AND number=?", (attempt["session_id"], attempt["number"] - 1)
    )
    if not before:
        return None, None
    session = db.one("SELECT * FROM sessions WHERE id=?", (attempt["session_id"],))
    review = (json.loads(before["analysis"]) if before["analysis"] else {}).get("review")
    kind = threads.attempt_settings(attempt, session)["prompt_kind"]
    previous_kind = threads.attempt_settings(before, session)["prompt_kind"]
    change = None
    if kind != previous_kind:
        topic = topic_for(session["topic_id"])
        change = {
            "previous_question": prompt(topic, previous_kind),
            "question": prompt(topic, kind),
        }
    return review, change


def write(attempt_id: str):
    attempt, analysis = _load(attempt_id)
    if not attempt or attempt["note_state"] == "pending" or not _prerequisites_done(analysis):
        return  # a pass whose prerequisite failed stays pending
    writer = analysis["passes"]["writer"]
    if writer["status"] == "done":
        return
    db.execute("UPDATE attempts SET status='processing' WHERE id=?", (attempt_id,))
    writer.update(status="running", error=None)
    _save(attempt_id, analysis)
    written = False
    try:
        lines = json.loads(attempt["lines"])
        notes = memory.current_notes()["content"]
        session = db.one("SELECT * FROM sessions WHERE id=?", (attempt["session_id"],))
        topic = topic_for(session["topic_id"])
        question = prompt(topic, threads.attempt_settings(attempt, session)["prompt_kind"])
        previous_review, question_change = _previous_attempt(attempt)
        if not analysis["review"]:
            analysis["review"], writer["model"] = coach.review_structure_pass(
                analysis["technical"],
                analysis["communication"],
                analysis["timing"],
                notes,
                attempt["learner_note"],
                previous_review,
                question_change, question=question, lines=lines, topic_core=topic.get("core", ""),
            )
            _save(attempt_id, analysis)  # the structure survives a failed message
        with llm.capture_text_calls() as calls:
            text, model_used = coach.review_message_pass(
                lines,
                analysis["technical"],
                analysis["communication"],
                analysis["timing"],
                analysis["review"],
                notes,
                attempt["learner_note"],
                question_change, question=question, topic_core=topic.get("core", ""),
                worked_example=topic.get("example", ""), voice_summary=analysis.get("voice_summary"),
            )
        context = feedback.generation_context({**attempt, "analysis": json.dumps(analysis)}, session, calls)
        warning = coach.call_state.warning  # thread-local: read in the thread that ran the pass
        with db.connect() as conn:
            conn.execute(
                "DELETE FROM messages WHERE session_id=? AND attempt_number=? AND kind='review'",
                (attempt["session_id"], attempt["number"]),
            )
            conn.execute(
                "INSERT INTO messages(session_id,role,content,created_at,attempt_number,kind,model,generation_context) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (attempt["session_id"], "assistant", text, db.now(), attempt["number"], "review", model_used,
                 json.dumps(context)),
            )
        writer.update(status="done", model=model_used, error=None, warning=warning)
        written = True
    except models.ServiceUnavailable as exc:
        writer.update(status="failed", error=str(exc))
    except Exception:
        log.exception("writer_failed", extra={"attempt_id": attempt_id})
        writer.update(status="failed", error=FAILED_UNEXPECTEDLY)
    _save(attempt_id, analysis)
    _final_status(attempt_id, json.loads(attempt["errors"] or "{}"), analysis)
    if written:
        after_review_written(attempt_id)


def retry(attempt_id: str):
    """Re-run from the first pass that isn't done. A pending note is still waited for."""
    _attempt, analysis = _load(attempt_id)
    if analysis:
        for entry in analysis["passes"].values():
            if entry["status"] in ("failed", "running"):
                entry.update(status="pending", error=None)
        _save(attempt_id, analysis)
    db.execute("UPDATE attempts SET status='pending', errors='{}' WHERE id=?", (attempt_id,))
    submit(attempt_id)
