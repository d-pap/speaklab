import json
from datetime import date
from pathlib import Path

import httpx
import numpy as np
import pytest
import soundfile as sf
from pydantic import BaseModel, ValidationError

from app import models, progress
from app.audio import acoustic_features, transcript_metrics
from app.config import Settings
from app.curriculum import TOPICS


class Reply(BaseModel):
    answer: str
    check_question: str


def test_catalog_has_unique_grounded_concepts_and_all_categories():
    assert len({t["id"] for t in TOPICS}) == len(TOPICS)
    assert len({t["category"] for t in TOPICS}) == 12
    assert {t["difficulty"] for t in TOPICS} == {"beginner", "intermediate", "advanced"}
    for topic in TOPICS:
        assert len({c["id"] for c in topic["concepts"]}) == len(topic["concepts"])
        assert topic["sources"]
        assert all(c["reference"] and c["check"] for c in topic["concepts"])


def test_default_data_and_env_paths_are_inside_project(monkeypatch):
    monkeypatch.delenv("SPEAKLAB_DATA_DIR", raising=False)
    root = Path(__file__).resolve().parents[2]
    assert Settings(_env_file=None).data_dir == root / "data"
    assert Settings(data_dir=Path("data/e2e"), _env_file=None).data_dir == root / "data/e2e"
    assert Settings.model_config["env_file"] == root / ".env"


def test_dsp_detects_known_pitch_and_internal_pause(tmp_path, wav_bytes):
    path = tmp_path / "tone.wav"
    path.write_bytes(wav_bytes)
    metrics = acoustic_features(path)
    assert metrics["pitch_median_hz"] == pytest.approx(220, abs=2)
    assert metrics["pause_count"] == 1
    assert metrics["pause_seconds"] == pytest.approx(0.6, abs=0.06)
    assert 0.7 < metrics["active_fraction"] < 0.85
    assert -22 < metrics["loudness_dbfs"] < -12
    assert metrics["limitations"]


def test_silence_has_no_pitch_or_fake_internal_pauses(tmp_path):
    path = tmp_path / "silence.wav"
    sf.write(path, np.zeros(32000), 16000)
    metrics = acoustic_features(path)
    assert metrics["active_fraction"] == 0
    assert metrics["pitch_median_hz"] is None
    assert metrics["pause_count"] == 0


def test_transcript_rate_and_fillers_are_transcript_derived():
    metrics = transcript_metrics("Um, I like maps. You know, uh, maps.", 60, [])
    assert metrics["word_count"] == 8
    assert metrics["wpm"] == 8
    assert metrics["filler_count"] == 3
    assert "like" not in metrics["fillers"]
    assert metrics["rate_track"] == []


@pytest.mark.parametrize("recall,expected", [("again", 1), ("hard", 2), ("good", 3), ("easy", 7)])
def test_first_review_interval(recall, expected):
    assert progress.schedule(None, recall, None)[0] == expected


def test_review_intervals_cap_and_observed_gaps():
    assert progress.schedule({"interval_days": 60, "repetitions": 5}, "easy", 1)[0] == 90
    assert progress.schedule(None, "easy", 0.2)[0] == 1
    assert progress.schedule(None, "easy", 0.6)[0] == 2


def test_same_day_repetition_does_not_expand_retention_interval():
    previous = {
        "interval_days": 3,
        "repetitions": 1,
        "last_completed_at": date.today().isoformat() + "T12:00:00",
    }
    days, repetitions, _ = progress.schedule(previous, "easy", 1)
    assert days == 3
    assert repetitions == 1


@pytest.mark.parametrize(
    "url",
    [
        "https://api.example.com",
        "http://192.168.1.2:11434",
        "http://localhost.evil.com",
        "http://localhost:11434/proxy",
        "http://a:b@localhost:11434",
    ],
)
def test_model_endpoints_must_be_plain_loopback(url):
    with pytest.raises(ValidationError):
        Settings(ollama_url=url, _env_file=None)


def test_structured_model_repairs_json_once(monkeypatch):
    calls = []
    monkeypatch.setattr(models.settings, "ollama_context", 4096)
    monkeypatch.setattr(models.settings, "ollama_max_output", 1024)

    def respond(request):
        if request.url.path == "/api/show":
            return httpx.Response(200, json={"details": {"family": "qwen3"}})
        calls.append(json.loads(request.content))
        content = (
            "not json"
            if len(calls) == 1
            else json.dumps(
                {"answer": "A bucket is a location in the table.", "check_question": "What is stored there?"}
            )
        )
        return httpx.Response(200, json={"message": {"content": content}})

    monkeypatch.setattr(models, "client", lambda *args: httpx.Client(transport=httpx.MockTransport(respond)))
    answer = models.structured("Tutor", {"question": "What is a bucket?"}, Reply)
    assert answer.answer.startswith("A bucket")
    assert len(calls) == 2
    assert calls[0]["think"] is False
    assert calls[0]["format"]["type"] == "object"
    assert calls[0]["options"]["num_ctx"] == 4096
    assert calls[0]["options"]["num_predict"] == 1024


def test_context_configuration_rejects_invalid_budgets():
    with pytest.raises(ValidationError):
        Settings(ollama_context=0, _env_file=None)


def test_structured_model_fails_honestly_after_invalid_responses(monkeypatch):
    def respond(request):
        return httpx.Response(
            200, json={} if request.url.path == "/api/show" else {"message": {"content": "{}"}}
        )

    monkeypatch.setattr(models, "client", lambda *args: httpx.Client(transport=httpx.MockTransport(respond)))
    with pytest.raises(models.ServiceUnavailable, match="invalid"):
        models.structured("Tutor", {}, Reply)


def test_remote_ollama_proxy_model_is_refused(monkeypatch):
    def respond(request):
        assert request.url.path == "/api/show"  # No user content should reach chat.
        return httpx.Response(200, json={"remote_host": "https://ollama.com"})

    monkeypatch.setattr(models, "client", lambda *args: httpx.Client(transport=httpx.MockTransport(respond)))
    with pytest.raises(models.ServiceUnavailable, match="remotely"):
        models.structured("Tutor", {"private": "transcript"}, Reply)


def test_transcription_adapter_parses_real_protocol_and_skips_bad_timestamps(monkeypatch):
    def respond(request):
        assert request.url.path == "/inference"
        assert b"verbose_json" in request.content
        return httpx.Response(
            200,
            json={
                "text": "Hello world",
                "segments": [
                    {"start": 0, "end": 1, "text": "Hello world"},
                    {"start": -1, "end": 2, "text": "invalid"},
                ],
            },
        )

    monkeypatch.setattr(models, "client", lambda *args: httpx.Client(transport=httpx.MockTransport(respond)))
    text, segments = models.transcribe(Path(__file__), 2)
    assert text == "Hello world"
    assert len(segments) == 1
