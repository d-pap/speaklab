from pathlib import Path

from conftest import get_thread, next_day, upload
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
    first = upload(client, wav_bytes)
    sid = first["session_id"]
    assert first["status"] == "ready"
    assert first["acoustics"]["pitch_median_hz"] > 200
    assert first["audio_url"].endswith("/audio")
    assert "audio_file" not in first
    assert client.get(first["audio_url"]).content == wav_bytes
    assert client.post(f"/api/attempts/{first['id']}/note", json={"skip": True}).status_code == 200
    reply = client.post(f"/api/sessions/{sid}/chat", json={"message": "Explain collisions", "attempt_number": 1})
    assert reply.status_code == 200 and '"done": true' in reply.text
    kinds = [m["kind"] for m in get_thread(client)["messages"]]
    assert kinds == ["review", "chat", "chat"]
    same_day = client.post("/api/topics/hash-maps/attempts", files={"file": ("a.wav", wav_bytes)})
    assert same_day.status_code == 409
    next_day(sid)
    second = upload(client, wav_bytes)
    assert client.post(f"/api/attempts/{second['id']}/note", json={"skip": True}).status_code == 200
    assert db.one("SELECT interval_days FROM reviews WHERE topic_id='hash-maps'")["interval_days"] == 1  # 1/N: "again"
    assert db.one("SELECT completed_at FROM sessions WHERE id=?", (sid,))["completed_at"] is None  # no completion
    assert client.post(f"/api/sessions/{sid}/complete", json={"recall": "easy"}).status_code in (404, 405)
    db.initialize()
    assert len(get_thread(client)["attempts"]) == 2
    [row] = client.get("/api/history").json()
    assert row["coverage"]["correct"] == 1  # from the technical pass


def test_reference_material_is_gated_and_reviewed_attempt_cannot_be_replaced(client, wav_bytes):
    catalog = client.get("/api/topics").json()
    assert len(catalog) >= 16
    assert not any("concepts" in t or "core" in t for t in catalog)
    assert client.get("/api/topics/hash-maps/thread").json()["attempts"] == []  # nothing to reveal yet
    first = upload(client, wav_bytes)
    chat = client.post(
        f"/api/sessions/{first['session_id']}/chat", json={"message": "Reveal the answer", "attempt_number": 2}
    )
    assert chat.status_code == 409
    assert client.post("/api/topics/hash-maps/attempts", files={"file": ("test.wav", wav_bytes)}).status_code == 409
    assert [a["id"] for a in get_thread(client)["attempts"]] == [first["id"]]


def test_transcript_edit_invalidates_analysis_and_timing_but_preserves_audio(client, wav_bytes):
    first = upload(client, wav_bytes)
    aid = first["id"]
    assert (
        client.put(
            f"/api/attempts/{aid}/transcript", json={"text": "Um a hash map maps a key to a value."}
        ).status_code
        == 200
    )
    edited = get_thread(client)["attempts"][0]
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
    first = upload(client, wav_bytes)
    assert first["transcript"] is None
    monkeypatch.setattr(models, "transcribe", original)
    assert client.post(f"/api/attempts/{first['id']}/retry").status_code == 200
    updated = get_thread(client)["attempts"][0]
    assert updated["status"] == "ready"
    assert updated["errors"] == {}


def test_safe_upload_size_type_path_and_cleanup(client, wav_bytes, monkeypatch):
    path = "/api/topics/hash-maps/attempts"
    assert client.post(path, files={"file": ("a.wav", b"not audio", "audio/wav")}).status_code == 415
    assert client.post(path, files={"file": ("a.wav", b"RIFF0000WAVE" + b"bad" * 20)}).status_code == 422
    assert list((settings.data_dir / "recordings").iterdir()) == []
    monkeypatch.setattr(settings, "max_upload_bytes", 100)
    assert client.post(path, files={"file": ("a.wav", wav_bytes)}).status_code == 413
    assert list((settings.data_dir / "recordings").iterdir()) == []
    assert db.all_rows("SELECT id FROM sessions") == []  # a refused upload creates no thread
    monkeypatch.setattr(settings, "max_upload_bytes", 30 * 1024 * 1024)
    result = upload(client, wav_bytes)
    stored = db.one("SELECT audio_file FROM attempts WHERE id=?", (result["id"],))
    assert Path(stored["audio_file"]).parent == settings.data_dir / "recordings"
    assert "unsafe" not in stored["audio_file"]


def test_origin_and_client_header_protection(client, wav_bytes):
    path = "/api/topics/hash-maps/attempts"
    wav = {"file": ("a.wav", wav_bytes, "audio/wav")}
    assert client.post(path, headers={"Origin": "https://evil.example"}, files=wav).status_code == 403
    assert client.get("/api/topics", headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.post(path, headers={"X-SpeakLab-Client": ""}, files=wav).status_code == 403
    assert client.get("/api/topics", headers={"Host": "evil.example"}).status_code == 400
    assert client.post("/api/topics/missing/attempts", files=wav).status_code == 404
    assert client.post(path, files=wav, data={"duration": "999"}).status_code == 422
    assert db.all_rows("SELECT id FROM sessions") == []


def test_processing_retry_guard_and_restart_recovery(client, wav_bytes, monkeypatch):
    monkeypatch.setattr(pipeline, "submit", lambda _: None)
    first = upload(client, wav_bytes)
    assert first["status"] == "pending"
    assert client.post(f"/api/attempts/{first['id']}/retry").status_code == 409
    db.initialize()
    attempt = get_thread(client)["attempts"][0]
    assert attempt["status"] == "interrupted"
    assert "interrupted" in attempt["errors"]["processing"]


def test_sessions_with_retired_topic_or_prompt_kind_still_load(client, wav_bytes):
    # Saved sessions outlive catalog edits: a topic or prompt kind removed later must not break pages.
    with db.connect() as conn:
        for sid, topic in (("old", "retired-topic"), ("kind", "hash-maps")):
            conn.execute(
                "INSERT INTO sessions(id,topic_id,created_at,duration,style,prompt_kind,stage) "
                "VALUES(?,?,'2026-11-01T00:00:00+00:00',120,'Conversational','Build a solution','review1')",
                (sid, topic),
            )
            conn.execute(
                "INSERT INTO attempts(id,session_id,number,created_at,audio_file,wav_file,mime,duration) "
                "VALUES(?,?,1,'2026-11-01T00:00:00+00:00','a','w','audio/wav',3)",
                (sid + "-1", sid),
            )
    history = client.get("/api/history")
    assert history.status_code == 200
    retired = next(row for row in history.json() if row["session_id"] == "old")
    assert retired["topic"]["category"] == "Retired topic"
    thread = get_thread(client, "retired-topic")
    assert thread["attempts"][0]["prompt"] == "" and thread["attempts"][0]["prompt_kind"] == "Build a solution"
    detail = client.get("/api/sessions/old")
    assert detail.status_code == 200 and detail.json()["prompt"] == ""
    kept = get_thread(client)["attempts"][0]
    assert kept["prompt"] == get_thread(client)["topic"]["prompt"]
    assert client.get("/api/practice/ready").status_code == 200
    # A new attempt on that thread carries the retired kind over rather than refusing it.
    second = upload(client, wav_bytes)
    assert second["number"] == 2 and second["prompt_kind"] == "Build a solution"
