"""Coach notes: a short plain-text document about the learner, with every version kept.

The memory pass rewrites the notes from the old notes plus a compact digest of each
attempt reviewed since the last update. It never drops a focus area on its own.
"""

import json
import re
import threading
from datetime import date

from . import db, llm, models
from .coach import _HEADING
from .curriculum import CATALOG

WORD_LIMIT = 400
MAX_LEARNER_MESSAGES = 12
MAX_MESSAGE_CHARS = 600

MEMORY_SYSTEM = (
    "You keep a coach's private notes about one learner who practises spoken technical explanations. "
    "Rewrite the notes so they fold in the attempts supplied, and return only the new notes as plain text.\n"
    "Use these Markdown headings:\n"
    "- one '## Focus: <area>' heading per current focus area, followed by the evidence and since when "
    "(a date from the input). A focus area is a communication skill the learner is working on, such as "
    "structure, pacing or natural playfulness.\n"
    "- '## Recurring struggles', '## Goals' (goals the learner stated) and "
    "'## How they like to be taught'.\n"
    "Keep every '## Focus:' heading from current_notes word for word. Never remove a focus area: when one "
    "shows consistent progress, say so and suggest what might come next. Add a focus area only when the "
    "learner states one ('I'm working on keeping things light') or the same pattern recurs.\n"
    "Pick up what the learner says about their goals and how they like to learn from learner_note and "
    "learner_messages. Prefer patterns over single events, keep dates, and keep it under "
    f"{WORD_LIMIT} words. Do not quote the transcript."
)
REPAIR_SYSTEM = (
    "You fix a draft of a coach's notes about a learner. Return the whole corrected notes as plain text, "
    "keeping the same headings and facts, with every problem listed in problems fixed."
)


class _CallState(threading.local):
    # Why the last fold_in in this thread returned None: an error message, or None for nothing to fold.
    error: str | None = None


call_state = _CallState()


class _NotesProblem(Exception):
    pass


class _NotesChanged(_NotesProblem):
    pass


def _words(text: str) -> int:
    return len(text.split())


def _version(row: dict) -> dict:
    return {**row, "folded_attempt_ids": json.loads(row["folded_attempt_ids"] or "[]")}


def _save(
    content: str,
    source: str,
    folded: list[str] | None = None,
    model: str | None = None,
    expect_current_id: int | None = ...,
) -> dict:
    """Insert a new version. With expect_current_id (None for no notes yet), the insert happens
    only if the newest version is still that one, in the same statement; else _NotesChanged."""
    with db.connect() as conn:
        args = (db.now(), content, source, json.dumps(folded or []), model)
        if expect_current_id is ...:
            cursor = conn.execute(
                "INSERT INTO coach_notes(created_at,content,source,folded_attempt_ids,model) VALUES(?,?,?,?,?)",
                args,
            )
        else:
            cursor = conn.execute(
                "INSERT INTO coach_notes(created_at,content,source,folded_attempt_ids,model) "
                "SELECT ?,?,?,?,? WHERE (SELECT MAX(id) FROM coach_notes) IS ?",
                (*args, expect_current_id),
            )
            if not cursor.rowcount:
                raise _NotesChanged(
                    "Your coach notes changed while the update was running, so the update was discarded. "
                    "The attempts will be folded in next time."
                )
        row = conn.execute("SELECT * FROM coach_notes WHERE id=?", (cursor.lastrowid,)).fetchone()
    return _version(dict(row))


def current_notes() -> dict:
    row = db.one("SELECT id, content, model FROM coach_notes ORDER BY id DESC LIMIT 1")
    return dict(row) if row else {"id": None, "content": "", "model": None}


def versions() -> list[dict]:
    return [_version(row) for row in db.all_rows("SELECT * FROM coach_notes ORDER BY id DESC")]


def save_learner_edit(content: str) -> dict:
    content = content.strip()
    if _words(content) > WORD_LIMIT:
        raise ValueError(f"Keep the coach notes to {WORD_LIMIT} words or fewer.")
    return _save(content, "learner")


def restore(version_id: int) -> dict:
    row = db.one("SELECT content FROM coach_notes WHERE id=?", (version_id,))
    if not row:
        raise LookupError("That version of the coach notes doesn't exist.")
    return _save(row["content"], "restore")


def unfolded_attempts() -> list[dict]:
    folded = set()
    for row in db.all_rows("SELECT folded_attempt_ids FROM coach_notes"):
        folded.update(json.loads(row["folded_attempt_ids"] or "[]"))
    rows = db.all_rows(
        "SELECT a.*, s.topic_id FROM attempts a JOIN sessions s ON s.id=a.session_id "
        "WHERE EXISTS (SELECT 1 FROM messages m WHERE m.session_id=a.session_id "
        "AND m.attempt_number=a.number AND m.kind='review') ORDER BY a.created_at, a.number"
    )
    result = []
    for row in rows:
        if row["id"] in folded:
            continue
        analysis = json.loads(row["analysis"]) if row["analysis"] else {}
        messages = db.all_rows(
            "SELECT role, content, created_at FROM messages WHERE session_id=? AND attempt_number=? "
            "AND kind='chat' ORDER BY id",
            (row["session_id"], row["number"]),
        )
        result.append(
            {
                "id": row["id"],
                "session_id": row["session_id"],
                "number": row["number"],
                "created_at": row["created_at"],
                "topic_id": row["topic_id"],
                "lines": json.loads(row["lines"]) if row["lines"] else [],
                "review": analysis.get("review"),
                "learner_note": row["learner_note"],
                "messages": messages,
            }
        )
    return result


