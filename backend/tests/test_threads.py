"""Topic threads: one ongoing practice thread per topic, attempts on later days."""

import json
from datetime import date, timedelta
from pathlib import Path

from conftest import MINIMAL_CHAT_REPLY, TRANSCRIPT, get_thread, minimal_replies, next_day, upload

from app import db, main, models, threads
from app.config import settings
from app.curriculum import TOPICS

SHORT = ("Um, testing.", [{"start": 0, "end": 1, "text": "Um, testing."}])
FULL = (TRANSCRIPT, [{"start": 0, "end": 2.6, "text": TRANSCRIPT}])
TOMORROW = (date.today() + timedelta(days=1)).isoformat()


def reviewed(client, wav_bytes, topic_id="hash-maps", **form):
    attempt = upload(client, wav_bytes, topic_id, **form)
    response = client.post(f"/api/attempts/{attempt['id']}/note", json={"skip": True})
    assert response.status_code == 200, response.text
    return attempt


def days_ahead(monkeypatch, days):
    monkeypatch.setattr(threads, "today", lambda: date.today() + timedelta(days=days))


def writer_scoring(overall):
    """A writer reply whose structure scores Overall at `overall`; the message falls to the default."""

    def reply(record):
        result = minimal_replies()["writer"](record)
        result["scores"][0]["score"] = overall
        for change in (result["comparison"] or {}).get("changes", []):
            if change["name"] == "Overall":
                change["after"] = overall
        return result

    return reply


def test_picking_a_topic_creates_nothing(client):
    thread = get_thread(client, "hash-maps")
    assert thread["topic"]["id"] == "hash-maps"
    assert "study_reference" not in thread
    assert thread["session_id"] is None and thread["attempts"] == [] and thread["messages"] == []
    assert thread["recording"] == {"can_record": True, "reason": None, "replace_number": None, "next_number": 1}
    assert thread["latest_checklist"] == [] and thread["next_attempt_after"] is None
    # The question for each type, so the recording screen can show the chosen angle before any upload.
    hash_maps = next(t for t in TOPICS if t["id"] == "hash-maps")
    assert thread["prompts"]["Concept explanation"] == hash_maps["prompt"]
    assert thread["prompts"]["Compare"] == hash_maps["compare"]
    assert len(thread["prompts"]) == 6
    assert db.all_rows("SELECT * FROM sessions") == []
    assert client.get("/api/history").json() == []
    assert client.get("/api/topics/missing/thread").status_code == 404
    # The old session creation and stage machine are gone.
    assert client.post("/api/sessions", json={"topic_id": "hash-maps"}).status_code in (404, 405)
    assert client.put("/api/sessions/x/stage", json={"stage": "record2"}).status_code in (404, 405)
    assert client.get("/api/attempt2").status_code in (404, 405)


def test_first_upload_creates_thread_and_attempt_1(client, wav_bytes):
    path = "/api/topics/hash-maps/attempts"
    wav = {"file": ("a.wav", wav_bytes, "audio/wav")}
    assert client.post(path, files=wav, data={"duration": "999"}).status_code == 422
    assert client.post(path, files=wav, data={"prompt_kind": "Build a solution"}).status_code == 422
    assert client.post(path, files=wav, data={"style": "Shouting"}).status_code == 422
    assert client.post("/api/topics/missing/attempts", files=wav).status_code == 404
    assert db.all_rows("SELECT * FROM sessions") == []
    attempt = upload(client, wav_bytes, prompt_kind="Compare", style="Thoughtful teacher", duration=180)
    assert attempt["number"] == 1 and attempt["status"] == "ready"
    assert attempt["prompt_kind"] == "Compare" and attempt["style"] == "Thoughtful teacher"
    assert attempt["target_duration"] == 180 and attempt["duration"] == 2.6  # recorded length is separate
    [session] = db.all_rows("SELECT * FROM sessions")
    assert session["id"] == attempt["session_id"] and session["topic_id"] == "hash-maps"
    assert session["prompt_kind"] == "Compare" and session["completed_at"] is None
    thread = get_thread(client)
    assert thread["study_reference"]["example"]
    assert thread["study_reference"]["sources"]
    assert thread["session_id"] == session["id"]
    [stored] = thread["attempts"]
    assert stored["id"] == attempt["id"] and stored["target_duration"] == 180
    assert stored["prompt"] != thread["topic"]["prompt"]  # the Compare question, not the default one
    assert thread["recording"] == {
        "can_record": False,
        "reason": "Next attempt opens tomorrow",
        "replace_number": None,
        "next_number": 2,
    }
    assert thread["next_attempt_after"] == TOMORROW
    # The old session view still loads, with its topic, so old links can redirect.
    old = client.get(f"/api/sessions/{session['id']}").json()
    assert old["topic_id"] == "hash-maps" and len(old["attempts"]) == 1


