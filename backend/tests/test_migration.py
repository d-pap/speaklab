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
    # s3 is on its own topic, so the v5 thread merge leaves its attempts in place.
    for sid, topic, stage in (("s1", "hash-maps", "feedback"), ("s2", "hash-maps", "learn"), ("s3", "caching", "compare")):
        conn.execute(
            "INSERT INTO sessions(id,topic_id,created_at,duration,style,prompt_kind,stage) "
            "VALUES(?,?,?,?,?,?,?)",
            (sid, topic, "2026-10-05T14:30:00+00:00", 120, "plain", "explain", stage),
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
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 6
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


def test_fresh_database_is_v6_and_coach_notes_checks_source(data_dir):
    db.initialize()
    db.initialize()
    with db.connect() as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 6
        conn.execute("INSERT INTO coach_notes(created_at, content, source) VALUES('t','x','memory')")
        row = conn.execute("SELECT folded_attempt_ids FROM coach_notes").fetchone()
        assert row[0] == "[]"
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO coach_notes(created_at, content, source) VALUES('t','x','bogus')")


def test_newer_than_v6_refused(data_dir):
    db.initialize()
    conn = sqlite3.connect(data_dir / "speaklab.sqlite3")
    conn.execute("PRAGMA user_version=7")
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


# The host database's v4 shape: the redesign's columns plus the tables an earlier branch left behind.
HOST_V4_SCHEMA = """
CREATE TABLE sessions (
  id TEXT PRIMARY KEY, topic_id TEXT NOT NULL, created_at TEXT NOT NULL,
  duration INTEGER NOT NULL, style TEXT NOT NULL, prompt_kind TEXT NOT NULL,
  stage TEXT NOT NULL DEFAULT 'record1', completed_at TEXT, recall TEXT,
  review_due TEXT
, attempt2_after TEXT);
CREATE TABLE attempts (
  id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  number INTEGER NOT NULL CHECK(number IN (1,2)), created_at TEXT NOT NULL,
  audio_file TEXT NOT NULL, wav_file TEXT NOT NULL, mime TEXT NOT NULL, duration REAL NOT NULL,
  transcript TEXT, transcript_source TEXT, segments TEXT, acoustics TEXT, assessment TEXT,
  status TEXT NOT NULL DEFAULT 'pending', errors TEXT NOT NULL DEFAULT '{}', retranscribe INTEGER NOT NULL DEFAULT 0,
  transcription_version INTEGER NOT NULL DEFAULT 0, lines TEXT, tokens TEXT, analysis TEXT, learner_note TEXT,
  note_state TEXT NOT NULL DEFAULT 'pending', note_deadline TEXT, chat_summary TEXT,
  chat_summary_through INTEGER NOT NULL DEFAULT 0, chat_summary_model TEXT,
  UNIQUE(session_id, number)
);
CREATE TABLE messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  role TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL
, attempt_number INTEGER NOT NULL DEFAULT 1, kind TEXT NOT NULL DEFAULT 'chat', model TEXT);
CREATE TABLE reviews (
  topic_id TEXT PRIMARY KEY, interval_days INTEGER NOT NULL, repetitions INTEGER NOT NULL,
  due TEXT NOT NULL, last_session_id TEXT NOT NULL REFERENCES sessions(id)
);
CREATE INDEX attempts_session ON attempts(session_id);
CREATE TABLE analysis_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  attempt_id TEXT NOT NULL REFERENCES attempts(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL, snapshot TEXT NOT NULL
);
CREATE TABLE app_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE learning_sessions (
  session_id TEXT PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
  state TEXT NOT NULL
);
CREATE TABLE learning_turns (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  request_id TEXT NOT NULL, payload TEXT NOT NULL, result TEXT NOT NULL,
  created_at TEXT NOT NULL, UNIQUE(session_id, request_id)
);
CREATE TABLE coach_notes (
  id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, content TEXT NOT NULL,
  source TEXT NOT NULL CHECK(source IN ('memory','learner','restore')),
  folded_attempt_ids TEXT NOT NULL DEFAULT '[]'
, model TEXT);
"""


def make_v4(path):
    conn = sqlite3.connect(path / "speaklab.sqlite3")
    conn.executescript(HOST_V4_SCHEMA)
    conn.execute("PRAGMA user_version=4")
    conn.commit()
    return conn


def add_session(conn, sid, topic, created_at):
    conn.execute(
        "INSERT INTO sessions(id,topic_id,created_at,duration,style,prompt_kind,stage) VALUES(?,?,?,?,?,?,?)",
        (sid, topic, created_at, 120, "plain", "explain", "review1"),
    )


def add_attempt(conn, aid, sid, number, created_at):
    conn.execute(
        "INSERT INTO attempts(id,session_id,number,created_at,audio_file,wav_file,mime,duration,status,"
        "analysis,note_state) VALUES(?,?,?,?,?,?,'audio/wav',10,'ready','{}','done')",
        (aid, sid, number, created_at, f"{aid}.webm", f"{aid}.wav"),
    )


def add_message(conn, sid, number, content, kind="chat"):
    conn.execute(
        "INSERT INTO messages(session_id,role,content,created_at,attempt_number,kind) VALUES(?,?,?,?,?,?)",
        (sid, "user", content, "t", number, kind),
    )


def message_attempts():
    """Each message's content, mapped to the attempt id its (session, attempt_number) points at."""
    return {
        r["content"]: r["attempt_id"]
        for r in db.all_rows(
            "SELECT m.content, a.id AS attempt_id FROM messages m "
            "LEFT JOIN attempts a ON a.session_id=m.session_id AND a.number=m.attempt_number"
        )
    }


def snapshot(conn, table):
    return [tuple(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY 1")]


def with_new_columns_null(rows, before):
    """Rows as they were before the upgrade; the attempt columns added since are all NULL."""
    width = len(before[0])
    assert all(set(row[width:]) <= {None} for row in rows)
    return [row[:width] for row in rows]


def schema_sql(conn, name):
    return conn.execute("SELECT sql FROM sqlite_master WHERE name=?", (name,)).fetchone()[0]


def test_v4_database_upgrades_to_v5_and_drops_attempt_number_check(data_dir):
    conn = make_v4(data_dir)
    add_session(conn, "s1", "hash-maps", "2026-10-01T10:00:00+00:00")
    add_attempt(conn, "a1", "s1", 1, "2026-10-01T10:05:00+00:00")
    add_attempt(conn, "a2", "s1", 2, "2026-10-02T10:05:00+00:00")
    conn.commit()
    before_columns = [row[1] for row in conn.execute("PRAGMA table_info(attempts)")]
    conn.close()
    db.initialize()
    with db.connect() as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 6
        assert [row[1] for row in conn.execute("PRAGMA table_info(attempts)")][: len(before_columns)] == before_columns
        assert "CHECK" not in schema_sql(conn, "attempts")
        assert schema_sql(conn, "attempts_session") is not None
        add_attempt(conn, "a3", "s1", 3, "2026-10-03T10:05:00+00:00")
        # UNIQUE(session_id, number) still holds.
        with pytest.raises(sqlite3.IntegrityError):
            add_attempt(conn, "dup", "s1", 3, "2026-10-04T10:05:00+00:00")
    assert [r["id"] for r in db.all_rows("SELECT id FROM attempts ORDER BY number")] == ["a1", "a2", "a3"]


def test_recorded_sessions_of_one_topic_merge_into_earliest_thread(data_dir):
    conn = make_v4(data_dir)
    add_session(conn, "empty", "hash-maps", "2026-09-01T10:00:00+00:00")  # picked, never recorded
    add_session(conn, "thread", "hash-maps", "2026-10-01T10:00:00+00:00")
    add_session(conn, "later", "hash-maps", "2026-10-10T10:00:00+00:00")
    add_session(conn, "other", "caching", "2026-10-05T10:00:00+00:00")
    # Interleaved dates: the later session's attempt falls between the thread's two attempts.
    add_attempt(conn, "t1", "thread", 1, "2026-10-01T10:05:00+00:00")
    add_attempt(conn, "t2", "thread", 2, "2026-10-20T10:05:00+00:00")
    add_attempt(conn, "l1", "later", 1, "2026-10-10T10:05:00+00:00")
    add_attempt(conn, "l2", "later", 2, "2026-10-25T10:05:00+00:00")
    add_attempt(conn, "o1", "other", 1, "2026-10-05T10:05:00+00:00")
    for sid, number in (("thread", 1), ("thread", 2), ("later", 1), ("later", 2), ("other", 1)):
        add_message(conn, sid, number, f"chat {sid} {number}")
    add_message(conn, "later", 1, "review later 1", kind="review")
    conn.execute("INSERT INTO analysis_history(attempt_id,created_at,snapshot) VALUES('l1','t','{}')")
    conn.execute("INSERT INTO analysis_history(attempt_id,created_at,snapshot) VALUES('t2','t','{}')")
    conn.commit()
    empty_before = snapshot(conn, "sessions")[0]
    conn.close()
    before = message_attempts()
    assert before["chat later 1"] == "l1"

    db.initialize()

    thread = db.all_rows("SELECT id, number FROM attempts WHERE session_id='thread' ORDER BY number")
    assert thread == [
        {"id": "t1", "number": 1},
        {"id": "l1", "number": 2},
        {"id": "t2", "number": 3},
        {"id": "l2", "number": 4},
    ]
    # Every message still points at the same attempt, now inside the thread.
    assert message_attempts() == before
    assert db.one("SELECT COUNT(*) AS n FROM messages WHERE session_id='later'")["n"] == 0
    history = {r["attempt_id"]: r["session_id"] for r in db.all_rows(
        "SELECT h.attempt_id, a.session_id FROM analysis_history h JOIN attempts a ON a.id=h.attempt_id"
    )}
    assert history == {"l1": "thread", "t2": "thread"}
    # The merged-from session row stays, without attempts. Other topics and empty sessions are untouched.
    assert db.one("SELECT id FROM sessions WHERE id='later'") is not None
    assert db.one("SELECT COUNT(*) AS n FROM attempts WHERE session_id='later'")["n"] == 0
    assert db.one("SELECT session_id, number FROM attempts WHERE id='o1'") == {"session_id": "other", "number": 1}
    with db.connect() as conn:
        assert tuple(conn.execute("SELECT * FROM sessions WHERE id='empty'").fetchone()) == empty_before


def test_host_shaped_v4_database_upgrades(data_dir):
    conn = make_v4(data_dir)
    add_session(conn, "s1", "auth", "2026-10-27T12:22:29+00:00")
    add_session(conn, "s2", "auth", "2026-11-04T00:05:21+00:00")  # never recorded
    add_session(conn, "s3", "prompt-injection", "2026-11-14T14:29:52+00:00")
    add_attempt(conn, "a1", "s1", 1, "2026-10-27T12:24:43+00:00")
    add_attempt(conn, "a2", "s1", 2, "2026-10-27T13:28:04+00:00")
    add_attempt(conn, "a3", "s3", 1, "2026-11-14T14:35:31+00:00")
    add_message(conn, "s1", 1, "hello")
    conn.execute("INSERT INTO analysis_history(attempt_id,created_at,snapshot) VALUES('a1','t','{}')")
    conn.execute("INSERT INTO learning_sessions(session_id,state) VALUES('s3','{\"step\":2}')")
    conn.execute(
        "INSERT INTO learning_turns(session_id,request_id,payload,result,created_at) VALUES('s3','r1','{}','{}','t')"
    )
    conn.execute("INSERT INTO reviews VALUES('auth',3,1,'2026-10-30','s1')")
    conn.commit()
    attempts_before = snapshot(conn, "attempts")
    learning_before = {t: (schema_sql(conn, t), snapshot(conn, t)) for t in ("learning_sessions", "learning_turns")}
    others_before = {t: snapshot(conn, t) for t in ("sessions", "messages", "analysis_history", "reviews")}
    conn.close()

    db.initialize()

    with db.connect() as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 6
        assert with_new_columns_null(snapshot(conn, "attempts"), attempts_before) == attempts_before
        assert {t: (schema_sql(conn, t), snapshot(conn, t)) for t in learning_before} == learning_before
        for table, before in others_before.items():
            after = snapshot(conn, table)
            assert (with_new_columns_null(after, before) if table == "messages" else after) == before
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_v5_initialize_is_idempotent(data_dir):
    conn = make_v4(data_dir)
    add_session(conn, "s1", "hash-maps", "2026-10-01T10:00:00+00:00")
    add_attempt(conn, "a1", "s1", 1, "2026-10-01T10:05:00+00:00")
    conn.commit()
    conn.close()
    db.initialize()
    # A second recorded session on the same topic after v5: only the upgrade merges, so it stays put.
    with db.connect() as conn:
        add_session(conn, "s2", "hash-maps", "2026-10-02T10:00:00+00:00")
        add_attempt(conn, "b1", "s2", 1, "2026-10-02T10:05:00+00:00")
        add_attempt(conn, "a3", "s1", 3, "2026-10-03T10:05:00+00:00")
        conn.execute("INSERT INTO analysis_history(attempt_id,created_at,snapshot) VALUES('a1','t','{}')")
        before = snapshot(conn, "attempts")
    db.initialize()
    with db.connect() as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 6
        assert snapshot(conn, "attempts") == before
        assert conn.execute("SELECT COUNT(*) FROM analysis_history").fetchone()[0] == 1
        assert schema_sql(conn, "attempts_session") is not None


def test_failed_v5_upgrade_rolls_back_to_v4_and_retries(data_dir, monkeypatch):
    conn = make_v4(data_dir)
    add_session(conn, "thread", "hash-maps", "2026-10-01T10:00:00+00:00")
    add_session(conn, "later", "hash-maps", "2026-10-10T10:00:00+00:00")
    add_attempt(conn, "t1", "thread", 1, "2026-10-01T10:05:00+00:00")
    add_attempt(conn, "l1", "later", 1, "2026-10-10T10:05:00+00:00")
    add_message(conn, "later", 1, "chat later 1")
    conn.execute("INSERT INTO analysis_history(attempt_id,created_at,snapshot) VALUES('l1','t','{}')")
    conn.commit()
    before = {t: snapshot(conn, t) for t in ("attempts", "messages", "analysis_history")}
    conn.close()

    def broken(_db):
        raise RuntimeError("merge failed")

    with monkeypatch.context() as patch:
        patch.setattr(db, "_merge_topic_threads", broken)
        with pytest.raises(RuntimeError):
            db.initialize()
    with db.connect() as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 4
        assert "CHECK" in schema_sql(conn, "attempts")
        assert conn.execute("SELECT name FROM sqlite_master WHERE name='attempts_v5'").fetchone() is None
        after = {t: snapshot(conn, t) for t in before}
        after["attempts"] = with_new_columns_null(after["attempts"], before["attempts"])
        assert after == before

    db.initialize()
    with db.connect() as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 6
    assert db.all_rows("SELECT id, session_id, number FROM attempts ORDER BY number") == [
        {"id": "t1", "session_id": "thread", "number": 1},
        {"id": "l1", "session_id": "thread", "number": 2},
    ]
    assert message_attempts() == {"chat later 1": "l1"}


def test_unrecognised_attempt_number_check_stops_the_upgrade(data_dir):
    conn = make_v4(data_dir)
    sql = schema_sql(conn, "attempts").replace("CHECK(number IN (1,2))", 'CHECK ("number" BETWEEN 1 AND 2)')
    conn.execute("PRAGMA writable_schema=ON")
    conn.execute("UPDATE sqlite_master SET sql=? WHERE type='table' AND name='attempts'", (sql,))
    conn.execute("PRAGMA writable_schema=OFF")
    conn.commit()
    conn.close()
    with pytest.raises(RuntimeError, match="attempt numbers"):
        db.initialize()
    with sqlite3.connect(data_dir / "speaklab.sqlite3") as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 4
