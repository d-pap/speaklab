import json
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import db, models
from .audio import acoustic_features, delivery_suggestions, transcript_metrics
from .curriculum import CATALOG, prompt
from .speech import speech_observations, vocal_foundations

log = logging.getLogger("speaklab.pipeline")
executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="speaklab-analysis")


def submit(attempt_id: str):
    executor.submit(process, attempt_id)


def process(attempt_id: str):
    attempt = db.one("SELECT * FROM attempts WHERE id=?", (attempt_id,))
    if not attempt:
        return
    db.execute("UPDATE attempts SET status='processing' WHERE id=?", (attempt_id,))
    session = db.one("SELECT * FROM sessions WHERE id=?", (attempt["session_id"],))
    errors = {}
    metrics = json.loads(attempt["acoustics"]) if attempt["acoustics"] else None
    transcript = attempt["transcript"]
    segments = json.loads(attempt["segments"]) if attempt["segments"] else []
    try:
        if metrics is None or metrics.get("acoustic_version") != 2:
            try:
                metrics = acoustic_features(Path(attempt["wav_file"]))
                db.execute("UPDATE attempts SET acoustics=? WHERE id=?", (json.dumps(metrics), attempt_id))
            except Exception:
                errors["acoustics"] = "Acoustic extraction failed. Your audio is saved; retry analysis."
                log.warning("acoustics_failed", extra={"attempt_id": attempt_id})
        if not transcript or attempt.get("retranscribe"):
            try:
                transcript, segments = models.transcribe(Path(attempt["wav_file"]), attempt["duration"])
                db.execute(
                    "UPDATE attempts SET transcript=?, segments=?, transcript_source='whisper', transcription_version=2, retranscribe=0 WHERE id=?",
                    (transcript, json.dumps(segments), attempt_id),
                )
            except models.ServiceUnavailable as exc:
                errors["transcription"] = str(exc)
        if transcript and "transcription" not in errors:
            text_metrics = transcript_metrics(transcript, attempt["duration"], segments)
            metrics = {**(metrics or {}), **text_metrics}
            metrics.update(speech_observations(transcript, attempt["duration"], segments))
            metrics["suggestions"] = delivery_suggestions(metrics, session["style"])
            metrics["vocal_foundations"] = vocal_foundations(metrics, session["style"])
            db.execute("UPDATE attempts SET acoustics=? WHERE id=?", (json.dumps(metrics), attempt_id))
            if not attempt["assessment"]:
                try:
                    topic = CATALOG[session["topic_id"]]
                    result = models.assess(
                        topic, transcript, metrics, session["style"], prompt(topic, session["prompt_kind"])
                    )
                    db.execute(
                        "UPDATE attempts SET assessment=? WHERE id=?", (json.dumps(result), attempt_id)
                    )
                except models.ServiceUnavailable as exc:
                    errors["assessment"] = str(exc)
            stored = db.one("SELECT assessment FROM attempts WHERE id=?", (attempt_id,))
            assessment = json.loads(stored["assessment"]) if stored["assessment"] else None
            if assessment and not assessment.get("insights"):
                try:
                    assessment["insights"] = models.review_insights(CATALOG[session["topic_id"]], transcript)
                    db.execute(
                        "UPDATE attempts SET assessment=? WHERE id=?", (json.dumps(assessment), attempt_id)
                    )
                except models.ServiceUnavailable as exc:
                    errors["insights"] = "Factual and vocabulary review is unavailable. " + str(exc)
        elif not transcript:
            errors["assessment"] = (
                "Technical assessment needs a transcript. You can still study the curated lesson."
            )
    except Exception:
        errors["processing"] = "Analysis stopped unexpectedly. Your recording is safe; retry."
        log.exception("analysis_failed", extra={"attempt_id": attempt_id})
    db.execute(
        "UPDATE attempts SET status=?, errors=? WHERE id=?",
        ("partial" if errors else "ready", json.dumps(errors), attempt_id),
    )
    log.info("analysis_finished", extra={"attempt_id": attempt_id, "components_failed": list(errors)})