def test_same_day_new_attempt_refused_next_day_allowed(client, wav_bytes, monkeypatch):
    first = reviewed(client, wav_bytes)
    recordings = settings.data_dir / "recordings"
    files_before = sorted(recordings.iterdir())
    response = client.post(
        "/api/topics/hash-maps/attempts", files={"file": ("a.wav", wav_bytes, "audio/wav")}
    )
    assert response.status_code == 409 and response.json()["detail"] == "Next attempt opens tomorrow"
    assert sorted(recordings.iterdir()) == files_before  # nothing left behind
    days_ahead(monkeypatch, 1)
    assert get_thread(client)["recording"]["can_record"] is True
    second = upload(client, wav_bytes)
    assert second["number"] == 2 and second["session_id"] == first["session_id"]
    assert second["prompt_kind"] == "Concept explanation"  # inherited from attempt 1
    assert len(db.all_rows("SELECT * FROM sessions")) == 1
    days_ahead(monkeypatch, 0)
    assert get_thread(client)["recording"]["reason"] == "Next attempt opens tomorrow"


def test_next_attempt_date_uses_the_local_date_of_the_latest_attempt(client, wav_bytes):
    attempt = upload(client, wav_bytes)
    from datetime import datetime

    local_day = datetime.fromisoformat(attempt["created_at"]).astimezone().date()
    assert threads.next_attempt_after(attempt["session_id"]) == (local_day + timedelta(days=1)).isoformat()


def test_too_short_latest_attempt_can_be_replaced_same_day(client, wav_bytes, monkeypatch):
    monkeypatch.setattr(models, "transcribe", lambda *a: SHORT)
    short = upload(client, wav_bytes, prompt_kind="Trade-off")
    assert short["analysis"]["review"] == {"too_short": True}
    sid = short["session_id"]
    assert get_thread(client)["recording"] == {
        "can_record": True,
        "reason": None,
        "replace_number": 1,
        "next_number": 1,
    }
    # Not while it is processing.
    db.execute("UPDATE attempts SET status='processing' WHERE id=?", (short["id"],))
    assert get_thread(client)["recording"]["can_record"] is False
    db.execute("UPDATE attempts SET status='ready' WHERE id=?", (short["id"],))
    old_audio = db.one("SELECT audio_file, wav_file FROM attempts WHERE id=?", (short["id"],))
    monkeypatch.setattr(models, "transcribe", lambda *a: FULL)
    again = upload(client, wav_bytes)
    assert again["number"] == 1 and again["id"] != short["id"] and again["session_id"] == sid
    assert again["prompt_kind"] == "Trade-off"
    assert db.one("SELECT id FROM attempts WHERE id=?", (short["id"],)) is None
    assert not Path(old_audio["audio_file"]).exists() and not Path(old_audio["wav_file"]).exists()
    assert get_thread(client)["recording"]["reason"] == "Next attempt opens tomorrow"
    # Only the latest attempt is replaced: a too-short attempt 2 leaves attempt 1 alone.
    client.post(f"/api/attempts/{again['id']}/note", json={"skip": True})
    next_day(sid)
    monkeypatch.setattr(models, "transcribe", lambda *a: SHORT)
    short2 = upload(client, wav_bytes)
    assert short2["number"] == 2
    monkeypatch.setattr(models, "transcribe", lambda *a: FULL)
    replaced = upload(client, wav_bytes)
    assert replaced["number"] == 2 and replaced["id"] != short2["id"]
    assert [a["id"] for a in get_thread(client)["attempts"]] == [again["id"], replaced["id"]]


