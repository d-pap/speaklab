import json
import threading
import time
from datetime import date, datetime, timedelta, timezone

import httpx
from conftest import MINIMAL_REVIEW, TRANSCRIPT, create, open_attempt2, upload

from app import db, models, pipeline, progress

# The real hand-off, captured before the client fixture swaps in synchronous doubles.
REAL_TIMER = threading.Timer
REAL_SUBMIT_WRITER = pipeline.submit_writer


class ImmediateTimer:
    def __init__(self, interval, function, args=None, kwargs=None):
        self.interval, self.function, self.args = interval, function, args or ()
        self.daemon = False

    def start(self):
        self.function(*self.args)


def attempt_row(attempt_id):
    return db.attempt_public(db.one("SELECT * FROM attempts WHERE id=?", (attempt_id,)))


def review_messages(session_id):
    return db.all_rows("SELECT * FROM messages WHERE session_id=? AND kind='review'", (session_id,))


def statuses(attempt):
    return {name: item["status"] for name, item in attempt["analysis"]["passes"].items()}


def test_pipeline_runs_phase1_then_waits_for_note(client, wav_bytes, fake_llm):
    session = create(client)
    attempt = upload(client, session, wav_bytes)
    assert attempt["status"] == "ready"
    assert attempt["note_state"] == "pending"
    assert attempt["lines"][0]["id"] == "L1" and attempt["tokens"]
    analysis = attempt["analysis"]
    assert analysis["stats"]["duration"] == attempt["duration"]
    assert statuses(attempt) == {
        "memory": "done",
        "technical": "done",
        "communication": "done",
        "writer": "waiting",
    }
    assert analysis["passes"]["technical"]["model"] and analysis["passes"]["communication"]["model"]
    assert analysis["technical"]["concepts"] and analysis["communication"]["sections"]
    assert analysis["timing"][0]["label"] == "Whole answer"
    assert analysis["review"] is None
    assert fake_llm.requests_for("writer") == [] and fake_llm.requests_for("memory") == []
    deadline = datetime.fromisoformat(db.one("SELECT note_deadline FROM attempts WHERE id=?", (attempt["id"],))["note_deadline"])
    assert timedelta(seconds=290) < deadline - datetime.now(timezone.utc) <= timedelta(seconds=300)
    [timer] = client.note_timers
    assert 290 < timer.interval <= 300 and timer.daemon and timer.args == (attempt["id"],)
    assert review_messages(session["id"]) == []


def test_note_submit_runs_writer_and_creates_review_message(client, wav_bytes, fake_llm):
    session = create(client)
    attempt = upload(client, session, wav_bytes)
    assert client.post(f"/api/attempts/{attempt['id']}/note", json={"text": "x" * 2001}).status_code == 422
    response = client.post(f"/api/attempts/{attempt['id']}/note", json={"text": "  I rushed the ending.  "})
    assert response.status_code == 200, response.text
    assert client.post(f"/api/attempts/{attempt['id']}/note", json={"skip": True}).status_code == 409
    detail = client.get(f"/api/sessions/{session['id']}").json()
    stored = detail["attempts"][0]
    assert stored["note_state"] == "submitted" and stored["learner_note"] == "I rushed the ending."
    assert stored["status"] == "ready"
    assert statuses(stored)["writer"] == "done"
    assert stored["analysis"]["passes"]["writer"]["model"]
    assert len(stored["analysis"]["review"]["scores"]) == 7
    structure, message = fake_llm.requests_for("writer")
    assert structure["payload"]["learner_note"] == message["payload"]["learner_note"] == "I rushed the ending."
    [review] = [m for m in detail["messages"] if m["kind"] == "review"]
    assert review["attempt_number"] == 1 and review["role"] == "assistant"
    assert review["content"] == MINIMAL_REVIEW
    ref = next(p for p in review["parts"] if p["type"] == "ref")
    assert ref["line_id"] == "L1" and ref["start"] == 0
    assert pipeline.after_review_written(attempt["id"]) is None
    sent = json.dumps([r["body"] for r in fake_llm.requests])
    assert "pitch_track" not in sent and "loudness_track" not in sent  # no dense plot arrays in prompts


def test_note_skip_before_phase1_finishes_is_picked_up_by_phase1(client, wav_bytes, monkeypatch, fake_llm):
    monkeypatch.setattr(pipeline, "submit", lambda _: None)
    session = create(client)
    attempt = upload(client, session, wav_bytes)
    assert client.post(f"/api/attempts/{attempt['id']}/note", json={"skip": True}).status_code == 200
    assert fake_llm.requests_for("writer") == []
    pipeline.process(attempt["id"])
    assert attempt_row(attempt["id"])["note_state"] == "skipped"
    assert len(review_messages(session["id"])) == 1
    assert client.note_timers == []


