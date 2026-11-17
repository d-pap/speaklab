import json
import sqlite3

import httpx
import pytest
from pydantic import BaseModel

from app import db, llm, models
from app.config import settings


class Answer(BaseModel):
    value: str


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    db.initialize()


def mock_ollama(monkeypatch, handler):
    requests = []

    def wrapped(request: httpx.Request):
        if request.url.path == "/api/show":
            return httpx.Response(200, json={"details": {}})
        body = json.loads(request.content)
        requests.append(body)
        return handler(request, body)

    monkeypatch.setattr(models, "transport", httpx.MockTransport(wrapped))
    return requests


def chat_reply(content, done_reason="stop"):
    return httpx.Response(200, json={"message": {"content": content}, "done": True, "done_reason": done_reason})


def test_pass_settings_default_to_current_model_and_limits(fresh_db):
    result = llm.pass_settings()
    assert set(result) == set(llm.PASSES)
    for name in llm.PASSES:
        assert result[name]["model"] == settings.ollama_model
        assert result[name]["num_ctx"] == 8192
        assert result[name]["num_predict"] == (4096 if name == "writer" else 2048)


def test_writer_defaults_to_4096_output(fresh_db):
    assert llm.pass_settings()["writer"]["num_predict"] == 4096
    assert llm.pass_settings()["chat"]["num_predict"] == 2048


def test_pass_settings_fall_back_to_saved_single_model(fresh_db):
    db.execute("INSERT INTO app_settings(key,value) VALUES('ollama_model','saved-model')")
    assert llm.pass_settings()["memory"]["model"] == "saved-model"


def test_save_pass_settings_rejects_unknown_pass_and_uninstalled_model(fresh_db, monkeypatch):
    monkeypatch.setattr(
        models, "installed_models", lambda: [{"name": "that-model", "selectable": True}]
    )
    good = {"model": "that-model", "num_ctx": 8192, "num_predict": 2048}
    with pytest.raises(ValueError):
        llm.save_pass_settings({"vision": good})
    with pytest.raises(ValueError):
        llm.save_pass_settings({"chat": {**good, "model": "missing"}})
    with pytest.raises(ValueError):
        llm.save_pass_settings({"chat": {**good, "num_ctx": 1024}})
    with pytest.raises(ValueError):
        llm.save_pass_settings({"chat": {**good, "num_predict": 8000}})
    assert llm.pass_settings()["chat"]["model"] == settings.ollama_model
    saved = llm.save_pass_settings({"chat": good})
    assert saved["chat"]["model"] == "that-model"
    assert llm.pass_settings()["technical"]["model"] == settings.ollama_model


def test_structured_call_uses_pass_model(fresh_db, monkeypatch):
    monkeypatch.setattr(models, "installed_models", lambda: [{"name": "that-model", "selectable": True}])
    llm.save_pass_settings({"communication": {"model": "that-model", "num_ctx": 6144, "num_predict": 1024}})
    requests = mock_ollama(monkeypatch, lambda r, b: chat_reply('{"value": "ok"}'))
    parsed, model_used = llm.structured_call("communication", "sys", {"x": 1}, Answer)
    assert parsed.value == "ok" and model_used == "that-model"
    assert requests[0]["model"] == "that-model"
    assert requests[0]["options"]["num_ctx"] == 6144
    assert requests[0]["options"]["num_predict"] == 1024
    assert requests[0]["think"] is False


def test_structured_call_repairs_once_then_fails(fresh_db, monkeypatch):
    requests = mock_ollama(monkeypatch, lambda r, b: chat_reply("not json"))
    with pytest.raises(models.ServiceUnavailable):
        llm.structured_call("technical", "sys", {}, Answer)
    assert len(requests) == 2


def test_text_call_returns_text_and_model(fresh_db, monkeypatch):
    mock_ollama(monkeypatch, lambda r, b: chat_reply("hello"))
    text, model_used = llm.text_call("chat", [{"role": "user", "content": "hi"}])
    assert (text, model_used) == ("hello", settings.ollama_model)
    assert llm.call_state.truncated is False


def test_stream_call_yields_chunks(fresh_db, monkeypatch):
    lines = [
        {"message": {"content": "a"}},
        {"message": {"content": "b"}},
        {"done": True},
    ]
    body = "\n".join(json.dumps(line) for line in lines)
    requests = mock_ollama(monkeypatch, lambda r, b: httpx.Response(200, content=body))
    assert list(llm.stream_call("chat", [{"role": "user", "content": "hi"}])) == ["a", "b"]
    assert requests[0]["stream"] is True


def stream_body(*lines):
    return httpx.Response(200, content="\n".join(x if isinstance(x, str) else json.dumps(x) for x in lines))