def test_attempt_3_gets_review_comparing_with_attempt_2(client, wav_bytes, fake_llm):
    first = reviewed(client, wav_bytes)
    sid = first["session_id"]
    next_day(sid)
    fake_llm.queue("writer", writer_scoring(7.0))
    second = reviewed(client, wav_bytes)
    second_structure = fake_llm.requests_for("writer")[-2]
    assert second_structure["payload"]["previous_attempt_scores"][0] == {"name": "Overall", "score": 5.0}
    assert "question_change" not in second_structure["payload"]
    next_day(sid)
    third = reviewed(client, wav_bytes, prompt_kind="Trade-off")
    assert third["number"] == 3
    structure, message = fake_llm.requests_for("writer")[-2:]
    assert structure["payload"]["previous_attempt_scores"][0] == {"name": "Overall", "score": 7.0}
    change = structure["payload"]["question_change"]
    hash_maps = next(t for t in TOPICS if t["id"] == "hash-maps")
    assert change["previous_question"] == hash_maps["prompt"]
    assert "trade" not in change["previous_question"].lower() and "benefit, a cost" in change["question"]
    assert message["payload"]["question_change"] == change
    # Plain data: the two questions only. The instruction lives in the system prompts.
    assert change == {"previous_question": hash_maps["prompt"], "question": change["question"]}
    assert "question_change" in structure["messages"][0]["content"]
    assert "question_change" in message["messages"][0]["content"]
    stored = db.one("SELECT analysis FROM attempts WHERE id=?", (third["id"],))
    comparison = json.loads(stored["analysis"])["review"]["comparison"]
    assert comparison["changes"][0] == {"name": "Overall", "before": 7.0, "after": 5.0}
    kinds = [(m["attempt_number"], m["kind"]) for m in get_thread(client)["messages"]]
    assert kinds == [(1, "review"), (2, "review"), (3, "review")]
    assert second["id"] != third["id"]


def test_chat_and_note_work_for_attempt_3(client, wav_bytes, fake_llm):
    first = reviewed(client, wav_bytes)
    sid = first["session_id"]
    next_day(sid)
    reviewed(client, wav_bytes)
    next_day(sid)
    third = upload(client, wav_bytes, prompt_kind="Trade-off")
    assert third["note_state"] == "pending"
    note = client.post(f"/api/attempts/{third['id']}/note", json={"text": "Better this time."})
    assert note.status_code == 200 and note.json()["learner_note"] == "Better this time."
    chat = client.post(f"/api/sessions/{sid}/chat", json={"message": "How was it?", "attempt_number": 3})
    assert chat.status_code == 200 and '"done": true' in chat.text
    context = fake_llm.requests_for("chat")[-1]["messages"][1]["content"]
    assert "attempt 3" in context and "benefit, a cost" in context
    missing = client.post(f"/api/sessions/{sid}/chat", json={"message": "Hi", "attempt_number": 4})
    assert missing.status_code == 409 and "attempt 4" in missing.json()["detail"].lower()
    assert client.post(f"/api/sessions/{sid}/chat", json={"message": "Hi", "attempt_number": 0}).status_code == 422
    thread = get_thread(client)
    assert [(m["attempt_number"], m["kind"]) for m in thread["messages"] if m["attempt_number"] == 3] == [
        (3, "review"),
        (3, "chat"),
        (3, "chat"),
    ]
    assert thread["messages"][-1]["content"] == MINIMAL_CHAT_REPLY
    assert thread["latest_checklist"] == ["Open with a one-sentence definition.", "Close with a summary."]