def test_writer_phase_starts_after_note_timeout(client, wav_bytes, monkeypatch):
    monkeypatch.setattr(pipeline, "NOTE_TIMEOUT_SECONDS", 0)
    monkeypatch.setattr(threading, "Timer", ImmediateTimer)
    session = create(client)
    attempt = upload(client, session, wav_bytes)
    stored = attempt_row(attempt["id"])
    assert stored["note_state"] == "skipped"
    assert statuses(stored)["writer"] == "done"
    assert stored["status"] == "ready"
    assert len(review_messages(session["id"])) == 1
    pipeline.auto_skip(attempt["id"])  # a late timer changes nothing
    assert len(review_messages(session["id"])) == 1


def test_pipeline_keeps_earlier_passes_when_later_pass_fails(client, wav_bytes, fake_llm):
    fake_llm.queue("communication", httpx.ConnectError("offline"))
    session = create(client)
    attempt = upload(client, session, wav_bytes)
    assert attempt["status"] == "partial"
    assert attempt["transcript"] == TRANSCRIPT and attempt["lines"]
    assert statuses(attempt) == {
        "memory": "done",
        "technical": "done",
        "communication": "failed",
        "writer": "pending",
    }
    assert "local model" in attempt["analysis"]["passes"]["communication"]["error"]
    assert attempt["analysis"]["technical"]["concepts"]
    assert client.post(f"/api/attempts/{attempt['id']}/note", json={"skip": True}).status_code == 200
    assert fake_llm.requests_for("writer") == []
    assert client.post(f"/api/attempts/{attempt['id']}/retry").status_code == 200
    retried = attempt_row(attempt["id"])
    assert set(statuses(retried).values()) == {"done"}
    assert retried["status"] == "ready"
    assert len(fake_llm.requests_for("technical")) == 1  # done passes are not re-run
    assert len(fake_llm.requests_for("communication")) == 2
    assert len(review_messages(session["id"])) == 1


def test_writer_failure_keeps_review_structure_and_retry_writes_message(client, wav_bytes, fake_llm):
    session = create(client)
    attempt = upload(client, session, wav_bytes)
    fake_llm.queue("writer", fake_llm.defaults["writer"], httpx.ConnectError("offline"))
    client.post(f"/api/attempts/{attempt['id']}/note", json={"skip": True})
    failed = attempt_row(attempt["id"])
    assert failed["status"] == "partial"
    assert statuses(failed)["writer"] == "failed"
    assert failed["analysis"]["review"]["scores"]
    assert review_messages(session["id"]) == []
    client.post(f"/api/attempts/{attempt['id']}/retry")
    assert statuses(attempt_row(attempt["id"]))["writer"] == "done"
    assert len(fake_llm.requests_for("writer")) == 3  # the structure is not rewritten
    assert len(review_messages(session["id"])) == 1


def test_prompt_too_long_is_a_failed_pass_with_a_readable_error(client, wav_bytes, monkeypatch):
    from app import coach, llm

    def too_long(*args, **kwargs):
        raise llm.PromptTooLong("The technical prompt is too long for the model's context window.")

    monkeypatch.setattr(coach, "technical_pass", too_long)
    attempt = upload(client, create(client), wav_bytes)
    passes = attempt["analysis"]["passes"]
    assert passes["technical"]["status"] == "failed"
    assert "too long" in passes["technical"]["error"]
    assert passes["communication"]["status"] == "done"


def test_too_short_attempt_gets_no_scores(client, wav_bytes, monkeypatch, fake_llm):
    monkeypatch.setattr(models, "transcribe", lambda *args: ("Testing one two three.", []))
    session = create(client)
    attempt = upload(client, session, wav_bytes)
    assert attempt["analysis"]["review"] == {"too_short": True}
    assert set(statuses(attempt).values()) == {"skipped"}
    assert attempt["transcript"] == "Testing one two three." and attempt["lines"]
    assert fake_llm.requests == []
    assert client.post(f"/api/attempts/{attempt['id']}/note", json={"skip": True}).status_code == 200
    assert fake_llm.requests == []
    assert review_messages(session["id"]) == []


