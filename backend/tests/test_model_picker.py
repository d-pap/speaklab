import json

import httpx
import pytest
from conftest import create, upload
from fastapi.testclient import TestClient

from app import db, main, models
from app.config import settings
from app.schemas import TutorReply


def ollama(monkeypatch, *, offline=False):
    calls = []
    names = ["qwen3.5:9b-q4_K_M", "gemma4:e4b", "remote-alias:latest", "embed:latest", "test:cloud"]

    def respond(request):
        calls.append(request)
        if offline:
            raise httpx.ConnectError("Explicitly offline test", request=request)
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": n, "size": 6000000000} for n in names]})
        body = json.loads(request.content)
        if request.url.path == "/api/show":
            info = {"capabilities": ["completion"], "details": {"parameter_size": "9B"}}
            if body["model"] == "remote-alias:latest":
                info["remote_host"] = "https://cloud.invalid"
            if body["model"] == "embed:latest":
                info["capabilities"] = ["embedding"]
            return httpx.Response(200, json=info)
        assert request.url.path == "/api/chat"
        return httpx.Response(
            200,
            json={
                "message": {"content": json.dumps({"answer": "Explicit test reply", "check_question": ""})}
            },
        )

    monkeypatch.setattr(models, "client", lambda *args: httpx.Client(transport=httpx.MockTransport(respond)))
    return calls


def test_picker_lists_installed_models_and_disables_remote_and_embedding_models(client, monkeypatch):
    calls = ollama(monkeypatch)
    response = client.get("/api/models")
    assert response.status_code == 200
    rows = {m["name"]: m for m in response.json()["models"]}
    assert rows["gemma4:e4b"]["selectable"]
    assert not any(rows[n]["selectable"] for n in ("remote-alias:latest", "embed:latest", "test:cloud"))
    assert all(r.url.host == "127.0.0.1" and r.url.path in ("/api/tags", "/api/show") for r in calls)


def test_selection_survives_restart_drives_inference_and_preserves_previous_analysis(
    client, monkeypatch, wav_bytes
):
    attempt = upload(client, create(client), wav_bytes)
    before = db.one("SELECT * FROM attempts WHERE id=?", (attempt["id"],))
    calls = ollama(monkeypatch)
    response = client.put("/api/settings/model", json={"model": "gemma4:e4b"})
    assert response.status_code == 200 and response.json()["selected"] == "gemma4:e4b"
    assert db.one("SELECT value FROM app_settings WHERE key='ollama_model'")["value"] == "gemma4:e4b"
    assert db.one("SELECT * FROM attempts WHERE id=?", (attempt["id"],)) == before
    settings.ollama_model = "environment-default:latest"
    with TestClient(main.app) as restarted:
        assert restarted.get("/api/models").json()["selected"] == "gemma4:e4b"
        models.structured("Tutor", {"question": "Hello"}, TutorReply)
    chat = next(r for r in calls if r.url.path == "/api/chat")
    assert json.loads(chat.content)["model"] == "gemma4:e4b"


@pytest.mark.parametrize(
    "name", ["not-installed:latest", "remote-alias:latest", "embed:latest", "test:cloud", "../bad name"]
)
def test_invalid_selection_cannot_replace_current_model(client, monkeypatch, name):
    ollama(monkeypatch)
    before = settings.ollama_model
    response = client.put("/api/settings/model", json={"model": name})
    assert response.status_code in (422, 503)
    assert settings.ollama_model == before and db.one("SELECT * FROM app_settings") is None


def test_model_switch_waits_for_analysis_and_tutor(client, monkeypatch, wav_bytes):
    a = upload(client, create(client), wav_bytes)
    calls = ollama(monkeypatch)
    db.execute("UPDATE attempts SET status='processing' WHERE id=?", (a["id"],))
    assert client.put("/api/settings/model", json={"model": "gemma4:e4b"}).status_code == 409
    db.execute("UPDATE attempts SET status='ready' WHERE id=?", (a["id"],))
    with main.tutor_lock:
        assert client.put("/api/settings/model", json={"model": "gemma4:e4b"}).status_code == 409
    assert calls == [] and db.one("SELECT * FROM app_settings") is None


def test_offline_picker_preserves_saved_selection_and_allows_retry(client, monkeypatch):
    ollama(monkeypatch)
    assert client.put("/api/settings/model", json={"model": "gemma4:e4b"}).status_code == 200
    ollama(monkeypatch, offline=True)
    assert client.get("/api/models").status_code == 503
    assert client.put("/api/settings/model", json={"model": "qwen3.5:9b-q4_K_M"}).status_code == 503
    assert settings.ollama_model == "gemma4:e4b"
    assert db.one("SELECT value FROM app_settings WHERE key='ollama_model'")["value"] == "gemma4:e4b"
