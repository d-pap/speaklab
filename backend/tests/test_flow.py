import json
import threading
import time
from datetime import datetime, timedelta, timezone

import httpx
from conftest import MINIMAL_REVIEW, TRANSCRIPT, get_thread, next_day, upload

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
    attempt = upload(client, wav_bytes)
    session = {"id": attempt["session_id"]}
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
    attempt = upload(client, wav_bytes)
    assert client.post(f"/api/attempts/{attempt['id']}/note", json={"text": "x" * 2001}).status_code == 422
    response = client.post(f"/api/attempts/{attempt['id']}/note", json={"text": "  I rushed the ending.  "})
    assert response.status_code == 200, response.text
    assert client.post(f"/api/attempts/{attempt['id']}/note", json={"skip": True}).status_code == 409
    detail = get_thread(client)
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
    attempt = upload(client, wav_bytes)
    session = {"id": attempt["session_id"]}
    assert client.post(f"/api/attempts/{attempt['id']}/note", json={"skip": True}).status_code == 200
    assert fake_llm.requests_for("writer") == []
    pipeline.process(attempt["id"])
    assert attempt_row(attempt["id"])["note_state"] == "skipped"
    assert len(review_messages(session["id"])) == 1
    assert client.note_timers == []


def test_writer_phase_starts_after_note_timeout(client, wav_bytes, monkeypatch):
    monkeypatch.setattr(pipeline, "NOTE_TIMEOUT_SECONDS", 0)
    monkeypatch.setattr(threading, "Timer", ImmediateTimer)
    attempt = upload(client, wav_bytes)
    session = {"id": attempt["session_id"]}
    stored = attempt_row(attempt["id"])
    assert stored["note_state"] == "skipped"
    assert statuses(stored)["writer"] == "done"
    assert stored["status"] == "ready"
    assert len(review_messages(session["id"])) == 1
    pipeline.auto_skip(attempt["id"])  # a late timer changes nothing
    assert len(review_messages(session["id"])) == 1


def test_pipeline_keeps_earlier_passes_when_later_pass_fails(client, wav_bytes, fake_llm):
    fake_llm.queue("communication", httpx.ConnectError("offline"))
    attempt = upload(client, wav_bytes)
    session = {"id": attempt["session_id"]}
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
    attempt = upload(client, wav_bytes)
    session = {"id": attempt["session_id"]}
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
    attempt = upload(client, wav_bytes)
    passes = attempt["analysis"]["passes"]
    assert passes["technical"]["status"] == "failed"
    assert "too long" in passes["technical"]["error"]
    assert passes["communication"]["status"] == "done"


def test_too_short_attempt_gets_no_scores(client, wav_bytes, monkeypatch, fake_llm):
    monkeypatch.setattr(models, "transcribe", lambda *args: ("Testing one two three.", []))
    attempt = upload(client, wav_bytes)
    session = {"id": attempt["session_id"]}
    assert attempt["analysis"]["review"] == {"too_short": True}
    assert set(statuses(attempt).values()) == {"skipped"}
    assert attempt["transcript"] == "Testing one two three." and attempt["lines"]
    assert fake_llm.requests == []
    assert client.post(f"/api/attempts/{attempt['id']}/note", json={"skip": True}).status_code == 200
    assert fake_llm.requests == []
    assert review_messages(session["id"]) == []


def test_review_receives_folded_notes(client, wav_bytes, fake_llm):
    first = upload(client, wav_bytes)
    first_session = {"id": first["session_id"]}
    client.post(f"/api/attempts/{first['id']}/note", json={"skip": True})
    with db.connect() as conn:
        for role, text in (("user", "I'm working on keeping things light."), ("assistant", "Try a light opener.")):
            conn.execute(
                "INSERT INTO messages(session_id,role,content,created_at,attempt_number,kind) VALUES(?,?,?,?,?,?)",
                (first_session["id"], role, text, db.now(), 1, "chat"),
            )
    notes = "## Focus: keeping things light\nSince today. Said they are working on keeping things light."
    fake_llm.queue("memory", notes)
    second = upload(client, wav_bytes, "caching")
    assert second["analysis"]["passes"]["memory"]["status"] == "done"
    assert second["analysis"]["passes"]["memory"]["model"]
    memory_request = fake_llm.requests_for("memory")[0]
    assert memory_request["payload"]["attempts"][0]["learner_messages"] == ["I'm working on keeping things light."]
    assert fake_llm.requests_for("communication")[-1]["payload"]["coach_notes"] == notes
    client.post(f"/api/attempts/{second['id']}/note", json={"skip": True})
    structure = fake_llm.requests_for("writer")[-2]
    assert "format" in structure["body"] and structure["payload"]["coach_notes"] == notes