def test_review_receives_folded_notes(client, wav_bytes, fake_llm):
    first_session = create(client)
    first = upload(client, first_session, wav_bytes)
    client.post(f"/api/attempts/{first['id']}/note", json={"skip": True})
    with db.connect() as conn:
        for role, text in (("user", "I'm working on keeping things light."), ("assistant", "Try a light opener.")):
            conn.execute(
                "INSERT INTO messages(session_id,role,content,created_at,attempt_number,kind) VALUES(?,?,?,?,?,?)",
                (first_session["id"], role, text, db.now(), 1, "chat"),
            )
    notes = "## Focus: keeping things light\nSince today. Said they are working on keeping things light."
    fake_llm.queue("memory", notes)
    second = upload(client, create(client), wav_bytes)
    assert second["analysis"]["passes"]["memory"]["status"] == "done"
    assert second["analysis"]["passes"]["memory"]["model"]
    memory_request = fake_llm.requests_for("memory")[0]
    assert memory_request["payload"]["attempts"][0]["learner_messages"] == ["I'm working on keeping things light."]
    assert fake_llm.requests_for("communication")[-1]["payload"]["coach_notes"] == notes
    client.post(f"/api/attempts/{second['id']}/note", json={"skip": True})
    structure = fake_llm.requests_for("writer")[-2]
    assert "format" in structure["body"] and structure["payload"]["coach_notes"] == notes


def test_memory_failure_is_recorded_without_blocking(client, wav_bytes, fake_llm):
    first_session = create(client)
    first = upload(client, first_session, wav_bytes)
    client.post(f"/api/attempts/{first['id']}/note", json={"skip": True})
    fake_llm.queue("memory", httpx.ConnectError("offline"))
    second = upload(client, create(client), wav_bytes)
    passes = second["analysis"]["passes"]
    assert passes["memory"]["status"] == "failed" and passes["memory"]["error"]
    assert passes["technical"]["status"] == passes["communication"]["status"] == "done"
    assert second["status"] == "partial"


def test_note_deadline_survives_restart(client, wav_bytes):
    session = create(client)
    attempt = upload(client, session, wav_bytes)
    assert statuses(attempt)["writer"] == "waiting"
    past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    db.execute("UPDATE attempts SET note_deadline=? WHERE id=?", (past, attempt["id"]))
    db.initialize()
    pipeline.sweep_note_deadlines()
    assert len(review_messages(session["id"])) == 1
    assert attempt_row(attempt["id"])["note_state"] == "skipped"