def test_history_lists_topics_with_recordings_only(client, wav_bytes):
    # An empty session left by an old topic click is never listed.
    db.execute(
        "INSERT INTO sessions(id,topic_id,created_at,duration,style,prompt_kind) "
        "VALUES('empty','caching','2026-11-01T00:00:00+00:00',120,'Conversational','Concept explanation')"
    )
    first = reviewed(client, wav_bytes)
    next_day(first["session_id"])
    reviewed(client, wav_bytes)
    rest = reviewed(client, wav_bytes, "rest-apis")
    next_day(rest["session_id"], 3)
    rows = client.get("/api/history").json()
    assert [r["topic"]["id"] for r in rows] == ["hash-maps", "rest-apis"]  # most recent first
    hash_maps, rest_apis = rows
    assert hash_maps["topic_id"] == "hash-maps" and hash_maps["session_id"] == first["session_id"]
    assert hash_maps["attempt_count"] == 2 and hash_maps["can_record"] is False
    assert hash_maps["last_attempt_at"] > rest_apis["last_attempt_at"]
    assert hash_maps["coverage"]["attempt"] == 2 and hash_maps["coverage"]["correct"] == 1
    assert hash_maps["coverage"]["total"] == len(next(t for t in TOPICS if t["id"] == "hash-maps")["concepts"])
    assert rest_apis["attempt_count"] == 1 and rest_apis["can_record"] is True


def test_ready_lists_open_topics_due_first(client, wav_bytes):
    hash_maps = reviewed(client, wav_bytes)
    next_day(hash_maps["session_id"], 1)
    caching = reviewed(client, wav_bytes, "caching")
    next_day(caching["session_id"], 3)
    rest = reviewed(client, wav_bytes, "rest-apis")
    next_day(rest["session_id"], 5)
    reviewed(client, wav_bytes, "auth")  # today: not open yet
    today = date.today().isoformat()
    db.execute("UPDATE reviews SET due='2099-01-01'")
    db.execute("UPDATE reviews SET due=? WHERE topic_id='caching'", (today,))
    rows = client.get("/api/practice/ready").json()
    assert [(r["topic"]["id"], r["due"]) for r in rows] == [
        ("caching", True),
        ("rest-apis", False),  # then the oldest last attempt
        ("hash-maps", False),
    ]
    assert rows[0]["session_id"] == caching["session_id"] and rows[0]["attempt_count"] == 1
    assert rows[0]["review_due"] == today


def test_recommend_excludes_practised_unless_included(client, monkeypatch):
    unpractised = TOPICS[-1]["id"]
    with db.connect() as conn:
        for topic in TOPICS[:-1]:
            sid = "thread-" + topic["id"]
            conn.execute(
                "INSERT INTO sessions(id,topic_id,created_at,duration,style,prompt_kind) "
                "VALUES(?,?,'2026-11-01T00:00:00+00:00',120,'Conversational','Concept explanation')",
                (sid, topic["id"]),
            )
            conn.execute(
                "INSERT INTO attempts(id,session_id,number,created_at,audio_file,wav_file,mime,duration) "
                "VALUES(?,?,1,'2026-11-01T00:00:00+00:00','a','w','audio/wav',3)",
                ("a-" + topic["id"], sid),
            )
    for _ in range(10):
        response = client.get("/api/topics/recommend", params={"include_practised": "false"})
        assert response.json()["topic"]["id"] == unpractised and response.json()["practised"] is False
    assert client.get("/api/topics/recommend").json()["topic"]["id"] == unpractised  # the default
    seen = []

    def spy(candidates, reviews, weak):
        seen.extend(c["id"] for c in candidates)
        return candidates[0]

    monkeypatch.setattr(main, "recommend", spy)
    included = client.get("/api/topics/recommend", params={"include_practised": "true"}).json()
    assert len(seen) == len(TOPICS) and included["practised"] is True
    # Every topic in this category is practised: no new suggestion, and no practised fallback.
    category = next(t["category"] for t in TOPICS if t["category"] != TOPICS[-1]["category"])
    assert client.get("/api/topics/recommend", params={"category": category}).status_code == 404


