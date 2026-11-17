import json

import httpx
from conftest import get_thread, upload

from app import db, main, models


def ready(client, wav_bytes):
    attempt = upload(client, wav_bytes)
    client.post(f"/api/attempts/{attempt['id']}/note", json={"skip": True})
    return attempt


def test_model_change_regenerates_all_review_passes_and_preserves_chat_votes_and_schedule(
    client, wav_bytes, fake_llm, monkeypatch,
):
    attempt = ready(client, wav_bytes)
    old = get_thread(client)["messages"][0]
    original_model = old["model"]
    client.put(f"/api/messages/{old['id']}/feedback", json={"rating": 1})
    client.post(f"/api/sessions/{attempt['session_id']}/chat", json={
        "message": "Explain the collision mechanism.", "attempt_number": 1,
    })
    chat_before = db.all_rows("SELECT * FROM messages WHERE kind='chat'")
    schedule_before = db.all_rows("SELECT * FROM reviews")
    calls_before = len(fake_llm.requests)

    original_transport = fake_llm._handle

    def installed(request):
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "comparison-model:latest"}]})
        return original_transport(request)

    monkeypatch.setattr(models, "transport", httpx.MockTransport(installed))
    assert client.put("/api/settings/model", json={"model": "comparison-model:latest"}).status_code == 200
    assert client.post(f"/api/attempts/{attempt['id']}/rereview").status_code == 200
    new = next(m for m in get_thread(client)["messages"] if m["kind"] == "review")
    assert new["id"] != old["id"] and new["model"] == "comparison-model:latest"
    requests = fake_llm.requests[calls_before:]
    assert {"technical", "communication", "writer"} <= {r["pass"] for r in requests}
    assert all(r["body"]["model"] == "comparison-model:latest" for r in requests)
    assert db.all_rows("SELECT * FROM messages WHERE kind='chat'") == chat_before
    assert db.all_rows("SELECT * FROM reviews") == schedule_before
    saved = db.one("SELECT * FROM attempts WHERE id=?", (attempt["id"],))
    assert saved["transcript"] == attempt["transcript"] and saved["audio_file"]
    snapshot = client.get(f"/api/attempts/{attempt['id']}/analysis-history").json()[0]["attempt"]
    assert snapshot["analysis"]["passes"]["writer"]["model"] == original_model
    assert snapshot["review_message"] == old["content"] and snapshot["review_parts"]
    rating = client.get("/api/feedback/export").json()["records"][0]
    assert rating["snapshot"]["message"]["id"] == old["id"]
    assert rating["message_id"] is None and rating["rating"] == 1

    client.post(f"/api/sessions/{attempt['session_id']}/chat", json={"message": "Give an example.", "attempt_number": 1})
    assert fake_llm.requests_for("chat")[-1]["body"]["model"] == "comparison-model:latest"


def test_regeneration_waits_for_active_reply_without_archiving_or_erasing(client, wav_bytes):
    attempt = ready(client, wav_bytes)
    before = db.one("SELECT * FROM attempts WHERE id=?", (attempt["id"],))
    messages = db.all_rows("SELECT * FROM messages")
    with main.tutor_lock:
        result = client.post(f"/api/attempts/{attempt['id']}/rereview")
        assert result.status_code == 409 and "finish answering" in result.json()["detail"]
    assert db.one("SELECT * FROM attempts WHERE id=?", (attempt["id"],)) == before
    assert db.all_rows("SELECT * FROM messages") == messages
    assert not db.all_rows("SELECT * FROM analysis_history")
    assert client.post(f"/api/attempts/{attempt['id']}/rereview").status_code == 200


def test_archived_review_parts_resolve_against_archived_lines(client, wav_bytes):
    attempt = ready(client, wav_bytes)
    client.post(f"/api/attempts/{attempt['id']}/rereview")
    db.execute("UPDATE attempts SET lines=? WHERE id=?", (json.dumps([
        {"id": "L1", "text": "Changed after the archive", "start": 99, "end": 100},
    ]), attempt["id"]))
    snapshot = client.get(f"/api/attempts/{attempt['id']}/analysis-history").json()[0]["attempt"]
    ref = next(p for p in snapshot["review_parts"] if p["type"] == "ref")
    assert ref["start"] != 99
