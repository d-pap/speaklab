import io

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from app import models, pipeline
from app.config import settings
from app.main import app

TRANSCRIPT = "A hash map stores keys and values. A hash selects a bucket. Collisions need key comparisons."


@pytest.fixture
def wav_bytes():
    sr = 16000
    t = np.arange(sr) / sr
    signal = 0.25 * np.sin(2 * np.pi * 220 * t)
    y = np.r_[signal, np.zeros(int(sr * 0.6)), signal]
    buffer = io.BytesIO()
    sf.write(buffer, y, sr, format="WAV", subtype="PCM_16")
    return buffer.getvalue()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "ollama_model", settings.ollama_model)
    monkeypatch.setattr(pipeline, "submit", pipeline.process)
    monkeypatch.setattr(
        models,
        "transcribe",
        lambda path, duration: (TRANSCRIPT, [{"start": 0, "end": 2.6, "text": TRANSCRIPT}]),
    )

    def test_assessment(topic, transcript, metrics, style, prompt):
        return {
            "summary": "Explicit test-double assessment.",
            "model": "test-double",
            "concepts": [
                {
                    "concept_id": c["id"],
                    "status": "correct" if i == 0 else "missing",
                    "evidence": transcript if i == 0 else "",
                    "feedback": "Test feedback.",
                }
                for i, c in enumerate(topic["concepts"])
            ],
            "next_steps": ["Explain collision handling."],
            "communication": [],
            "rubric": "Test rubric.",
        }

    monkeypatch.setattr(models, "assess", test_assessment)
    monkeypatch.setattr(
        models,
        "review_insights",
        lambda *args: {
            "claims": [],
            "vocabulary": [],
            "sources": [],
            "version": 2,
            "note": "Explicit test double.",
        },
    )
    monkeypatch.setattr(
        models,
        "tutor",
        lambda *args: {
            "answer": "This is an explicit test tutor response.",
            "check_question": "What is a collision?",
        },
    )
    with TestClient(app, headers={"X-SpeakLab-Client": "1"}) as client:
        yield client


def create(client):
    response = client.post("/api/sessions", json={"topic_id": "hash-maps"})
    assert response.status_code == 201, response.text
    return response.json()


def upload(client, session, wav_bytes, number=1):
    response = client.post(
        f"/api/sessions/{session['id']}/attempts/{number}",
        files={"file": ("../../unsafe.wav", wav_bytes, "audio/wav")},
    )
    assert response.status_code == 201, response.text
    return response.json()
