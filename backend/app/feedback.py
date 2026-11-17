"""Local response feedback. Snapshots survive re-reviews and never trigger inference or training."""

import json

from . import db, threads
from .curriculum import prompt, topic_for


def generation_context(attempt: dict, session: dict, calls: list[dict]) -> dict:
    """Record source context at generation time, separate from the budget-trimmed model input.

    Keep transcript/analysis, not recordings or dense acoustic arrays. Calls hold the actual
    system prompts, model options and raw outputs; marker resolution uses the stored lines.
    """
    chosen = threads.attempt_settings(attempt, session)
    topic = topic_for(session["topic_id"])
    return {
        "version": 1,
        "captured_at": db.now(),
        "topic_id": session["topic_id"],
        "question": prompt(topic, chosen["prompt_kind"]),
        "settings": chosen,
        "attempt_id": attempt["id"],
        "attempt_number": attempt["number"],
        "transcript": attempt.get("transcript"),
        "lines": json.loads(attempt.get("lines") or "[]"),
        "analysis": json.loads(attempt.get("analysis") or "null"),
        "learner_note": attempt.get("learner_note"),
        "calls": calls,
    }


def public_message(message: dict) -> dict:
    return {k: v for k, v in message.items() if k != "generation_context"}


def messages_for_session(session_id: str) -> list[dict]:
    rows = db.all_rows(
        "SELECT id,session_id,role,content,created_at,attempt_number,kind,model "
        "FROM messages WHERE session_id=? ORDER BY id", (session_id,),
    )
    votes = {
        row["message_id"]: public_feedback(row)
        for row in db.all_rows(
            "SELECT f.* FROM response_feedback f JOIN messages m ON f.message_id=m.id WHERE m.session_id=?",
            (session_id,),
        )
    }
    return [{**public_message(m), "feedback": votes.get(m["id"])} for m in rows]


def public_feedback(row: dict) -> dict:
    return {k: row[k] for k in ("id", "rating", "reason", "comment", "preferred_response", "updated_at")}


def save(message_id: int, values: dict) -> dict | None:
    # One transaction prevents a concurrent re-review deleting the message between read and write.
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        message = conn.execute("SELECT * FROM messages WHERE id=?", (message_id,)).fetchone()
        if not message:
            raise LookupError("This response is no longer available. Refresh the topic.")
        message = dict(message)
        if message["role"] != "assistant":
            raise ValueError("Only coach responses can be rated.")
        if values["rating"] is None:
            conn.execute("DELETE FROM response_feedback WHERE message_id=?", (message_id,))
            return None
        context = json.loads(message["generation_context"]) if message["generation_context"] else None
        snapshot = {
            "version": 1,
            "message": public_message(message),
            "context_status": "captured_at_generation" if context else "unavailable_for_older_response",
            "generation": context,
        }
        now = db.now()
        conn.execute(
            "INSERT INTO response_feedback(message_id,rating,reason,comment,preferred_response,created_at,updated_at,snapshot) "
            "VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(message_id) DO UPDATE SET rating=excluded.rating, "
            "reason=excluded.reason, comment=excluded.comment, preferred_response=excluded.preferred_response, "
            "updated_at=excluded.updated_at",
            (message_id, values["rating"], values["reason"], values["comment"].strip(),
             values["preferred_response"].strip(), now, now, json.dumps(snapshot)),
        )
        row = conn.execute("SELECT * FROM response_feedback WHERE message_id=?", (message_id,)).fetchone()
        return public_feedback(dict(row))


def export() -> dict:
    records = db.all_rows("SELECT * FROM response_feedback ORDER BY id")
    return {
        "format": "speaklab-feedback-v1",
        "exported_at": db.now(),
        "purpose": "Uncurated local feedback; not an approved training or evaluation dataset.",
        "records": [{**row, "snapshot": json.loads(row["snapshot"])} for row in records],
    }
