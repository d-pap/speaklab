import json
import sqlite3

import pytest

from app import db
from app.config import settings

V3_SCHEMA = """
CREATE TABLE sessions (
  id TEXT PRIMARY KEY, topic_id TEXT NOT NULL, created_at TEXT NOT NULL,
  duration INTEGER NOT NULL, style TEXT NOT NULL, prompt_kind TEXT NOT NULL,
  stage TEXT NOT NULL DEFAULT 'record1', completed_at TEXT, recall TEXT,
  review_due TEXT
);
CREATE TABLE attempts (
  id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  number INTEGER NOT NULL CHECK(number IN (1,2)), created_at TEXT NOT NULL,
  audio_file TEXT NOT NULL, wav_file TEXT NOT NULL, mime TEXT NOT NULL, duration REAL NOT NULL,
  transcript TEXT, transcript_source TEXT, segments TEXT, acoustics TEXT, assessment TEXT,
  status TEXT NOT NULL DEFAULT 'pending', errors TEXT NOT NULL DEFAULT '{}',
  retranscribe INTEGER NOT NULL DEFAULT 0, transcription_version INTEGER NOT NULL DEFAULT 0,
  UNIQUE(session_id, number)
);
CREATE TABLE messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  role TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE reviews (
  topic_id TEXT PRIMARY KEY, interval_days INTEGER NOT NULL, repetitions INTEGER NOT NULL,
  due TEXT NOT NULL, last_session_id TEXT NOT NULL REFERENCES sessions(id)
);
CREATE TABLE analysis_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  attempt_id TEXT NOT NULL REFERENCES attempts(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL, snapshot TEXT NOT NULL
);
CREATE TABLE app_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def columns(table):
    with db.connect() as conn:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def make_v3(tmp_path):
    conn = sqlite3.connect(tmp_path / "speaklab.sqlite3")
    conn.executescript(V3_SCHEMA)
    for sid, stage in (("s1", "feedback"), ("s2", "learn"), ("s3", "compare")):
        conn.execute(
            "INSERT INTO sessions(id,topic_id,created_at,duration,style,prompt_kind,stage) "
            "VALUES(?,?,?,?,?,?,?)",
            (sid, "hash-maps", "2026-10-05T14:30:00+00:00", 120, "plain", "explain", stage),
        )
    conn.execute(
        "INSERT INTO attempts(id,session_id,number,created_at,audio_file,wav_file,mime,duration,assessment,status) "
        "VALUES('a1','s1',1,'2026-10-05T14:30:00+00:00','a','w','audio/wav',10,?, 'complete')",
        (json.dumps({"summary": "old"}),),
    )
    conn.execute(
        "INSERT INTO attempts(id,session_id,number,created_at,audio_file,wav_file,mime,duration,status) "
        "VALUES('a2','s2',1,'2026-10-05T14:30:00+00:00','a','w','audio/wav',10,'complete')"
    )
    conn.execute("INSERT INTO messages(session_id,role,content,created_at) VALUES('s1','user','hi','t')")
    conn.execute("PRAGMA user_version=3")
    conn.commit()
    conn.close()


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    return tmp_path


def test_v3_database_migrates_stages_and_columns(data_dir):
    make_v3(data_dir)
    db.initialize()
    stages = {r["id"]: r["stage"] for r in db.all_rows("SELECT id, stage FROM sessions")}
    assert stages == {"s1": "review1", "s2": "review1", "s3": "review2"}
    with db.connect() as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 4
    assert {
        "lines", "tokens", "analysis", "learner_note", "note_state",
        "note_deadline", "chat_summary", "chat_summary_through", "chat_summary_model",
    } <= columns("attempts")
    assert {"attempt_number", "kind"} <= columns("messages")
    assert "attempt2_after" in columns("sessions")
    assert "coach_notes" in {r["name"] for r in db.all_rows("SELECT name FROM sqlite_master WHERE type='table'")}
    assert db.one("SELECT note_state FROM attempts WHERE id='a1'")["note_state"] == "legacy"
    # No legacy assessment and no new analysis: there is no review to wait a note for.
    other = db.one("SELECT note_state, chat_summary_through FROM attempts WHERE id='a2'")
    assert other == {"note_state": "skipped", "chat_summary_through": 0}
    message = db.one("SELECT attempt_number, kind FROM messages")
    assert message == {"attempt_number": 1, "kind": "chat"}
    after = {r["id"]: r["attempt2_after"] for r in db.all_rows("SELECT id, attempt2_after FROM sessions")}
    assert after["s1"] == after["s2"] == "2026-10-05"
    assert after["s3"] is None


def test_pre_redesign_database_already_marked_v4_is_still_upgraded(data_dir):
    # An earlier branch marked old-format databases user_version 4 and added its own tables.
    make_v3(data_dir)
    conn = sqlite3.connect(data_dir / "speaklab.sqlite3")
    conn.execute("CREATE TABLE learning_sessions (id TEXT PRIMARY KEY, data TEXT)")
    conn.execute("INSERT INTO learning_sessions VALUES ('l1', '{}')")
    conn.execute("PRAGMA user_version=4")
    conn.commit()
    conn.close()
    db.initialize()
    stages = {r["id"]: r["stage"] for r in db.all_rows("SELECT id, stage FROM sessions")}
    assert stages == {"s1": "review1", "s2": "review1", "s3": "review2"}
    assert db.one("SELECT note_state FROM attempts WHERE id='a1'")["note_state"] == "legacy"
    assert db.one("SELECT note_state FROM attempts WHERE id='a2'")["note_state"] == "skipped"
    after = {r["id"]: r["attempt2_after"] for r in db.all_rows("SELECT id, attempt2_after FROM sessions")}
    assert after["s1"] == after["s2"] == "2026-10-05"
    # Unknown tables from the earlier branch are left alone.
    assert db.one("SELECT data FROM learning_sessions WHERE id='l1'")["data"] == "{}"


def test_migration_is_idempotent(data_dir):
    make_v3(data_dir)
    db.initialize()
    db.execute("UPDATE sessions SET stage='review1', attempt2_after=NULL WHERE id='s3'")
    db.initialize()
    stages = {r["id"]: r["stage"] for r in db.all_rows("SELECT id, stage FROM sessions")}
    assert stages == {"s1": "review1", "s2": "review1", "s3": "review1"}
    # A review1 session on an already-migrated database keeps its own attempt2_after.
    assert db.one("SELECT attempt2_after FROM sessions WHERE id='s3'")["attempt2_after"] is None


def test_fresh_database_is_v4_and_coach_notes_checks_source(data_dir):
    db.initialize()
    db.initialize()
    with db.connect() as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 4
        conn.execute("INSERT INTO coach_notes(created_at, content, source) VALUES('t','x','memory')")
        row = conn.execute("SELECT folded_attempt_ids FROM coach_notes").fetchone()
        assert row[0] == "[]"
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO coach_notes(created_at, content, source) VALUES('t','x','bogus')")


def test_newer_database_refused(data_dir):
    db.initialize()
    conn = sqlite3.connect(data_dir / "speaklab.sqlite3")
    conn.execute("PRAGMA user_version=5")
    conn.commit()
    conn.close()
    with pytest.raises(RuntimeError):
        db.initialize()


def test_note_state_backfill_runs_only_on_the_upgrade(data_dir):
    make_v3(data_dir)
    db.initialize()
    # A new attempt on the migrated database waits for its note as usual.
    db.execute(
        "INSERT INTO attempts(id,session_id,number,created_at,audio_file,wav_file,mime,duration) "
        "VALUES('new','s3',1,'2026-11-16T00:00:00+00:00','a','w','audio/wav',10)"
    )
    db.initialize()
    assert db.one("SELECT note_state FROM attempts WHERE id='new'")["note_state"] == "pending"
    assert db.one("SELECT note_state FROM attempts WHERE id='a2'")["note_state"] == "skipped"


def _add_attempts(path, session_id, attempt2_assessment):
    conn = sqlite3.connect(path / "speaklab.sqlite3")
    concepts = {"concepts": [{"status": "correct"}, {"status": "correct"}, {"status": "missing"}]}
    for number, assessment in ((1, concepts), (2, attempt2_assessment)):
        conn.execute(
            "INSERT INTO attempts(id,session_id,number,created_at,audio_file,wav_file,mime,duration,assessment,status) "
            "VALUES(?,?,?,'2026-10-05T14:30:00+00:00','a','w','audio/wav',10,?,'complete')",
            (f"{session_id}-{number}", session_id, number, json.dumps(assessment) if assessment else None),
        )
    conn.commit()
    conn.close()


def test_open_compare_session_with_legacy_attempt2_completes_at_startup(data_dir):
    from fastapi.testclient import TestClient

    from app import main

    make_v3(data_dir)
    _add_attempts(data_dir, "s3", {"concepts": [{"status": "correct"}, {"status": "missing"}]})
    with TestClient(main.app):
        pass
    session = db.one("SELECT * FROM sessions WHERE id='s3'")
    assert session["stage"] == "review2" and session["completed_at"]
    assert session["recall"] == "hard"  # 1 of 2 concepts from the legacy assessment
    review = db.one("SELECT * FROM reviews WHERE topic_id='hash-maps'")
    assert review["last_session_id"] == "s3" and review["due"] == session["review_due"]


def test_startup_leaves_review2_sessions_with_a_new_analysis_alone(data_dir):
    make_v3(data_dir)
    _add_attempts(data_dir, "s3", {"concepts": [{"status": "correct"}]})
    db.initialize()
    # Re-reviewed by the new pipeline, which completes the session itself when its review is written.
    db.execute("UPDATE attempts SET analysis='{}' WHERE id='s3-2'")
    from app import pipeline

    pipeline.complete_legacy_sessions()
    assert db.one("SELECT completed_at FROM sessions WHERE id='s3'")["completed_at"] is None
