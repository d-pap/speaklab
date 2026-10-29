import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import Settings, settings
from app.main import app
from app.security import configure_browser_security


@pytest.mark.parametrize("origin", [
    "http://pc.example", "https://*.example", "https://pc.example/path",
    "https://user:secret@pc.example", "https://pc.example?x=1", "https://pc.example#x",
    "https://pc.example:99999", "https://pc.example\n", "https://",
])
def test_extra_browser_origins_must_be_exact_https_origins(origin):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, browser_origins=[origin])


def test_browser_origin_configuration_is_canonical_and_does_not_change_model_boundary():
    config = Settings(_env_file=None, browser_origins=["https://PC.example:443/", "https://pc.example"])
    assert config.browser_origins == ["https://pc.example"]
    with pytest.raises(ValidationError):
        Settings(_env_file=None, ollama_url="https://pc.example")


def test_private_https_can_use_real_api_without_loosening_host_or_csrf_checks(client):
    origin = "https://pc.tail-test.ts.net"
    config = Settings(_env_file=None, data_dir=settings.data_dir, browser_origins=[origin])
    protected = FastAPI()
    protected.include_router(app.router)
    configure_browser_security(protected, config, logging.getLogger("test-security"))
    with TestClient(protected, base_url=origin) as browser:
        response = browser.get("/api/topics", headers={"Origin": origin})
        assert response.status_code == 200
        assert response.headers["Access-Control-Allow-Origin"] == origin
        response = browser.post("/api/sessions", headers={"Origin": origin, "X-SpeakLab-Client": "1"},
                                json={"topic_id": "hash-maps"})
        assert response.status_code == 201
        assert client.get(f"/api/sessions/{response.json()['id']}").status_code == 200
        assert browser.post("/api/sessions", headers={"Origin": origin},
                            json={"topic_id": "hash-maps"}).status_code == 403
        for untrusted in ("https://other.tail-test.ts.net", "https://evil.example", "http://pc.tail-test.ts.net"):
            assert browser.get("/api/topics", headers={"Origin": untrusted}).status_code == 403
        assert browser.get("/api/topics", headers={"Host": "evil.example"}).status_code == 400
        assert browser.options("/api/sessions", headers={
            "Origin": origin, "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "X-SpeakLab-Client,Content-Type",
        }).status_code == 200
