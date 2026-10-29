import json
from datetime import date
from pathlib import Path

import httpx
import numpy as np
import pytest
import soundfile as sf
from pydantic import ValidationError

from app import models, progress
from app.audio import acoustic_features, transcript_metrics
from app.config import Settings
from app.curriculum import CATALOG, TOPICS
from app.schemas import Assessment, TutorReply


def test_catalog_has_unique_grounded_concepts_and_all_categories():
    assert len({t["id"] for t in TOPICS}) == len(TOPICS)
    assert len({t["category"] for t in TOPICS}) == 8
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


def valid_result():
    return Assessment(
        summary="A limited explanation",
        next_steps=["Explain collisions"],
        communication=[],
        concepts=[
            {
                "concept_id": c["id"],
                "status": "correct" if i == 0 else "missing",
                "evidence": "A hash selects a bucket." if i == 0 else "",
                "feedback": "Feedback",
            }
            for i, c in enumerate(CATALOG["hash-maps"]["concepts"])
        ],
    )


def test_assessment_rejects_fabricated_evidence_and_duplicate_concepts():
    result = valid_result()
    models.validate_assessment(result, CATALOG["hash-maps"], "A hash selects a bucket.")
    result.concepts[0].evidence = "The user never said this."
    with pytest.raises(ValueError, match="verbatim"):
        models.validate_assessment(result, CATALOG["hash-maps"], "A hash selects a bucket.")
    result = valid_result()
    result.concepts.append(result.concepts[0])
    with pytest.raises(ValueError, match="exactly once"):
        models.validate_assessment(result, CATALOG["hash-maps"], "A hash selects a bucket.")


def test_missing_is_not_incorrect_and_cannot_invent_evidence():
    result = valid_result()
    assert result.concepts[1].status == "missing"
    result.concepts[1].evidence = "A hash selects a bucket."
    with pytest.raises(ValueError, match="missing"):
        models.validate_assessment(result, CATALOG["hash-maps"], "A hash selects a bucket.")


def test_assessment_repair_receives_all_evidence_errors(monkeypatch):
    valid = valid_result().model_dump()
    valid["concepts"][0]["evidence"] = "excerpt_1"
    invalid = valid_result().model_dump()
    invalid["concepts"][0]["evidence"] = "The transcript states: A hash selects a bucket."
    invalid["communication"] = [{"suggestion": "Add an example.", "evidence": "The speaker described hashing."}]
    calls = []

    def respond(request):
        if request.url.path == "/api/show":
            return httpx.Response(200, json={})
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={"message": {"content": json.dumps(invalid if len(calls) == 1 else valid)}})

    monkeypatch.setattr(models, "client", lambda *args: httpx.Client(transport=httpx.MockTransport(respond)))
    result = models.assess(CATALOG["hash-maps"], "A hash selects a bucket.", None, "Conversational", "Explain hashing")
    assert result["concepts"][0]["evidence"] == "A hash selects a bucket."
    repair = calls[1]["messages"][-1]["content"]
    assert "concepts[hashing].evidence" in repair
    assert "communication[0].evidence" in repair
    schema = calls[0]["format"]
    assert json.loads(calls[0]["messages"][1]["content"])["output_schema"] == schema
    assert schema["$defs"]["ConceptResult"]["properties"]["concept_id"]["enum"] == [c["id"] for c in CATALOG["hash-maps"]["concepts"]]
    assert schema["properties"]["concepts"]["minItems"] == schema["properties"]["concepts"]["maxItems"] == 4