def test_session_detail_sweeps_expired_note_deadlines(client, wav_bytes):
    session = create(client)
    attempt = upload(client, session, wav_bytes)
    future = (datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat()
    db.execute("UPDATE attempts SET note_deadline=? WHERE id=?", (future, attempt["id"]))
    client.get(f"/api/sessions/{session['id']}")
    assert review_messages(session["id"]) == []
    past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    db.execute("UPDATE attempts SET note_deadline=? WHERE id=?", (past, attempt["id"]))
    detail = client.get(f"/api/sessions/{session['id']}").json()
    assert [m["kind"] for m in detail["messages"]] == ["review"]


def test_attempt2_review_receives_attempt1_review(client, wav_bytes, fake_llm):
    session = create(client)
    first = upload(client, session, wav_bytes)
    client.post(f"/api/attempts/{first['id']}/note", json={"skip": True})
    open_attempt2(client, session)
    second = upload(client, session, wav_bytes, 2)
    client.post(f"/api/attempts/{second['id']}/note", json={"skip": True})
    structure = fake_llm.requests_for("writer")[-2]
    assert structure["payload"]["attempt_1_scores"][0] == {"name": "Overall", "score": 5.0}
    stored = attempt_row(second["id"])
    assert stored["analysis"]["review"]["comparison"]["changes"]
    kinds = [(m["attempt_number"], m["kind"]) for m in client.get(f"/api/sessions/{session['id']}").json()["messages"]]
    assert kinds == [(1, "review"), (2, "review")]


def test_offline_models_still_allow_recording_and_transcript(client, wav_bytes, fake_llm):
    for name in ("technical", "communication", "writer", "memory"):
        fake_llm.defaults[name] = httpx.ConnectError("offline")
    session = create(client)
    first = upload(client, session, wav_bytes)
    assert first["status"] == "partial"
    assert first["transcript"] == TRANSCRIPT
    assert first["lines"] and first["tokens"]
    assert first["acoustics"]["duration"] == 2.6
    assert first["analysis"]["stats"]["duration"] == 2.6
    assert statuses(first) == {
        "memory": "done",
        "technical": "failed",
        "communication": "failed",
        "writer": "pending",
    }
    assert client.post(f"/api/attempts/{first['id']}/note", json={"text": "Felt shaky."}).status_code == 200
    assert client.get(f"/api/attempts/{first['id']}/audio").content == wav_bytes
    open_attempt2(client, session)
    second = upload(client, session, wav_bytes, 2)
    assert second["transcript"] == TRANSCRIPT and second["status"] == "partial"
    assert review_messages(session["id"]) == []


def test_replacing_transcript_resets_analysis_and_review(client, wav_bytes, fake_llm):
    session = create(client)
    attempt = upload(client, session, wav_bytes)
    client.post(f"/api/attempts/{attempt['id']}/note", json={"skip": True})
    assert len(review_messages(session["id"])) == 1
    text = "Um a hash map maps each key to a value by hashing the key to pick one bucket in an array."
    assert client.put(f"/api/attempts/{attempt['id']}/transcript", json={"text": text}).status_code == 200
    edited = attempt_row(attempt["id"])
    assert all(line["start"] is None for line in edited["lines"])
    assert edited["lines"][0]["text"] == text
    assert statuses(edited) == {name: "done" for name in ("memory", "technical", "communication", "writer")}
    [review] = review_messages(session["id"])
    assert len(fake_llm.requests_for("technical")) == 2
    history = client.get(f"/api/attempts/{attempt['id']}/analysis-history").json()
    assert history[0]["attempt"]["analysis"]["review"]["scores"]
    assert history[0]["attempt"]["review_message"] == MINIMAL_REVIEW
    assert review["content"] == MINIMAL_REVIEW


def test_legacy_attempt_edit_archives_assessment_and_gets_new_review(client, wav_bytes):
    session = create(client)
    attempt = upload(client, session, wav_bytes)
    legacy = {"summary": "Legacy summary.", "concepts": []}
    db.execute(
        "UPDATE attempts SET analysis=NULL, lines=NULL, tokens=NULL, assessment=?, note_state='legacy' WHERE id=?",
        (json.dumps(legacy), attempt["id"]),
    )
    text = "A hash map stores each key with its value and hashes the key to choose one bucket in an array."
    assert client.put(f"/api/attempts/{attempt['id']}/transcript", json={"text": text}).status_code == 200
    history = client.get(f"/api/attempts/{attempt['id']}/analysis-history").json()
    assert history[0]["attempt"]["assessment"] == legacy
    stored = attempt_row(attempt["id"])
    assert stored["note_state"] == "skipped"
    assert statuses(stored)["writer"] == "done"
    assert len(review_messages(session["id"])) == 1


def test_note_timeout_runs_writer_through_real_timer_and_executor(client, wav_bytes, monkeypatch):
    monkeypatch.setattr(pipeline, "NOTE_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(threading, "Timer", REAL_TIMER)
    monkeypatch.setattr(pipeline, "submit_writer", REAL_SUBMIT_WRITER)
    session = create(client)
    attempt = upload(client, session, wav_bytes)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and not review_messages(session["id"]):
        time.sleep(0.02)
    pipeline.executor.submit(lambda: None).result(timeout=10)  # let the writer finish its last save
    stored = attempt_row(attempt["id"])
    assert stored["note_state"] == "skipped"
    assert statuses(stored)["writer"] == "done" and stored["status"] == "ready"
    assert len(review_messages(session["id"])) == 1


def test_queued_writer_survives_restart(client, wav_bytes, monkeypatch):
    session = create(client)
    attempt = upload(client, session, wav_bytes)
    monkeypatch.setattr(pipeline, "submit_writer", lambda _: None)  # the process dies before write starts
    assert client.post(f"/api/attempts/{attempt['id']}/note", json={"skip": True}).status_code == 200
    assert statuses(attempt_row(attempt["id"]))["writer"] == "pending"
    assert review_messages(session["id"]) == []
    monkeypatch.setattr(pipeline, "submit_writer", pipeline.write)
    db.initialize()
    pipeline.recover_writers()
    stored = attempt_row(attempt["id"])
    assert statuses(stored)["writer"] == "done" and stored["status"] == "ready"
    assert len(review_messages(session["id"])) == 1


def test_writer_interrupted_by_crash_is_recovered_by_retry(client, wav_bytes, monkeypatch):
    session = create(client)
    attempt = upload(client, session, wav_bytes)
    monkeypatch.setattr(pipeline, "submit_writer", lambda _: None)
    client.post(f"/api/attempts/{attempt['id']}/note", json={"skip": True})
    # Simulate a crash in the middle of write(): writer running, attempt processing.
    _row, analysis = pipeline._load(attempt["id"])
    analysis["passes"]["writer"]["status"] = "running"
    pipeline._save(attempt["id"], analysis)
    db.execute("UPDATE attempts SET status='processing' WHERE id=?", (attempt["id"],))
    monkeypatch.setattr(pipeline, "submit_writer", pipeline.write)
    db.initialize()
    pipeline.recover_writers()  # an interrupted attempt is left for Retry, not re-run silently
    interrupted = attempt_row(attempt["id"])
    assert interrupted["status"] == "interrupted" and review_messages(session["id"]) == []
    assert client.post(f"/api/attempts/{attempt['id']}/retry").status_code == 200
    stored = attempt_row(attempt["id"])
    assert statuses(stored)["writer"] == "done" and stored["status"] == "ready" and stored["errors"] == {}
    assert len(review_messages(session["id"])) == 1


def test_transcription_offline_keeps_recording_and_runs_no_model_pass(client, wav_bytes, monkeypatch, fake_llm):
    def unavailable(*args):
        raise models.ServiceUnavailable("Explicitly offline for this test.")

    monkeypatch.setattr(models, "transcribe", unavailable)
    session = create(client)
    first = upload(client, session, wav_bytes)
    assert first["status"] == "partial"
    assert first["errors"]["transcription"] == "Explicitly offline for this test."
    assert first["transcript"] is None and first["analysis"] is None
    assert first["acoustics"]["duration"] == 2.6
    assert first["acoustics"].get("wpm") is None
    assert client.get(first["audio_url"]).content == wav_bytes
    open_attempt2(client, session)
    second = upload(client, session, wav_bytes, 2)
    assert second["status"] == "partial" and second["acoustics"]["duration"] == 2.6
    assert fake_llm.requests == []


# Day split, automatic completion and the Today queue


class FrozenDate(date):
    offset = 0

    @classmethod
    def today(cls):
        return date.today() + timedelta(days=cls.offset)


def freeze_days_ahead(monkeypatch, days):
    from app import main

    monkeypatch.setattr(FrozenDate, "offset", days, raising=False)
    monkeypatch.setattr(main, "date", FrozenDate)


def review_attempt1(client, session, wav_bytes):
    first = upload(client, session, wav_bytes)
    assert client.post(f"/api/attempts/{first['id']}/note", json={"skip": True}).status_code == 200
    return first


open_day2 = open_attempt2


def session_row(session_id):
    return db.one("SELECT * FROM sessions WHERE id=?", (session_id,))


def test_derived_recall_thresholds():
    assert [progress.derived_recall(m) for m in (1.0, 0.8, 0.79, 0.5, 0.49, 0.0, None)] == [
        "good",
        "good",
        "hard",
        "hard",
        "again",
        "again",
        "again",
    ]


def test_upload_sets_attempt2_after_tomorrow(client, wav_bytes):
    session = create(client)
    upload(client, session, wav_bytes)
    row = session_row(session["id"])
    assert row["stage"] == "review1"
    assert row["attempt2_after"] == (date.today() + timedelta(days=1)).isoformat()


def test_attempt2_same_day_is_refused(client, wav_bytes):
    session = create(client)
    review_attempt1(client, session, wav_bytes)
    response = client.put(f"/api/sessions/{session['id']}/stage", json={"stage": "record2"})
    assert response.status_code == 409
    assert response.json()["detail"] == "Attempt 2 opens tomorrow so it tests what you remember."
    assert session_row(session["id"])["stage"] == "review1"


def test_attempt2_allowed_next_day(client, wav_bytes, monkeypatch):
    session = create(client)
    review_attempt1(client, session, wav_bytes)
    freeze_days_ahead(monkeypatch, 1)
    response = client.put(f"/api/sessions/{session['id']}/stage", json={"stage": "record2"})
    assert response.status_code == 200 and response.json()["stage"] == "record2"
    upload(client, session, wav_bytes, 2)
    assert session_row(session["id"])["stage"] == "review2"


def test_old_stage_names_are_rejected(client, wav_bytes):
    session = create(client)
    for name in ("feedback", "learn", "compare"):
        assert client.put(f"/api/sessions/{session['id']}/stage", json={"stage": name}).status_code == 422


def test_session_autocompletes_after_attempt2_review_and_schedules(client, wav_bytes):
    session = create(client)
    review_attempt1(client, session, wav_bytes)
    open_day2(client, session)
    second = upload(client, session, wav_bytes, 2)
    assert session_row(session["id"])["completed_at"] is None  # the review is still to come
    assert client.post(f"/api/attempts/{second['id']}/note", json={"skip": True}).status_code == 200
    stored = attempt_row(second["id"])
    concepts = stored["analysis"]["technical"]["concepts"]
    mastery = sum(c["status"] == "correct" for c in concepts) / len(concepts)
    done = session_row(session["id"])
    assert done["completed_at"] and done["stage"] == "review2"
    assert done["recall"] == progress.derived_recall(mastery)
    days, repetitions, due = progress.schedule(None, done["recall"], mastery)
    assert done["review_due"] == due
    review = db.one("SELECT * FROM reviews WHERE topic_id='hash-maps'")
    assert (review["interval_days"], review["repetitions"], review["due"]) == (days, repetitions, due)
    assert review["last_session_id"] == session["id"]
    # Running it again changes nothing.
    pipeline.complete_session(session["id"])
    assert session_row(session["id"])["completed_at"] == done["completed_at"]
    assert db.one("SELECT * FROM reviews WHERE topic_id='hash-maps'") == review
    assert client.get("/api/sessions/%s" % session["id"]).json()["completed_at"]


def test_good_attempt2_schedules_a_longer_interval(client, wav_bytes):
    session = create(client)
    review_attempt1(client, session, wav_bytes)
    open_day2(client, session)
    second = upload(client, session, wav_bytes, 2)
    analysis = json.loads(db.one("SELECT analysis FROM attempts WHERE id=?", (second["id"],))["analysis"])
    for concept in analysis["technical"]["concepts"]:
        concept["status"] = "correct"
    db.execute("UPDATE attempts SET analysis=? WHERE id=?", (json.dumps(analysis), second["id"]))
    pipeline.complete_session(session["id"])
    done = session_row(session["id"])
    assert done["recall"] == "good"
    assert db.one("SELECT interval_days FROM reviews WHERE topic_id='hash-maps'")["interval_days"] == 3


def test_too_short_attempt2_still_completes_with_again(client, wav_bytes, monkeypatch):
    session = create(client)
    review_attempt1(client, session, wav_bytes)
    open_day2(client, session)
    monkeypatch.setattr(models, "transcribe", lambda path, duration: ("Um, testing.", [{"start": 0, "end": 1, "text": "Um, testing."}]))
    second = upload(client, session, wav_bytes, 2)
    assert attempt_row(second["id"])["analysis"]["review"] == {"too_short": True}
    done = session_row(session["id"])
    assert done["completed_at"] and done["recall"] == "again"
    assert done["review_due"] == (date.today() + timedelta(days=1)).isoformat()
    assert db.one("SELECT interval_days FROM reviews WHERE topic_id='hash-maps'")["interval_days"] == 1


def test_too_short_attempt1_does_not_complete(client, wav_bytes, monkeypatch):
    monkeypatch.setattr(models, "transcribe", lambda path, duration: ("Um, testing.", [{"start": 0, "end": 1, "text": "Um, testing."}]))
    session = create(client)
    upload(client, session, wav_bytes)
    assert session_row(session["id"])["completed_at"] is None


def test_too_short_attempt1_can_be_recorded_again(client, wav_bytes, monkeypatch):
    monkeypatch.setattr(models, "transcribe", lambda path, duration: ("Um, testing.", [{"start": 0, "end": 1, "text": "Um, testing."}]))
    session = create(client)
    first = upload(client, session, wav_bytes)
    assert attempt_row(first["id"])["analysis"]["review"] == {"too_short": True}
    response = client.put(f"/api/sessions/{session['id']}/stage", json={"stage": "record1"})
    assert response.status_code == 200 and response.json()["stage"] == "record1"
    monkeypatch.setattr(models, "transcribe", lambda path, duration: (TRANSCRIPT, [{"start": 0, "end": 2.6, "text": TRANSCRIPT}]))
    second = upload(client, session, wav_bytes)
    assert second["id"] != first["id"]
    assert db.one("SELECT id FROM attempts WHERE id=?", (first["id"],)) is None
    assert session_row(session["id"])["stage"] == "review1"


def test_attempt2_recorder_is_closed_once_attempt2_exists(client, wav_bytes):
    """review2 -> record2 would leave the session where every action is refused once it completes."""
    session = create(client)
    review_attempt1(client, session, wav_bytes)
    open_day2(client, session)
    second = upload(client, session, wav_bytes, 2)
    assert session_row(session["id"])["completed_at"] is None  # the note box is still open
    response = client.put(f"/api/sessions/{session['id']}/stage", json={"stage": "record2"})
    assert response.status_code == 409
    assert "preserved" in response.json()["detail"]
    assert session_row(session["id"])["stage"] == "review2"
    assert client.post(f"/api/attempts/{second['id']}/note", json={"skip": True}).status_code == 200
    assert session_row(session["id"])["completed_at"]


def test_completing_a_session_leaves_it_at_review2(client, wav_bytes):
    session = create(client)
    review_attempt1(client, session, wav_bytes)
    open_day2(client, session)
    upload(client, session, wav_bytes, 2)
    # A session that reached the recorder again before this fix, with attempt 2 still being reviewed.
    db.execute("UPDATE sessions SET stage='record2' WHERE id=?", (session["id"],))
    pipeline.complete_session(session["id"])
    done = session_row(session["id"])
    assert done["completed_at"] and done["stage"] == "review2"


def test_reviewed_attempt1_cannot_return_to_record1(client, wav_bytes):
    session = create(client)
    upload(client, session, wav_bytes)
    response = client.put(f"/api/sessions/{session['id']}/stage", json={"stage": "record1"})
    assert response.status_code == 409
    assert "preserved" in response.json()["detail"]


def test_today_queue_lists_pending_attempt2_and_hides_its_spaced_review(client, wav_bytes):
    done = create(client)
    review_attempt1(client, done, wav_bytes)
    open_day2(client, done)
    second = upload(client, done, wav_bytes, 2)
    client.post(f"/api/attempts/{second['id']}/note", json={"skip": True})
    assert [r["topic_id"] for r in client.get("/api/reviews").json()] == ["hash-maps"]
    assert client.get("/api/attempt2").json() == []
    db.execute("UPDATE reviews SET due='2000-01-01'")
    pending = create(client)
    review_attempt1(client, pending, wav_bytes)
    assert client.get("/api/reviews").json() == []
    [item] = client.get("/api/attempt2").json()
    assert item["session_id"] == pending["id"] and item["topic"]["id"] == "hash-maps"
    assert item["attempt2_after"] == (date.today() + timedelta(days=1)).isoformat()
    assert item["available"] is False
    open_day2(client, pending)  # record2 stays in the queue until attempt 2 is reviewed
    assert client.get("/api/reviews").json() == []
    assert client.get("/api/attempt2").json()[0]["available"] is True


def test_pending_attempt2_never_expires(client, wav_bytes, monkeypatch):
    session = create(client)
    review_attempt1(client, session, wav_bytes)
    freeze_days_ahead(monkeypatch, 30)
    [item] = client.get("/api/attempt2").json()
    assert item["session_id"] == session["id"] and item["available"] is True
    assert session_row(session["id"])["completed_at"] is None


def test_legacy_session_weak_topics_use_old_assessment(client, wav_bytes, monkeypatch):
    from app import main

    legacy = create(client)
    upload(client, legacy, wav_bytes)
    modern = create(client)
    upload(client, modern, wav_bytes)
    # Legacy: attempt 2 only has the old assessment (1 of 4 correct).
    db.execute(
        "INSERT INTO attempts(id,session_id,number,created_at,audio_file,wav_file,mime,duration,assessment) "
        "VALUES('legacy2',?,2,'2026-10-01T00:00:00+00:00','a','w','audio/wav',3,?)",
        (legacy["id"], json.dumps({"concepts": [{"status": "correct"}] + [{"status": "missing"}] * 3})),
    )
    db.execute(
        "UPDATE sessions SET completed_at='2026-10-01T00:00:00+00:00', created_at='2026-10-01T00:00:00+00:00' WHERE id=?",
        (legacy["id"],),
    )
    seen = {}

    def spy(candidates, reviews, weak):
        seen.update(weak)
        return candidates[0]

    monkeypatch.setattr(main, "recommend", spy)
    assert client.get("/api/topics/recommend").status_code == 200
    assert seen == {"hash-maps": 0.75}
    # A newer session with the new analysis replaces the legacy figure.
    technical = {"concepts": [{"status": "correct"}] * 3 + [{"status": "missing"}]}
    db.execute(
        "INSERT INTO attempts(id,session_id,number,created_at,audio_file,wav_file,mime,duration,analysis) "
        "VALUES('new2',?,2,'2026-10-02T00:00:00+00:00','a','w','audio/wav',3,?)",
        (modern["id"], json.dumps({"technical": technical})),
    )
    db.execute("UPDATE sessions SET completed_at='2026-10-02T00:00:00+00:00', created_at='2026-10-02T00:00:00+00:00' WHERE id=?", (modern["id"],))
    seen.clear()
    client.get("/api/topics/recommend")
    assert seen == {"hash-maps": 0.25}


def test_note_refused_for_completed_session(client, wav_bytes):
    session = create(client)
    first = upload(client, session, wav_bytes)
    db.execute("UPDATE sessions SET completed_at='2026-10-27T12:00:00+00:00' WHERE id=?", (session["id"],))
    response = client.post(f"/api/attempts/{first['id']}/note", json={"skip": True})
    assert response.status_code == 409


def test_rereview_archives_previous_and_reruns(client, wav_bytes, fake_llm):
    session = create(client)
    attempt = upload(client, session, wav_bytes)
    client.post(f"/api/attempts/{attempt['id']}/note", json={"skip": True})
    assert len(review_messages(session["id"])) == 1
    response = client.post(f"/api/attempts/{attempt['id']}/rereview")
    assert response.status_code == 200 and response.json() == {"status": "pending"}
    stored = attempt_row(attempt["id"])
    assert stored["note_state"] == "skipped"
    assert statuses(stored) == {name: "done" for name in ("memory", "technical", "communication", "writer")}
    assert len(fake_llm.requests_for("technical")) == 2
    [review] = review_messages(session["id"])  # replaced, not duplicated
    assert review["content"] == MINIMAL_REVIEW
    history = client.get(f"/api/attempts/{attempt['id']}/analysis-history").json()
    assert len(history) == 1
    assert history[0]["attempt"]["review_message"] == MINIMAL_REVIEW
    assert history[0]["attempt"]["analysis"]["review"]["scores"]
    assert "audio_file" not in history[0]["attempt"]


def test_rereview_upgrades_legacy_attempt_and_keeps_completed_schedule(client, wav_bytes):
    session = create(client)
    attempt = upload(client, session, wav_bytes)
    legacy = {"summary": "Legacy summary.", "concepts": []}
    db.execute(
        "UPDATE attempts SET analysis=NULL, lines=NULL, tokens=NULL, assessment=?, note_state='legacy' WHERE id=?",
        (json.dumps(legacy), attempt["id"]),
    )
    db.execute(
        "UPDATE sessions SET completed_at='2026-10-27T12:00:00+00:00', review_due='2026-10-30' WHERE id=?",
        (session["id"],),
    )
    before = db.one("SELECT * FROM attempts WHERE id=?", (attempt["id"],))
    assert client.post(f"/api/attempts/{attempt['id']}/rereview").status_code == 200
    stored = attempt_row(attempt["id"])
    after = db.one("SELECT * FROM attempts WHERE id=?", (attempt["id"],))
    assert after["audio_file"] == before["audio_file"] and after["transcript"] == before["transcript"]
    assert stored["note_state"] == "skipped" and statuses(stored)["writer"] == "done"
    assert len(review_messages(session["id"])) == 1
    history = client.get(f"/api/attempts/{attempt['id']}/analysis-history").json()
    assert history[0]["attempt"]["assessment"] == legacy
    assert session_row(session["id"])["review_due"] == "2026-10-30"


def test_rereview_refused_while_processing(client, wav_bytes, fake_llm):
    session = create(client)
    attempt = upload(client, session, wav_bytes)
    requests_before = len(fake_llm.requests)
    for status in ("pending", "processing"):
        db.execute("UPDATE attempts SET status=? WHERE id=?", (status, attempt["id"]))
        response = client.post(f"/api/attempts/{attempt['id']}/rereview")
        assert response.status_code == 409
        assert "still" in response.json()["detail"].lower() or "running" in response.json()["detail"].lower()
    assert client.get(f"/api/attempts/{attempt['id']}/analysis-history").json() == []
    assert len(fake_llm.requests) == requests_before
    assert client.post("/api/attempts/nope/rereview").status_code == 404


def test_rereview_preserves_manual_transcript_and_never_retranscribes(client, wav_bytes, monkeypatch):
    session = create(client)
    attempt = upload(client, session, wav_bytes)
    manual = "A hash map stores each key with its value and hashes the key to choose one bucket in an array."
    db.execute(
        "UPDATE attempts SET transcript=?, transcript_source='manual', transcription_version=0, "
        "segments='[]', retranscribe=1 WHERE id=?",
        (manual, attempt["id"]),
    )
    monkeypatch.setattr(
        models, "transcribe", lambda *a: (_ for _ in ()).throw(AssertionError("must not retranscribe"))
    )
    before = db.one("SELECT * FROM attempts WHERE id=?", (attempt["id"],))
    assert client.post(f"/api/attempts/{attempt['id']}/rereview").status_code == 200
    after = db.one("SELECT * FROM attempts WHERE id=?", (attempt["id"],))
    assert after["status"] == "ready" and after["retranscribe"] == 0
    assert after["transcript"] == manual and after["transcript_source"] == "manual"
    assert after["transcription_version"] == before["transcription_version"] == 0
    assert after["audio_file"] == before["audio_file"]
