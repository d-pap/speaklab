from pathlib import Path

from conftest import create, open_attempt2, upload
from fastapi.testclient import TestClient

from app import db, models, pipeline
from app.config import settings


def test_built_frontend_shares_api_port_without_exposing_source(tmp_path, monkeypatch):
    from app import main

    dist = tmp_path / "frontend" / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("<html>SpeakLab production build</html>")
    (tmp_path / ".env").write_text("PRIVATE=not-for-browser")
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    monkeypatch.setattr(settings, "serve_frontend", True)
    monkeypatch.setattr(main, "ROOT", tmp_path)
    with TestClient(main.app) as browser:
        assert "SpeakLab production build" in browser.get("/").text
        assert browser.get("/api/topics").json()[0]["id"]
        assert browser.get("/.env").status_code == 404
        assert browser.get("/backend/app/config.py").status_code == 404
        assert browser.get("/", headers={"Origin": "http://untrusted.example"}).status_code == 403


def test_complete_practice_loop_persistence_and_idempotent_review(client, wav_bytes):
    session = create(client)
    sid = session["id"]
    first = upload(client, session, wav_bytes)
    assert first["status"] == "ready"
    assert first["acoustics"]["pitch_median_hz"] > 200
    assert first["audio_url"].endswith("/audio")
    assert "audio_file" not in first
    assert client.get(first["audio_url"]).content == wav_bytes
    assert client.post(f"/api/attempts/{first['id']}/note", json={"skip": True}).status_code == 200
    reply = client.post(f"/api/sessions/{sid}/chat", json={"message": "Explain collisions", "attempt_number": 1})
    assert reply.status_code == 200 and '"done": true' in reply.text
    kinds = [m["kind"] for m in client.get(f"/api/sessions/{sid}").json()["messages"]]
    assert kinds == ["review", "chat", "chat"]
    assert client.put(f"/api/sessions/{sid}/stage", json={"stage": "record2"}).status_code == 409  # same day
    open_attempt2(client, session)
    second = upload(client, session, wav_bytes, 2)
    assert client.get(f"/api/sessions/{sid}").json()["completed_at"] is None  # review still to come
    assert client.post(f"/api/attempts/{second['id']}/note", json={"skip": True}).status_code == 200
    completed = client.get(f"/api/sessions/{sid}").json()
    assert completed["completed_at"] and completed["review_due"] and completed["recall"] == "again"
    assert client.get("/api/reviews").json()[0]["interval_days"] == 1  # mastery 1/N, so "again"
    assert client.post(f"/api/sessions/{sid}/complete", json={"recall": "easy"}).status_code in (404, 405)
    db.initialize()
    assert len(client.get(f"/api/sessions/{sid}").json()["attempts"]) == 2
    assert client.get("/api/sessions").json()[0]["coverage"][0]["correct"] == 1  # from the technical pass


def test_reference_material_is_gated_and_cold_attempt_cannot_be_replaced(client, wav_bytes):
    session = create(client)
    sid = session["id"]
    catalog = client.get("/api/topics").json()
    assert len(catalog) >= 16
    assert not any("concepts" in t or "core" in t for t in catalog)
    chat = client.post(f"/api/sessions/{sid}/chat", json={"message": "Reveal the answer", "attempt_number": 1})
    assert chat.status_code == 409
    assert client.put(f"/api/sessions/{sid}/stage", json={"stage": "record2"}).status_code == 409
    upload(client, session, wav_bytes)
    assert client.put(f"/api/sessions/{sid}/stage", json={"stage": "record1"}).status_code == 409
    assert (
        client.post(f"/api/sessions/{sid}/attempts/1", files={"file": ("test.wav", wav_bytes)}).status_code
        == 409
    )


