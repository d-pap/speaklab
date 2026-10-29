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


def initialize():
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    (settings.data_dir / "recordings").mkdir(exist_ok=True)
    with connect() as db:
        db.execute("PRAGMA journal_mode=WAL")
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if version > 3:
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
        columns = {row[1] for row in db.execute("PRAGMA table_info(attempts)")}
        for column in ("retranscribe", "transcription_version"):
            if column not in columns:
                db.execute(f"ALTER TABLE attempts ADD COLUMN {column} INTEGER NOT NULL DEFAULT 0")
        db.execute("PRAGMA user_version=3")
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
    for key in ("segments", "acoustics", "assessment", "errors"):
        result[key] = json.loads(result[key]) if result[key] else None
    result["audio_url"] = f"/api/attempts/{attempt['id']}/audio"
    return result