def test_assessment_constrains_and_resolves_transcript_evidence(monkeypatch):
    transcript = "This is a microphone test.\n I am checking the recording."
    result = valid_result().model_dump()
    for concept in result["concepts"]:
        concept.update(status="missing", evidence="")
    result["communication"] = [{"suggestion": "Begin with the concept next time.", "evidence": "excerpt_1"}]

    def respond(request):
        if request.url.path == "/api/show":
            return httpx.Response(200, json={})
        body = json.loads(request.content)
        payload = json.loads(body["messages"][1]["content"])
        excerpts = payload["transcript_excerpts"]
        assert excerpts == {
            "excerpt_1": "This is a microphone test.",
            "excerpt_2": "I am checking the recording.",
        }
        definitions = body["format"]["$defs"]
        assert definitions["CoachingPoint"]["properties"]["evidence"]["enum"] == list(excerpts)
        assert definitions["ConceptResult"]["properties"]["evidence"]["enum"] == ["", *excerpts]
        return httpx.Response(200, json={"message": {"content": json.dumps(result)}})

    monkeypatch.setattr(models, "client", lambda *args: httpx.Client(transport=httpx.MockTransport(respond)))
    assessment = models.assess(CATALOG["hash-maps"], transcript, None, "Conversational", "Explain hashing")
    assert assessment["communication"][0]["evidence"] == "This is a microphone test."
    assert all(c["status"] == "missing" and c["evidence"] == "" for c in assessment["concepts"])
    models.validate_assessment(Assessment(**{k: assessment[k] for k in result}), CATALOG["hash-maps"], transcript)


@pytest.mark.parametrize("evidence", ["intended_style: Conversational", "", "excerpt_999"])
def test_assessment_never_accepts_unsupported_communication_evidence(monkeypatch, evidence):
    result = valid_result().model_dump()
    result["concepts"][0]["evidence"] = "excerpt_1"
    result["communication"] = [{"suggestion": "Add an example.", "evidence": evidence}]

    def respond(request):
        return httpx.Response(200, json={} if request.url.path == "/api/show" else {
            "message": {"content": json.dumps(result)}
        })

    monkeypatch.setattr(models, "client", lambda *args: httpx.Client(transport=httpx.MockTransport(respond)))
    with pytest.raises(models.ServiceUnavailable, match="invalid assessment twice"):
        models.assess(CATALOG["hash-maps"], "A hash selects a bucket.", None, "Conversational", "Explain hashing")


def test_transcript_excerpts_preserve_all_text_with_bounded_verbatim_quotes():
    transcript = "First sentence.\n  Second sentence! " + "long uninterrupted clause " * 70 + "x" * 1200
    excerpts = models.transcript_excerpts(transcript)
    assert len(excerpts) > 4
    assert all(0 < len(text) <= 500 and text in transcript for text in excerpts.values())
    assert "".join("".join(excerpts.values()).split()) == "".join(transcript.split())


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
    answer = models.structured("Tutor", {"question": "What is a bucket?"}, TutorReply)
    assert answer.answer.startswith("A bucket")
    assert len(calls) == 2
    assert calls[0]["think"] is False
    assert calls[0]["format"]["type"] == "object"
    assert calls[0]["options"]["num_ctx"] == 4096
    assert calls[0]["options"]["num_predict"] == 1024


def test_measurement_summary_keeps_evidence_without_dense_plot_arrays():
    track = [{"time": i / 10, "value": 220} for i in range(3600)]
    metrics = {
        "pitch_track": track, "loudness_track": track,
        "pitch_median_hz": 220, "pause_count": 2, "wpm": 130,
        "extended_silences": [{"start": 4, "duration": 2.3}, {"start": 20, "duration": 3.5}],
        "limitations": ["Pitch is an estimate."], "rate_track": [{"time": 0, "value": 130}],
    }
    summary = models.measurement_summary(metrics)
    assert summary["pitch_median_hz"] == 220
    assert summary["extended_silence_seconds"] == 5.8
    assert summary["extended_silence_count"] == 2
    assert summary["limitations"] == metrics["limitations"]
    assert "pitch_track" not in summary and "loudness_track" not in summary
    assert metrics["pitch_track"] == track  # The UI retains the original measurements.
    assert models.measurement_summary(None) is None
    assert len(json.dumps(summary)) < 1000


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
        models.structured("Tutor", {}, TutorReply)


def test_remote_ollama_proxy_model_is_refused(monkeypatch):
    def respond(request):
        assert request.url.path == "/api/show"  # No user content should reach chat.
        return httpx.Response(200, json={"remote_host": "https://ollama.com"})

    monkeypatch.setattr(models, "client", lambda *args: httpx.Client(transport=httpx.MockTransport(respond)))
    with pytest.raises(models.ServiceUnavailable, match="remotely"):
        models.structured("Tutor", {"private": "transcript"}, TutorReply)


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