def test_stream_call_reports_model_and_truncation_through_result(fresh_db, monkeypatch):
    mock_ollama(
        monkeypatch,
        lambda r, b: stream_body({"message": {"content": "a"}}, {"done": True, "done_reason": "length"}),
    )
    result = llm.StreamResult()
    assert list(llm.stream_call("chat", [{"role": "user", "content": "hi"}], result=result)) == ["a"]
    assert (result.done, result.truncated, result.model) == (True, True, settings.ollama_model)
    mock_ollama(monkeypatch, lambda r, b: stream_body({"message": {"content": "b"}}, {"done": True}))
    result = llm.StreamResult()
    assert list(llm.stream_call("chat", [{"role": "user", "content": "hi"}], result=result)) == ["b"]
    assert (result.done, result.truncated) == (True, False)


def test_stream_without_done_line_is_unavailable(fresh_db, monkeypatch):
    mock_ollama(monkeypatch, lambda r, b: stream_body({"message": {"content": "partial"}}))
    received = []
    with pytest.raises(models.ServiceUnavailable):
        for chunk in llm.stream_call("chat", [{"role": "user", "content": "hi"}]):
            received.append(chunk)
    assert received == ["partial"]


@pytest.mark.parametrize("bad", ["{not json", "[1, 2]", json.dumps({"error": "model crashed"})])
def test_stream_with_malformed_line_is_unavailable(fresh_db, monkeypatch, bad):
    mock_ollama(monkeypatch, lambda r, b: stream_body({"message": {"content": "a"}}, bad, {"done": True}))
    with pytest.raises(models.ServiceUnavailable):
        list(llm.stream_call("chat", [{"role": "user", "content": "hi"}]))


def test_prompt_over_budget_raises_without_sending(fresh_db, monkeypatch):
    requests = mock_ollama(monkeypatch, lambda r, b: chat_reply("x"))
    assert llm.prompt_budget("chat") == 8192 - 2048
    huge = [{"role": "user", "content": "w" * (4 * 6200)}]
    with pytest.raises(llm.PromptTooLong):
        llm.text_call("chat", huge)
    with pytest.raises(llm.PromptTooLong):
        list(llm.stream_call("chat", huge))
    with pytest.raises(llm.PromptTooLong):
        llm.structured_call("technical", "s", {"t": "w" * (4 * 6200)}, Answer)
    assert requests == []
    assert issubclass(llm.PromptTooLong, models.ServiceUnavailable)


def test_length_stop_raises_for_structured_and_flags_for_text(fresh_db, monkeypatch):
    mock_ollama(monkeypatch, lambda r, b: chat_reply('{"value": "cut', "length"))
    with pytest.raises(llm.LengthLimited):
        llm.structured_call("technical", "sys", {}, Answer)
    text, _ = llm.text_call("chat", [{"role": "user", "content": "hi"}])
    assert text == '{"value": "cut'
    assert llm.call_state.truncated is True
    mock_ollama(monkeypatch, lambda r, b: chat_reply("fine"))
    llm.text_call("chat", [{"role": "user", "content": "hi"}])
    assert llm.call_state.truncated is False


def test_http_failure_raises_service_unavailable(fresh_db, monkeypatch):
    mock_ollama(monkeypatch, lambda r, b: httpx.Response(500))
    with pytest.raises(models.ServiceUnavailable):
        llm.text_call("chat", [{"role": "user", "content": "hi"}])


def test_get_and_put_settings_passes(client, monkeypatch):
    monkeypatch.setattr(models, "installed_models", lambda: [{"name": "m2", "selectable": True}])
    got = client.get("/api/settings/passes").json()
    assert got["writer"]["num_predict"] == 4096
    body = {"passes": {"chat": {"model": "m2", "num_ctx": 8192, "num_predict": 2048}}}
    response = client.put("/api/settings/passes", json=body)
    assert response.status_code == 200, response.text
    assert response.json()["chat"]["model"] == "m2"
    bad = {"passes": {"vision": {"model": "m2", "num_ctx": 8192, "num_predict": 2048}}}
    assert client.put("/api/settings/passes", json=bad).status_code == 422


def test_put_settings_passes_busy_returns_409(client, monkeypatch):
    monkeypatch.setattr(models, "installed_models", lambda: [{"name": "m2", "selectable": True}])
    monkeypatch.setattr(
        "app.main.db.one", lambda sql, args=(): {"id": 1} if "attempts" in sql else None
    )
    body = {"passes": {"chat": {"model": "m2", "num_ctx": 8192, "num_predict": 2048}}}
    assert client.put("/api/settings/passes", json=body).status_code == 409


def test_stored_falls_back_only_when_table_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    assert llm._stored("ollama_model") is None  # uninitialized database: defaults

    def locked(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(db, "one", locked)
    with pytest.raises(sqlite3.OperationalError, match="locked"):
        llm._stored("ollama_model")
