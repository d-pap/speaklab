import json

import pytest
from conftest import get_thread, upload

from app import db


def reviewed(client, wav_bytes):
    attempt = upload(client, wav_bytes)
    assert client.post(f"/api/attempts/{attempt['id']}/note", json={"skip": True}).status_code == 200
    return attempt, get_thread(client)["messages"][0]


def vote(client, message, **values):
    return client.put(f"/api/messages/{message['id']}/feedback", json={"rating": -1, **values})


def exported(client):
    response = client.get("/api/feedback/export")
    assert response.status_code == 200
    assert response.headers["content-disposition"].startswith("attachment;")
    return response.json()["records"]


def test_vote_snapshots_exact_writer_context_and_can_change_or_remove(client, wav_bytes, fake_llm):
    attempt, message = reviewed(client, wav_bytes)
    original_calls = len(fake_llm.requests)
    response = vote(client, message, reason="missed_insight", comment=" Missed a pattern ", preferred_response=" Better ")
    assert response.status_code == 200
    saved = response.json()["feedback"]
    assert saved["comment"] == "Missed a pattern"
    assert get_thread(client)["messages"][0]["feedback"] == saved
    record = exported(client)[0]
    snapshot = record["snapshot"]
    assert snapshot["context_status"] == "captured_at_generation"
    assert snapshot["generation"]["transcript"] == attempt["transcript"]
    request = snapshot["generation"]["calls"][0]["request"]
    writer = [r for r in fake_llm.requests_for("writer") if "format" not in r["body"]][-1]
    assert request == writer["body"]
    assert "generation_context" not in message
    assert "generation_context" not in get_thread(client)["messages"][0]
    assert vote(client, message, rating=1).status_code == 200
    assert exported(client)[0]["snapshot"] == snapshot
    assert len(exported(client)) == 1
    assert vote(client, message, rating=None).json() == {"feedback": None}
    assert exported(client) == []
    assert len(fake_llm.requests) == original_calls  # rating never calls a model


def test_rereview_and_transcript_edits_preserve_rated_response(client, wav_bytes):
    attempt, message = reviewed(client, wav_bytes)
    assert vote(client, message).status_code == 200
    snapshot = exported(client)[0]["snapshot"]
    assert client.post(f"/api/attempts/{attempt['id']}/rereview").status_code == 200
    assert exported(client)[0]["message_id"] is None
    assert exported(client)[0]["snapshot"] == snapshot
    current = get_thread(client)["messages"][0]
    assert current["id"] != message["id"] and current["feedback"] is None
    assert vote(client, message).status_code == 404
    assert client.put(f"/api/attempts/{attempt['id']}/transcript", json={
        "text": "This is a different explanation of hash maps and key comparisons with buckets and collisions."
    }).status_code == 200
    assert exported(client)[0]["snapshot"] == snapshot


def test_learning_reply_keeps_actual_request_and_original_transcript(client, wav_bytes, fake_llm):
    attempt, _ = reviewed(client, wav_bytes)
    response = client.post(f"/api/sessions/{attempt['session_id']}/chat", json={
        "message": "Explain collisions", "attempt_number": 1,
    })
    event = json.loads([s[6:] for s in response.text.splitlines() if s.startswith("data: ")][-1])
    message = event["message"]
    assert "generation_context" not in message
    # Edit the source before voting: the reply must retain its generation-time input.
    db.execute("UPDATE attempts SET transcript='Changed later', lines='[]' WHERE id=?", (attempt["id"],))
    assert vote(client, message, rating=1).status_code == 200
    generation = exported(client)[0]["snapshot"]["generation"]
    assert generation["transcript"] == attempt["transcript"]
    call = generation["calls"][0]
    assert call["request"] == fake_llm.requests_for("chat")[-1]["body"]
    assert call["request"]["messages"][-1] == {"role": "user", "content": "Explain collisions"}
    assert call["truncated"] is False
    user = db.one("SELECT * FROM messages WHERE role='user'")
    assert vote(client, user).status_code == 422


def test_older_response_context_is_explicitly_missing(client, wav_bytes):
    _, message = reviewed(client, wav_bytes)
    db.execute("UPDATE messages SET generation_context=NULL,model=NULL WHERE id=?", (message["id"],))
    assert vote(client, message).status_code == 200
    snapshot = exported(client)[0]["snapshot"]
    assert snapshot["generation"] is None
    assert snapshot["context_status"] == "unavailable_for_older_response"


@pytest.mark.parametrize("body", [
    {"rating": 0}, {"rating": 1, "reason": "made-up"}, {"rating": 1, "comment": "a" * 4001},
    {"rating": -1, "preferred_response": "a" * 20001}, {"rating": 1, "train": True},
])
def test_invalid_feedback_is_rejected(client, wav_bytes, body):
    _, message = reviewed(client, wav_bytes)
    assert client.put(f"/api/messages/{message['id']}/feedback", json=body).status_code == 422
    assert exported(client) == []


def test_feedback_migration_and_restart_keep_snapshot(client, wav_bytes):
    _, message = reviewed(client, wav_bytes)
    vote(client, message)
    original = exported(client)
    # A v5 database has no feedback; rerunning the upgrade must also preserve existing v6 data.
    db.execute("PRAGMA user_version=5")
    db.initialize()
    db.initialize()
    assert exported(client) == original
    with db.connect() as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 6
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
