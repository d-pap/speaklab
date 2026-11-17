import json
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
        if version > 4:
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
          number INTEGER NOT NULL CHECK(number IN (1,2)), created_at TEXT NOT NULL,
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
        if version < 4 and has_assessment:
            db.execute("UPDATE attempts SET note_state='legacy' WHERE assessment IS NOT NULL")
            # No legacy review and no new one either: no note box to wait on.
            db.execute("UPDATE attempts SET note_state='skipped' WHERE assessment IS NULL")
        # Sessions left in the old feedback/learn stages keep attempt 2 open: date of creation.
        db.execute(
            "UPDATE sessions SET attempt2_after=substr(created_at,1,10) "
            "WHERE attempt2_after IS NULL AND (stage IN ('feedback','learn') OR (stage='review1' AND ?<4))",
            (version,),
        )
        db.execute("UPDATE sessions SET stage='review1' WHERE stage IN ('feedback','learn')")
        db.execute("UPDATE sessions SET stage='review2' WHERE stage='compare'")
        db.execute("PRAGMA user_version=4")
        db.execute(
            "UPDATE attempts SET status='interrupted', errors=? WHERE status IN ('pending','processing')",
            (
                json.dumps(
                    {"processing": "Processing was interrupted. Your recording is saved; retry analysis."}
                ),
            ),
        )


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
