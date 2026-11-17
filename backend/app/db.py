import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from .config import settings


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def connect():
    conn = sqlite3.connect(settings.data_dir / "speaklab.sqlite3", timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _add_columns(db, table: str, wanted: dict[str, str]):
    existing = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
    for column, definition in wanted.items():
        if column not in existing:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def initialize():
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    (settings.data_dir / "recordings").mkdir(exist_ok=True)
    with connect() as db:
        db.execute("PRAGMA journal_mode=WAL")
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if version > 6:
            raise RuntimeError("This database was created by a newer SpeakLab version.")
        db.executescript("""
        CREATE TABLE IF NOT EXISTS sessions (
          id TEXT PRIMARY KEY, topic_id TEXT NOT NULL, created_at TEXT NOT NULL,
          duration INTEGER NOT NULL, style TEXT NOT NULL, prompt_kind TEXT NOT NULL,
          stage TEXT NOT NULL DEFAULT 'record1', completed_at TEXT, recall TEXT,
          review_due TEXT
        );
        CREATE TABLE IF NOT EXISTS attempts (
          id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
          number INTEGER NOT NULL, created_at TEXT NOT NULL,
          audio_file TEXT NOT NULL, wav_file TEXT NOT NULL, mime TEXT NOT NULL, duration REAL NOT NULL,
          transcript TEXT, transcript_source TEXT, segments TEXT, acoustics TEXT, assessment TEXT,
          status TEXT NOT NULL DEFAULT 'pending', errors TEXT NOT NULL DEFAULT '{}',
          UNIQUE(session_id, number)
        );
        CREATE TABLE IF NOT EXISTS messages (
          id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
          role TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS reviews (
          topic_id TEXT PRIMARY KEY, interval_days INTEGER NOT NULL, repetitions INTEGER NOT NULL,
          due TEXT NOT NULL, last_session_id TEXT NOT NULL REFERENCES sessions(id)
        );
        CREATE INDEX IF NOT EXISTS attempts_session ON attempts(session_id);
        CREATE TABLE IF NOT EXISTS analysis_history (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          attempt_id TEXT NOT NULL REFERENCES attempts(id) ON DELETE CASCADE,
          created_at TEXT NOT NULL, snapshot TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS app_settings (
          key TEXT PRIMARY KEY, value TEXT NOT NULL
        );
        """)
        db.execute(
            """CREATE TABLE IF NOT EXISTS coach_notes (
              id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, content TEXT NOT NULL,
              source TEXT NOT NULL CHECK(source IN ('memory','learner','restore')),
              folded_attempt_ids TEXT NOT NULL DEFAULT '[]'
            )"""
        )
        # A database is upgrading to the coach pipeline when it lacks the note_state column.
        # Some pre-redesign databases were already marked user_version 4 by an earlier
        # branch, so the version number alone cannot decide whether to backfill.
        upgrading = version < 4 or not any(
            row[1] == "note_state" for row in db.execute("PRAGMA table_info(attempts)")
        )
        _add_columns(
            db,
            "attempts",
            {
                "retranscribe": "INTEGER NOT NULL DEFAULT 0",
                "transcription_version": "INTEGER NOT NULL DEFAULT 0",
                "lines": "TEXT",
                "tokens": "TEXT",
                "analysis": "TEXT",
                "learner_note": "TEXT",
                "note_state": "TEXT NOT NULL DEFAULT 'pending'",
                "note_deadline": "TEXT",
                "chat_summary": "TEXT",
                "chat_summary_through": "INTEGER NOT NULL DEFAULT 0",
                "chat_summary_model": "TEXT",  # the chat pass's model that wrote the running summary
                # Topic threads: each attempt's own question type, style and target length in
                # seconds (`duration` is the recorded length). NULL on older attempts, which use
                # their session's values.
                "prompt_kind": "TEXT",
                "style": "TEXT",
                "target_duration": "INTEGER",
                # When this attempt's review rescheduled the topic's spaced review; once per attempt.
                "scheduled_at": "TEXT",
            },
        )
        _add_columns(
            db,
            "messages",
            # model: the chat pass's model for coach replies; NULL for learner messages and reviews.
            {"attempt_number": "INTEGER NOT NULL DEFAULT 1", "kind": "TEXT NOT NULL DEFAULT 'chat'", "model": "TEXT"},
        )
        _add_columns(db, "sessions", {"attempt2_after": "TEXT"})
        _add_columns(db, "coach_notes", {"model": "TEXT"})  # the memory pass's model; NULL for edits
        has_assessment = any(row[1] == "assessment" for row in db.execute("PRAGMA table_info(attempts)"))
        if upgrading and has_assessment:
            db.execute("UPDATE attempts SET note_state='legacy' WHERE assessment IS NOT NULL")
            # No legacy review and no new one either: no note box to wait on.
            db.execute("UPDATE attempts SET note_state='skipped' WHERE assessment IS NULL")
        # Sessions left in the old feedback/learn stages keep attempt 2 open: date of creation.
        db.execute(
            "UPDATE sessions SET attempt2_after=substr(created_at,1,10) "
            "WHERE attempt2_after IS NULL AND (stage IN ('feedback','learn') OR (stage='review1' AND ?))",
            (int(upgrading),),
        )
        db.execute("UPDATE sessions SET stage='review1' WHERE stage IN ('feedback','learn')")
        db.execute("UPDATE sessions SET stage='review2' WHERE stage='compare'")
        # Mark v4 in the same transaction as the backfill above, so a failed v5 step retries from v4.
        db.execute(f"PRAGMA user_version={max(version, 4)}")
        _upgrade_to_v5(db, merge=version < 5)
        _add_columns(db, "messages", {"generation_context": "TEXT"})
        db.execute("""CREATE TABLE IF NOT EXISTS response_feedback (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          message_id INTEGER UNIQUE REFERENCES messages(id) ON DELETE SET NULL,
          rating INTEGER NOT NULL CHECK(rating IN (-1,1)), reason TEXT,
          comment TEXT NOT NULL DEFAULT '', preferred_response TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL, snapshot TEXT NOT NULL
        )""")
        db.execute("PRAGMA user_version=6")
        db.execute(
            "UPDATE attempts SET status='interrupted', errors=? WHERE status IN ('pending','processing')",
            (
                json.dumps(
                    {"processing": "Processing was interrupted. Your recording is saved; retry analysis."}
                ),
            ),
        )


_ATTEMPT_NUMBER_CHECK = re.compile(r"\s*CHECK\s*\(\s*number\s+IN\s*\(\s*1\s*,\s*2\s*\)\s*\)", re.IGNORECASE)
_ANY_NUMBER_CHECK = re.compile(r"CHECK\s*\([^)]*\bnumber\b", re.IGNORECASE)


def _upgrade_to_v5(db, merge: bool):
    """Allow any attempt number and fold each topic's recorded sessions into one thread.

    Runs in its own transaction with foreign keys off: dropping the old attempts table with
    them on would cascade-delete analysis_history.
    """
    db.commit()
    db.execute("PRAGMA foreign_keys=OFF")
    if db.execute("PRAGMA foreign_keys").fetchone()[0] != 0:
        raise RuntimeError("Could not disable foreign keys for the schema upgrade.")
    try:
        db.execute("BEGIN")
        changed = _drop_attempt_number_check(db)
        if merge:
            changed = _merge_topic_threads(db) or changed
        # Only checked after a real change: very old shapes have an attempts table that
        # analysis_history's foreign key cannot even resolve against.
        for table in ("attempts", "messages", "analysis_history") if changed else ():
            if db.execute(f"PRAGMA foreign_key_check({table})").fetchall():
                raise RuntimeError(f"Schema upgrade left broken references in {table}.")
        attempts_sql = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='attempts'").fetchone()
        if attempts_sql and _ANY_NUMBER_CHECK.search(attempts_sql[0]):
            # A CHECK spelled in a way the rebuild didn't recognise: stay below v5 rather than
            # mark a database that still refuses attempt 3.
            raise RuntimeError("The attempts table still limits attempt numbers; the upgrade was not applied.")
        db.execute("PRAGMA user_version=5")
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.execute("PRAGMA foreign_keys=ON")


def _drop_attempt_number_check(db) -> bool:
    """Rebuild attempts from its own stored DDL minus the attempt-number CHECK, keeping every column."""
    sql = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='attempts'").fetchone()[0]
    new_sql, found = _ATTEMPT_NUMBER_CHECK.subn("", sql)
    if not found:
        return False
    new_sql, renamed = re.subn(r"^\s*CREATE\s+TABLE\s+(\"?)attempts\1", "CREATE TABLE attempts_v5", new_sql, flags=re.I)
    if renamed != 1:
        raise RuntimeError("Unexpected attempts table definition.")
    columns = ", ".join(f'"{row[1]}"' for row in db.execute("PRAGMA table_info(attempts)"))
    db.execute("DROP TABLE IF EXISTS attempts_v5")
    db.execute(new_sql)
    db.execute(f"INSERT INTO attempts_v5({columns}) SELECT {columns} FROM attempts")
    db.execute("DROP TABLE attempts")
    db.execute("ALTER TABLE attempts_v5 RENAME TO attempts")
    db.execute("CREATE INDEX IF NOT EXISTS attempts_session ON attempts(session_id)")
    return True


def _merge_topic_threads(db) -> bool:
    """Per topic, move every recorded session's attempts into the earliest recorded session.

    Attempts keep their ids (so analysis_history follows them) and are renumbered 1..n by
    created_at. Messages move with the attempt they belong to. Sessions without attempts,
    and the emptied merged-from session rows, are left in place.
    """
    attempt_columns = {row[1] for row in db.execute("PRAGMA table_info(attempts)")}
    if not {"number", "created_at"} <= attempt_columns:
        return False  # pre-v2 shapes without numbered attempts have nothing to merge
    recorded = db.execute(
        "SELECT id, topic_id FROM sessions s WHERE EXISTS (SELECT 1 FROM attempts a WHERE a.session_id=s.id) "
        "ORDER BY topic_id, created_at, id"
    ).fetchall()
    by_topic: dict[str, list[str]] = {}
    for row in recorded:
        by_topic.setdefault(row["topic_id"], []).append(row["id"])
    merged = False
    has_messages = "attempt_number" in {row[1] for row in db.execute("PRAGMA table_info(messages)")}
    for session_ids in by_topic.values():
        if len(session_ids) < 2:
            continue
        merged = True
        thread = session_ids[0]
        rank = {sid: i for i, sid in enumerate(session_ids)}
        marks = ",".join("?" * len(session_ids))
        attempts = db.execute(
            f"SELECT id, session_id, number, created_at FROM attempts WHERE session_id IN ({marks})", session_ids
        ).fetchall()
        ordered = sorted(attempts, key=lambda a: (a["created_at"], rank[a["session_id"]], a["number"]))
        renumber = {(a["session_id"], a["number"]): n for n, a in enumerate(ordered, start=1)}
        messages = (
            db.execute(
                f"SELECT id, session_id, attempt_number FROM messages WHERE session_id IN ({marks})", session_ids
            ).fetchall()
            if has_messages
            else []
        )
        # Negative numbers first, so UNIQUE(session_id, number) never sees a transient clash.
        for a in ordered:
            db.execute(
                "UPDATE attempts SET session_id=?, number=? WHERE id=?",
                (thread, -renumber[(a["session_id"], a["number"])], a["id"]),
            )
        db.execute("UPDATE attempts SET number=-number WHERE session_id=? AND number<0", (thread,))
        for m in messages:
            new_number = renumber.get((m["session_id"], m["attempt_number"]))
            if new_number is not None:
                db.execute(
                    "UPDATE messages SET session_id=?, attempt_number=? WHERE id=?", (thread, new_number, m["id"])
                )
    return merged


def one(sql: str, args: tuple = ()) -> dict | None:
    with connect() as db:
        row = db.execute(sql, args).fetchone()
        return dict(row) if row else None


def all_rows(sql: str, args: tuple = ()) -> list[dict]:
    with connect() as db:
        return [dict(row) for row in db.execute(sql, args).fetchall()]


def execute(sql: str, args: tuple = ()):
    with connect() as db:
        db.execute(sql, args)


def attempt_public(attempt: dict) -> dict:
    result = {k: v for k, v in attempt.items() if k not in {"audio_file", "wav_file"}}
    for key in ("segments", "acoustics", "assessment", "errors", "lines", "tokens", "analysis"):
        result[key] = json.loads(result[key]) if result[key] else None
    result["audio_url"] = f"/api/attempts/{attempt['id']}/audio"
    return result
