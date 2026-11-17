"""Topic threads: each topic has at most one practice thread, the `sessions` row of its first
recording. Everything here is derived from the thread's attempts: when the next attempt opens,
whether recording is allowed, which attempt may be replaced, and the latest checklist.

The thread is found by topic: the earliest session with at least one attempt. Sessions without
attempts (old topic clicks) and rows emptied by the v5 merge are never threads, and their stage,
completed_at, recall and review_due columns are not read.
"""

import json
from datetime import date, datetime, timedelta

from . import db

NEXT_TOMORROW = "Next attempt opens tomorrow"


def today() -> date:
    """The server's local date. One seam, so tests can move the calendar."""
    return date.today()


def local_date(timestamp: str) -> date:
    return datetime.fromisoformat(timestamp).astimezone().date()


_THREAD = (
    "SELECT s.* FROM sessions s WHERE s.topic_id=? "
    "AND EXISTS (SELECT 1 FROM attempts a WHERE a.session_id=s.id) ORDER BY s.created_at, s.id LIMIT 1"
)


def thread_for_topic(topic_id: str) -> dict | None:
    return db.one(_THREAD, (topic_id,))


def all_threads() -> list[dict]:
    """Every topic's thread, one per topic."""
    rows = db.all_rows(
        "SELECT s.* FROM sessions s WHERE EXISTS (SELECT 1 FROM attempts a WHERE a.session_id=s.id) "
        "ORDER BY s.topic_id, s.created_at, s.id"
    )
    threads: dict[str, dict] = {}
    for row in rows:
        threads.setdefault(row["topic_id"], row)
    return list(threads.values())


def attempts(session_id: str) -> list[dict]:
    return db.all_rows("SELECT * FROM attempts WHERE session_id=? ORDER BY number", (session_id,))


def attempt_settings(attempt: dict, session: dict) -> dict:
    """The question type, style and target length an attempt was recorded with. Attempts from
    before topic threads have none of their own and use their session's."""
    return {
        "prompt_kind": attempt.get("prompt_kind") or session["prompt_kind"],
        "style": attempt.get("style") or session["style"],
        "target_duration": attempt.get("target_duration") or session["duration"],
    }


def next_attempt_after(session_id: str) -> str | None:
    latest = db.one(
        "SELECT created_at FROM attempts WHERE session_id=? ORDER BY number DESC LIMIT 1", (session_id,)
    )
    if not latest:
        return None
    return (local_date(latest["created_at"]) + timedelta(days=1)).isoformat()


def _review(attempt: dict) -> dict:
    analysis = json.loads(attempt["analysis"]) if attempt.get("analysis") else {}
    return analysis.get("review") or {}


def too_short(attempt: dict) -> bool:
    return bool(_review(attempt).get("too_short"))


def recording_state(topic_id: str) -> dict:
    """Whether a new recording is allowed now, and which number it gets. `next_number` is the
    number the next recording will have: the replaced number when `replace_number` is set."""
    thread = thread_for_topic(topic_id)
    if not thread:
        return {"can_record": True, "reason": None, "replace_number": None, "next_number": 1}
    latest = db.one(
        "SELECT * FROM attempts WHERE session_id=? ORDER BY number DESC LIMIT 1", (thread["id"],)
    )
    if too_short(latest) and latest["status"] not in ("pending", "processing"):
        # A too-short attempt got no feedback, so it may be recorded again, the same day too.
        number = latest["number"]
        return {"can_record": True, "reason": None, "replace_number": number, "next_number": number}
    opens = next_attempt_after(thread["id"])
    if today().isoformat() >= opens:
        return {"can_record": True, "reason": None, "replace_number": None, "next_number": latest["number"] + 1}
    return {"can_record": False, "reason": NEXT_TOMORROW, "replace_number": None, "next_number": latest["number"] + 1}


CHECKLIST_MAX = 5


def latest_checklist(session_id: str) -> list[str]:
    """The checklist of the most recent attempt that has one: its review's checklist, or, for an
    attempt with no new review structure, the legacy assessment's next_steps. At most 5 items."""
    for attempt in reversed(attempts(session_id)):
        review = _review(attempt)
        checklist = review.get("checklist")
        if not review and attempt.get("assessment"):
            checklist = json.loads(attempt["assessment"]).get("next_steps")
        if checklist and isinstance(checklist, list):
            return [str(item) for item in checklist[:CHECKLIST_MAX]]
    return []