# The memory pass


def _digest(item: dict) -> dict:
    review = item["review"] or {}
    topic = CATALOG.get(item["topic_id"], {})
    learner = [m["content"][:MAX_MESSAGE_CHARS] for m in item["messages"] if m["role"] == "user"]
    return {
        "date": item["created_at"][:10],
        "topic": topic.get("title", item["topic_id"]),
        "attempt": item["number"],
        "scores": [{"name": s["name"], "score": s["score"]} for s in review.get("scores", [])],
        "key_points": [p["text"] for p in review.get("key_points", [])],
        "learner_note": item["learner_note"] or "",
        "learner_messages": learner[-MAX_LEARNER_MESSAGES:],
    }


def _payload(notes: str, digests: list[dict]) -> dict:
    return {"today": date.today().isoformat(), "current_notes": notes, "attempts": digests}


def _messages(system: str, payload: dict) -> list[dict]:
    return [{"role": "system", "content": system}, {"role": "user", "content": json.dumps(payload)}]


def _estimate(payload: dict) -> int:
    return llm._estimate_tokens(_messages(MEMORY_SYSTEM, payload))


def _budget() -> int:
    return llm.prompt_budget("memory")


def _normalise_heading(line: str) -> str:
    text = re.sub(r"\([^)]*\)", "", line.strip().lstrip("#")).strip().rstrip(":")
    return " ".join(text.split()).casefold()


def _focus_sections(notes: str) -> dict[str, str]:
    """Each heading that names a focus area, mapped to its section text (heading included)."""
    sections: dict[str, list[str]] = {}
    current = None
    for line in (notes or "").splitlines():
        if _HEADING.match(line):
            current = _normalise_heading(line) if "focus" in line.lower() else None
            if current is not None:
                sections.setdefault(current, [])
        if current is not None:
            sections[current].append(line)
    return {key: "\n".join(lines).strip() for key, lines in sections.items()}


def _clean(text: str) -> str:
    return re.sub(r"^```[a-z]*\s*|\s*```$", "", text.strip()).strip()


def _missing_focus(old: str, new: str) -> dict[str, str]:
    kept = _focus_sections(new)
    return {key: section for key, section in _focus_sections(old).items() if key not in kept}


def _problems(old: str, new: str, truncated: bool) -> list[str]:
    problems = []
    if not new:
        problems.append("The notes are empty. Return the whole notes.")
    if truncated or _words(new) > WORD_LIMIT:
        problems.append(f"The notes must be {WORD_LIMIT} words or fewer; tighten them without dropping a heading.")
    for section in _missing_focus(old, new).values():
        heading = section.splitlines()[0].strip()
        problems.append(f"Keep the focus area heading {heading!r} and its section; never remove a focus area.")
    return problems


def _fold(items: list[dict]) -> dict:
    start = current_notes()
    notes = start["content"]
    digests = [_digest(item) for item in items]
    budget = _budget()
    while len(digests) > 1 and _estimate(_payload(notes, digests)) > budget:
        digests.pop()  # fold the oldest batch that fits; the rest wait for the next update
    included = [item["id"] for item in items[: len(digests)]]

    draft, model_used = llm.text_call("memory", _messages(MEMORY_SYSTEM, _payload(notes, digests)))
    draft = _clean(draft)
    problems = _problems(notes, draft, llm.call_state.truncated)
    if problems:
        repair = {"current_notes": notes, "draft": draft, "problems": problems}
        draft, model_used = llm.text_call(
            "memory",
            _messages(REPAIR_SYSTEM, repair)
            + [{"role": "user", "content": "Problems to fix: " + " ".join(problems)}],
        )
        draft = _clean(draft)
        if llm.call_state.truncated or not draft:
            raise _NotesProblem(
                f"The coach notes update was over {WORD_LIMIT} words or cut off after one repair. "
                "Your notes are unchanged."
            )
    for section in _missing_focus(notes, draft).values():
        draft = draft + "\n" + section  # still dropped after the repair: keep the old section as it was
    if _words(draft) > WORD_LIMIT:
        raise _NotesProblem(
            f"The coach notes update was over {WORD_LIMIT} words or cut off after one repair. "
            "Your notes are unchanged."
        )
    # A learner edit or restore made while the model ran wins: this result was built on older notes.
    return _save(draft, "memory", included, model_used, expect_current_id=start["id"])


def fold_in() -> dict | None:
    """Run the memory pass over unfolded attempts. None when there is nothing to fold or it failed;
    on failure call_state.error says why and the notes are untouched."""
    call_state.error = None
    items = unfolded_attempts()
    if not items:
        return None
    try:
        return _fold(items)
    except (models.ServiceUnavailable, _NotesProblem) as exc:
        call_state.error = str(exc)
        return None