def test_transcript_edit_invalidates_analysis_and_timing_but_preserves_audio(client, wav_bytes):
    session = create(client)
    first = upload(client, session, wav_bytes)
    aid = first["id"]
    assert (
        client.put(
            f"/api/attempts/{aid}/transcript", json={"text": "Um a hash map maps a key to a value."}
        ).status_code
        == 200
    )
    edited = client.get(f"/api/sessions/{session['id']}").json()["attempts"][0]
    assert edited["transcript_source"] == "manual"
    assert edited["segments"] == []
    assert edited["acoustics"]["rate_track"] == []
    assert edited["acoustics"]["filler_count"] == 1
    assert [line["start"] for line in edited["lines"]] == [None]
    assert edited["lines"][0]["text"] == edited["transcript"]
    assert edited["analysis"]["review"] == {"too_short": True}  # 10 words: no scores
    assert client.get(edited["audio_url"]).content == wav_bytes
    assert client.put(f"/api/attempts/{aid}/transcript", json={"text": "   "}).status_code == 422


def test_retry_recovers_failed_transcription(client, wav_bytes, monkeypatch):
    original = models.transcribe

    def unavailable(*args):
        raise models.ServiceUnavailable("Offline test")

    monkeypatch.setattr(models, "transcribe", unavailable)
    session = create(client)
    first = upload(client, session, wav_bytes)
    assert first["transcript"] is None
    monkeypatch.setattr(models, "transcribe", original)
    assert client.post(f"/api/attempts/{first['id']}/retry").status_code == 200
    updated = client.get(f"/api/sessions/{session['id']}").json()["attempts"][0]
    assert updated["status"] == "ready"
    assert updated["errors"] == {}


def test_safe_upload_size_type_path_and_cleanup(client, wav_bytes, monkeypatch):
    session = create(client)
    path = f"/api/sessions/{session['id']}/attempts/1"
    assert client.post(path, files={"file": ("a.wav", b"not audio", "audio/wav")}).status_code == 415
    assert client.post(path, files={"file": ("a.wav", b"RIFF0000WAVE" + b"bad" * 20)}).status_code == 422
    assert list((settings.data_dir / "recordings").iterdir()) == []
    monkeypatch.setattr(settings, "max_upload_bytes", 100)
    assert client.post(path, files={"file": ("a.wav", wav_bytes)}).status_code == 413
    assert list((settings.data_dir / "recordings").iterdir()) == []
    monkeypatch.setattr(settings, "max_upload_bytes", 30 * 1024 * 1024)
    result = upload(client, session, wav_bytes)
    stored = db.one("SELECT audio_file FROM attempts WHERE id=?", (result["id"],))
    assert Path(stored["audio_file"]).parent == settings.data_dir / "recordings"
    assert "unsafe" not in stored["audio_file"]


def test_origin_and_client_header_protection(client):
    assert (
        client.post(
            "/api/sessions", headers={"Origin": "https://evil.example"}, json={"topic_id": "hash-maps"}
        ).status_code
        == 403
    )
    assert client.get("/api/topics", headers={"Origin": "https://evil.example"}).status_code == 403
    assert (
        client.post(
            "/api/sessions", headers={"X-SpeakLab-Client": ""}, json={"topic_id": "hash-maps"}
        ).status_code
        == 403
    )
    assert client.get("/api/topics", headers={"Host": "evil.example"}).status_code == 400
    assert client.post("/api/sessions", json={"topic_id": "missing"}).status_code == 404
    assert client.post("/api/sessions", json={"topic_id": "hash-maps", "duration": 999}).status_code == 422


def test_processing_retry_guard_and_restart_recovery(client, wav_bytes, monkeypatch):
    monkeypatch.setattr(pipeline, "submit", lambda _: None)
    session = create(client)
    first = upload(client, session, wav_bytes)
    assert first["status"] == "pending"
    assert client.post(f"/api/attempts/{first['id']}/retry").status_code == 409
    db.initialize()
    attempt = client.get(f"/api/sessions/{session['id']}").json()["attempts"][0]
    assert attempt["status"] == "interrupted"
    assert "interrupted" in attempt["errors"]["processing"]