def test_memory_failure_is_recorded_without_blocking(client, wav_bytes, fake_llm):
    first = upload(client, wav_bytes)
    client.post(f"/api/attempts/{first['id']}/note", json={"skip": True})
    fake_llm.queue("memory", httpx.ConnectError("offline"))
    second = upload(client, wav_bytes, "caching")
    passes = second["analysis"]["passes"]
    assert passes["memory"]["status"] == "failed" and passes["memory"]["error"]
    assert passes["technical"]["status"] == passes["communication"]["status"] == "done"
    assert second["status"] == "partial"


def test_note_deadline_survives_restart(client, wav_bytes):
    attempt = upload(client, wav_bytes)
    session = {"id": attempt["session_id"]}
    assert statuses(attempt)["writer"] == "waiting"
    past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    db.execute("UPDATE attempts SET note_deadline=? WHERE id=?", (past, attempt["id"]))
    db.initialize()
    pipeline.sweep_note_deadlines()
    assert len(review_messages(session["id"])) == 1
    assert attempt_row(attempt["id"])["note_state"] == "skipped"


def test_thread_view_sweeps_expired_note_deadlines(client, wav_bytes):
    attempt = upload(client, wav_bytes)
    session = {"id": attempt["session_id"]}
    future = (datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat()
    db.execute("UPDATE attempts SET note_deadline=? WHERE id=?", (future, attempt["id"]))
    get_thread(client)
    assert review_messages(session["id"]) == []
    past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    db.execute("UPDATE attempts SET note_deadline=? WHERE id=?", (past, attempt["id"]))
    detail = get_thread(client)
    assert [m["kind"] for m in detail["messages"]] == ["review"]


def test_attempt2_review_receives_attempt1_review(client, wav_bytes, fake_llm):
    first = upload(client, wav_bytes)
    client.post(f"/api/attempts/{first['id']}/note", json={"skip": True})
    next_day(first["session_id"])
    second = upload(client, wav_bytes)
    client.post(f"/api/attempts/{second['id']}/note", json={"skip": True})
    structure = fake_llm.requests_for("writer")[-2]
    assert structure["payload"]["previous_attempt_scores"][0] == {"name": "Overall", "score": 5.0}
    stored = attempt_row(second["id"])
    assert stored["analysis"]["review"]["comparison"]["changes"]
    kinds = [(m["attempt_number"], m["kind"]) for m in get_thread(client)["messages"]]
    assert kinds == [(1, "review"), (2, "review")]


def test_offline_models_still_allow_recording_and_transcript(client, wav_bytes, fake_llm):
    for name in ("technical", "communication", "writer", "memory"):
        fake_llm.defaults[name] = httpx.ConnectError("offline")
    first = upload(client, wav_bytes)
    session = {"id": first["session_id"]}
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
    next_day(session["id"])
    second = upload(client, wav_bytes)
    assert second["transcript"] == TRANSCRIPT and second["status"] == "partial"
    assert review_messages(session["id"]) == []


def test_replacing_transcript_resets_analysis_and_review(client, wav_bytes, fake_llm):
    attempt = upload(client, wav_bytes)
    session = {"id": attempt["session_id"]}
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
    attempt = upload(client, wav_bytes)
    session = {"id": attempt["session_id"]}
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
    attempt = upload(client, wav_bytes)
    session = {"id": attempt["session_id"]}
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and not review_messages(session["id"]):
        time.sleep(0.02)
    pipeline.executor.submit(lambda: None).result(timeout=10)  # let the writer finish its last save
    stored = attempt_row(attempt["id"])
    assert stored["note_state"] == "skipped"
    assert statuses(stored)["writer"] == "done" and stored["status"] == "ready"
    assert len(review_messages(session["id"])) == 1


def test_queued_writer_survives_restart(client, wav_bytes, monkeypatch):
    attempt = upload(client, wav_bytes)
    session = {"id": attempt["session_id"]}
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
    attempt = upload(client, wav_bytes)
    session = {"id": attempt["session_id"]}
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
    first = upload(client, wav_bytes)
    session = {"id": first["session_id"]}
    assert first["status"] == "partial"
    assert first["errors"]["transcription"] == "Explicitly offline for this test."
    assert first["transcript"] is None and first["analysis"] is None
    assert first["acoustics"]["duration"] == 2.6
    assert first["acoustics"].get("wpm") is None
    assert client.get(first["audio_url"]).content == wav_bytes
    next_day(session["id"])
    second = upload(client, wav_bytes)
    assert second["status"] == "partial" and second["acoustics"]["duration"] == 2.6
    assert fake_llm.requests == []


# Spaced review, Today and recommendations


def review_attempt1(client, wav_bytes):
    first = upload(client, wav_bytes)
    assert client.post(f"/api/attempts/{first['id']}/note", json={"skip": True}).status_code == 200
    return first


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


def test_reviewed_attempt_schedules_from_its_mastery(client, wav_bytes):
    first = review_attempt1(client, wav_bytes)
    stored = attempt_row(first["id"])
    concepts = stored["analysis"]["technical"]["concepts"]
    mastery = sum(c["status"] == "correct" for c in concepts) / len(concepts)
    days, repetitions, due = progress.schedule(None, progress.derived_recall(mastery), mastery)
    review = db.one("SELECT * FROM reviews WHERE topic_id='hash-maps'")
    assert (review["interval_days"], review["repetitions"], review["due"]) == (days, repetitions, due)
    assert review["last_session_id"] == first["session_id"]
    # Running it again changes nothing.
    pipeline.after_review_written(first["id"])
    assert db.one("SELECT * FROM reviews WHERE topic_id='hash-maps'") == review
    session = db.one("SELECT * FROM sessions WHERE id=?", (first["session_id"],))
    assert session["completed_at"] is None and session["review_due"] is None


def test_good_attempt_schedules_a_longer_interval(client, wav_bytes):
    attempt = upload(client, wav_bytes)  # the note box is open: its review is still to come
    analysis = json.loads(db.one("SELECT analysis FROM attempts WHERE id=?", (attempt["id"],))["analysis"])
    for concept in analysis["technical"]["concepts"]:
        concept["status"] = "correct"
    db.execute("UPDATE attempts SET analysis=? WHERE id=?", (json.dumps(analysis), attempt["id"]))
    pipeline.after_review_written(attempt["id"])
    assert db.one("SELECT interval_days FROM reviews WHERE topic_id='hash-maps'")["interval_days"] == 3


def test_only_the_latest_attempt_reschedules(client, wav_bytes):
    first = upload(client, wav_bytes)  # review still to come
    next_day(first["session_id"])
    review_attempt1(client, wav_bytes)
    before = db.one("SELECT * FROM reviews WHERE topic_id='hash-maps'")
    client.post(f"/api/attempts/{first['id']}/note", json={"skip": True})  # a late review of attempt 1
    assert attempt_row(first["id"])["analysis"]["passes"]["writer"]["status"] == "done"
    assert db.one("SELECT * FROM reviews WHERE topic_id='hash-maps'") == before


def test_too_short_attempt_does_not_schedule(client, wav_bytes, monkeypatch):
    monkeypatch.setattr(models, "transcribe", lambda path, duration: ("Um, testing.", [{"start": 0, "end": 1, "text": "Um, testing."}]))
    upload(client, wav_bytes)
    assert db.all_rows("SELECT * FROM reviews") == []


def test_too_short_attempt1_can_be_recorded_again(client, wav_bytes, monkeypatch):
    monkeypatch.setattr(models, "transcribe", lambda path, duration: ("Um, testing.", [{"start": 0, "end": 1, "text": "Um, testing."}]))
    first = upload(client, wav_bytes)
    assert attempt_row(first["id"])["analysis"]["review"] == {"too_short": True}
    assert get_thread(client)["recording"]["replace_number"] == 1
    monkeypatch.setattr(models, "transcribe", lambda path, duration: (TRANSCRIPT, [{"start": 0, "end": 2.6, "text": TRANSCRIPT}]))
    second = upload(client, wav_bytes)
    assert second["id"] != first["id"] and second["number"] == 1
    assert db.one("SELECT id FROM attempts WHERE id=?", (first["id"],)) is None


def test_open_attempt_never_expires(client, wav_bytes, monkeypatch):
    from datetime import date as real_date

    from app import threads

    first = review_attempt1(client, wav_bytes)
    monkeypatch.setattr(threads, "today", lambda: real_date.today() + timedelta(days=30))
    [item] = client.get("/api/practice/ready").json()
    assert item["session_id"] == first["session_id"] and item["can_record"] is True and item["due"] is True


def test_legacy_attempt_weak_topics_use_old_assessment(client, wav_bytes, monkeypatch):
    from app import main

    first = upload(client, wav_bytes)
    sid = first["session_id"]
    # A legacy attempt 2 has only the old assessment (1 of 4 correct).
    db.execute(
        "INSERT INTO attempts(id,session_id,number,created_at,audio_file,wav_file,mime,duration,assessment) "
        "VALUES('legacy2',?,2,'2026-10-01T00:00:00+00:00','a','w','audio/wav',3,?)",
        (sid, json.dumps({"concepts": [{"status": "correct"}] + [{"status": "missing"}] * 3})),
    )
    seen = {}

    def spy(candidates, reviews, weak):
        seen.update(weak)
        return candidates[0]

    monkeypatch.setattr(main, "recommend", spy)
    assert client.get("/api/topics/recommend", params={"include_practised": "true"}).status_code == 200
    assert seen == {"hash-maps": 0.75}
    # A later attempt with the new analysis replaces the legacy figure.
    technical = {"concepts": [{"status": "correct"}] * 3 + [{"status": "missing"}]}
    db.execute(
        "INSERT INTO attempts(id,session_id,number,created_at,audio_file,wav_file,mime,duration,analysis) "
        "VALUES('new3',?,3,'2026-10-02T00:00:00+00:00','a','w','audio/wav',3,?)",
        (sid, json.dumps({"technical": technical})),
    )
    seen.clear()
    client.get("/api/topics/recommend", params={"include_practised": "true"})
    assert seen == {"hash-maps": 0.25}


def test_rereview_archives_previous_and_reruns(client, wav_bytes, fake_llm):
    attempt = upload(client, wav_bytes)
    session = {"id": attempt["session_id"]}
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
    attempt = upload(client, wav_bytes)
    session = {"id": attempt["session_id"]}
    legacy = {"summary": "Legacy summary.", "concepts": []}
    db.execute(
        "UPDATE attempts SET analysis=NULL, lines=NULL, tokens=NULL, assessment=?, note_state='legacy' WHERE id=?",
        (json.dumps(legacy), attempt["id"]),
    )
    db.execute(
        "UPDATE sessions SET completed_at='2026-10-27T12:00:00+00:00', review_due='2026-10-30' WHERE id=?",
        (session["id"],),
    )
    db.execute("INSERT INTO reviews VALUES('hash-maps',3,1,'2026-10-30',?)", (session["id"],))
    before = db.one("SELECT * FROM attempts WHERE id=?", (attempt["id"],))
    assert client.post(f"/api/attempts/{attempt['id']}/rereview").status_code == 200
    stored = attempt_row(attempt["id"])
    after = db.one("SELECT * FROM attempts WHERE id=?", (attempt["id"],))
    assert after["audio_file"] == before["audio_file"] and after["transcript"] == before["transcript"]
    assert stored["note_state"] == "skipped" and statuses(stored)["writer"] == "done"
    assert len(review_messages(session["id"])) == 1
    history = client.get(f"/api/attempts/{attempt['id']}/analysis-history").json()
    assert history[0]["attempt"]["assessment"] == legacy
    review = db.one("SELECT * FROM reviews WHERE topic_id='hash-maps'")
    assert (review["interval_days"], review["repetitions"], review["due"]) == (3, 1, "2026-10-30")


def test_rereview_refused_while_processing(client, wav_bytes, fake_llm):
    attempt = upload(client, wav_bytes)
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
    attempt = upload(client, wav_bytes)
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