def test_each_reviewed_attempt_reschedules_spaced_review(client, wav_bytes, monkeypatch, fake_llm):
    first = reviewed(client, wav_bytes)
    sid = first["session_id"]
    review = db.one("SELECT * FROM reviews WHERE topic_id='hash-maps'")
    assert review["interval_days"] == 1 and review["due"] == TOMORROW  # 1 of N concepts: "again"
    # Retry, transcript edit and rereview don't schedule the same attempt again.
    db.execute("UPDATE reviews SET due='2099-01-01'")
    assert client.post(f"/api/attempts/{first['id']}/rereview").status_code == 200
    assert db.one("SELECT due FROM reviews WHERE topic_id='hash-maps'")["due"] == "2099-01-01"
    # A too-short attempt doesn't reschedule.
    next_day(sid)
    monkeypatch.setattr(models, "transcribe", lambda *a: SHORT)
    upload(client, wav_bytes)
    assert db.one("SELECT due FROM reviews WHERE topic_id='hash-maps'")["due"] == "2099-01-01"
    # Its replacement, with every concept right, does.
    monkeypatch.setattr(models, "transcribe", lambda *a: FULL)

    def all_correct(record):
        result = minimal_replies()["technical"](record)
        first_line = list(record["payload"]["transcript_lines"])[:1]
        for concept in result.get("concepts", []):
            concept.update(status="correct", line_ids=first_line)
        return result

    fake_llm.queue("technical", all_correct)
    second = reviewed(client, wav_bytes)
    assert second["number"] == 2
    stored = json.loads(db.one("SELECT analysis FROM attempts WHERE id=?", (second["id"],))["analysis"])
    assert {c["status"] for c in stored["technical"]["concepts"]} == {"correct"}
    review = db.one("SELECT * FROM reviews WHERE topic_id='hash-maps'")
    assert review["interval_days"] == 3 and review["repetitions"] == 1  # "good" after interval 1
    assert review["last_session_id"] == sid
    assert db.one("SELECT completed_at FROM sessions WHERE id=?", (sid,))["completed_at"] is None


def test_host_shaped_completed_thread_stays_writable(client, wav_bytes):
    """Threads migrated from completed sessions keep completed_at; it no longer gates anything."""
    first = reviewed(client, wav_bytes)
    sid = first["session_id"]
    db.execute(
        "UPDATE sessions SET completed_at='2026-10-27T12:00:00+00:00', stage='review2', review_due='2026-10-30' "
        "WHERE id=?",
        (sid,),
    )
    edit = client.put(
        f"/api/attempts/{first['id']}/transcript",
        json={"text": "A hash map stores each key with its value and hashes the key to choose a bucket."},
    )
    assert edit.status_code == 200
    next_day(sid)
    second = upload(client, wav_bytes)
    assert second["number"] == 2
    assert client.post(f"/api/attempts/{second['id']}/note", json={"skip": True}).status_code == 200


def test_rereview_of_a_too_short_attempt_does_not_block_its_later_schedule(client, wav_bytes, monkeypatch):
    monkeypatch.setattr(models, "transcribe", lambda *a: SHORT)
    short = upload(client, wav_bytes)
    assert client.post(f"/api/attempts/{short['id']}/rereview").status_code == 200
    assert db.one("SELECT scheduled_at FROM attempts WHERE id=?", (short["id"],))["scheduled_at"] is None
    text = "A hash map stores each key with its value and hashes the key to choose one bucket in an array."
    assert client.put(f"/api/attempts/{short['id']}/transcript", json={"text": text}).status_code == 200
    client.post(f"/api/attempts/{short['id']}/note", json={"skip": True})
    assert db.one("SELECT * FROM reviews WHERE topic_id='hash-maps'") is not None


def test_latest_checklist_falls_back_to_legacy_next_steps(client, wav_bytes):
    first = reviewed(client, wav_bytes)
    sid = first["session_id"]
    steps = [f"Legacy step {n}." for n in range(1, 8)]
    # A legacy attempt 2: only the old assessment, no new review structure.
    db.execute(
        "INSERT INTO attempts(id,session_id,number,created_at,audio_file,wav_file,mime,duration,assessment,note_state) "
        "VALUES('legacy2',?,2,?,'a','w','audio/wav',3,?,'legacy')",
        (sid, db.now(), json.dumps({"summary": "Old.", "concepts": [], "next_steps": steps})),
    )
    assert get_thread(client)["latest_checklist"] == steps[:5]
    # A new review on the latest attempt wins over the legacy steps.
    db.execute("DELETE FROM attempts WHERE id='legacy2'")
    assert get_thread(client)["latest_checklist"] == ["Open with a one-sentence definition.", "Close with a summary."]
