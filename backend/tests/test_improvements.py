import json
import sqlite3

import httpx
import pytest
from conftest import create, upload

from app import db, models, pipeline
from app.curriculum import CATALOG, TOPICS, lesson
from app.speech import readability, speech_observations, vocal_foundations


def test_hesitations_are_distinct_from_contextual_words_and_preserve_offsets():
    text = "Umm, I like trees. You know, uh, the the tree is tall. I mean it."
    segments = [{"text": text, "start": 1, "end": 12, "words": [{"word": "Umm,", "start": 1.2, "end": 1.7}]}]
    result = speech_observations(text, 30, segments)
    assert result["fillers"] == {"um": 1, "uh": 1}
    assert result["filler_count"] == 2 and result["fillers_per_minute"] == 4
    assert result["filler_candidates"] == {"like": 1, "you know": 1, "i mean": 1}
    assert result["filler_events"][0]["start"] == 1.2
    assert result["filler_events"][0]["timing"] == "estimated-word"
    assert result["repetitions"][0]["text"] == "the the"
    assert all(text[e["char_start"] : e["char_end"]] == e["text"] for e in result["filler_events"])
    assert all(e["start"] is None for e in speech_observations(text, 30, [])["filler_events"])
    assert speech_observations("Uuum, uuuh", 30, [])["fillers"] == {"um": 1, "uh": 1}


def test_readability_is_optional_bounded_sample_and_does_not_mutate_transcript():
    assert not readability("Um, hello.")["available"]
    text = ("Um, I can see the bird by the tree. " * 14).strip()
    result = readability(text)
    assert result["available"] and result["words"] == 112
    assert len(result["grade_band"]) == 2
    assert text.startswith("Um,")
    assert "not a vocabulary" in result["limitation"]


def test_vocal_markers_are_measured_windows_without_emotion_inference():
    result = vocal_foundations(
        {
            "wpm": 140,
            "rate_track": [{"time": 30, "value": 180}],
            "delivery_windows": [{"start": 15, "pitch_range_semitones": 1.5, "loudness_range_db": 4}],
            "pauses": [{"start": 42, "duration": 2}],
            "pause_count": 1,
            "pause_seconds": 2,
        },
        "Conversational",
    )
    assert [p["start"] for p in result] == [30, 15, 15, 42, None]
    assert "1.5" in result[2]["observation"]
    assert "cannot establish" in result[4]["observation"]
    assert len(vocal_foundations({}, "Conversational")) == 5


def test_all_topics_gain_short_context_without_extra_sections():
    for topic in TOPICS:
        path = lesson(topic, None)
        assert len(path["sections"]) == len(topic["concepts"]) + 3
        assert 15 <= len(path["sections"][0]["context"].split()) <= 70
        assert 20 <= len(topic["practice"].split()) <= 100
        for section in path["sections"][1:-2]:
            assert section["context"] and section["body"] and section["question"]
            assert len((section["context"] + " " + section["body"]).split()) < 160
        assert path["sources"] and path["reviewed_at"]
    auth = lesson(CATALOG["auth"], None)
    tokens = next(s for s in auth["sections"] if s["title"] == "Sessions and tokens")
    assert "password again" in tokens["context"]
    assert "OIDC" in auth["sections"][-2]["practice"]


def insight_response():
    return {
        "claims": [
            {
                "evidence": "excerpt_1",
                "verdict": "incorrect",
                "explanation": "Login is not blanket permission.",
                "correction": "Check the action and resource permissions.",
                "reference_ids": ["permissions"],
            }
        ],
        "vocabulary": [
            {
                "evidence": "excerpt_1",
                "original": "everything",
                "alternative": "every protected resource",
                "meaning": "An item controlled by an access policy.",
                "reason": "Names the scope of access.",
                "practice": "Check access to each protected resource.",
            }
        ],
    }


def mock_insight(monkeypatch, value):
    def respond(request):
        if request.url.path == "/api/show":
            return httpx.Response(200, json={})
        body = json.loads(request.content)
        assert body["format"]["$defs"]["ClaimReview"]["properties"]["evidence"]["enum"] == ["excerpt_1"]
        return httpx.Response(200, json={"message": {"content": json.dumps(value)}})

    monkeypatch.setattr(models, "client", lambda *args: httpx.Client(transport=httpx.MockTransport(respond)))


def test_factual_review_resolves_only_supplied_claims_and_reference_text(monkeypatch):
    mock_insight(monkeypatch, insight_response())
    result = models.review_insights(CATALOG["auth"], "Login lets you access everything.")
    assert result["claims"][0]["evidence"] == "Login lets you access everything."
    assert result["claims"][0]["references"][0]["text"] == CATALOG["auth"]["concepts"][1]["reference"]
    assert result["vocabulary"] == []  # Do not polish an explicitly incorrect claim.


def test_asr_line_wraps_keep_claim_context_and_exact_vocabulary_characters(monkeypatch):
    text = "Login lets you\naccess everything."
    assert models.transcript_excerpts(text) == {"excerpt_1": text}
    response = insight_response()
    response["claims"] = []
    response["vocabulary"][0]["original"] = "you access everything"
    mock_insight(monkeypatch, response)
    result = models.review_insights(CATALOG["auth"], text)
    assert result["vocabulary"][0]["original"] == "you\naccess everything"
    assert result["vocabulary"][0]["evidence"] == text


def test_supported_claim_has_no_placeholder_correction(monkeypatch):
    response = insight_response()
    response["claims"][0].update(verdict="supported", correction="N/A")
    response["vocabulary"] = []
    mock_insight(monkeypatch, response)
    result = models.review_insights(CATALOG["auth"], "Authentication establishes identity.")
    assert result["claims"][0]["correction"] == ""


@pytest.mark.parametrize("available", [True, False])
def test_proposed_corrections_need_second_review_and_fail_as_unverified(monkeypatch, available):
    calls = []

    def respond(request):
        if request.url.path == "/api/show":
            return httpx.Response(200, json={})
        body = json.loads(request.content)
        calls.append(body)
        value = insight_response()
        if len(calls) > 1:
            assert body["format"]["properties"]["vocabulary"]["maxItems"] == 0
            if not available:
                return httpx.Response(503)
            value["claims"][0].update(
                verdict="supported", explanation="The original claim is consistent.", correction=""
            )
            value["vocabulary"] = []
        return httpx.Response(200, json={"message": {"content": json.dumps(value)}})

    monkeypatch.setattr(models, "client", lambda *args: httpx.Client(transport=httpx.MockTransport(respond)))
    result = models.review_insights(CATALOG["auth"], "Login lets you access everything.")
    assert len(calls) == 2
    assert result["claims"][0]["verdict"] == ("supported" if available else "unverified")
    assert result["claims"][0]["correction"] == ""


@pytest.mark.parametrize("mutation", ["quote", "reference", "missing_correction", "vocabulary", "ungrounded"])
def test_unverifiable_model_fields_are_rejected(monkeypatch, mutation):
    result = insight_response()
    if mutation == "quote":
        result["claims"][0]["evidence"] = "invented words"
    if mutation == "reference":
        result["claims"][0]["reference_ids"] = ["invented"]
    if mutation == "missing_correction":
        result["claims"][0]["correction"] = ""
    if mutation == "vocabulary":
        result["vocabulary"][0]["original"] = "not actually said"
    if mutation == "ungrounded":
        result["claims"][0]["reference_ids"] = []
    mock_insight(monkeypatch, result)
    with pytest.raises(models.ServiceUnavailable, match="invalid response twice"):
        models.review_insights(CATALOG["auth"], "Login lets you access everything.")


def test_whisper_verbatim_parameters_and_finite_timestamps(monkeypatch, tmp_path):
    path = tmp_path / "audio.wav"
    path.write_bytes(b"test-double")

    def respond(request):
        assert b'name="prompt"' in request.content and b"Um, well" in request.content
        assert b'name="suppress_non_speech"\r\n\r\nfalse' in request.content
        return httpx.Response(
            200,
            json={
                "text": "Um, I, I know.",
                "segments": [
                    {
                        "start": 0,
                        "end": 2,
                        "text": "Um, I, I know.",
                        "words": [
                            {"word": "Um,", "start": 0.1, "end": 0.3},
                            {"word": "bad", "start": -1, "end": 1},
                        ],
                    }
                ],
            },
        )

    monkeypatch.setattr(models, "client", lambda *args: httpx.Client(transport=httpx.MockTransport(respond)))
    text, segments = models.transcribe(path, 2)
    assert text == "Um, I, I know." and len(segments[0]["words"]) == 1


def test_reanalysis_archives_completed_session_without_rescheduling(client, wav_bytes):
    s = create(client)
    a = upload(client, s, wav_bytes)
    db.execute(
        "UPDATE sessions SET completed_at='2026-10-27T12:00:00+00:00', review_due='2026-10-30' WHERE id=?",
        (s["id"],),
    )
    original = db.one("SELECT * FROM attempts WHERE id=?", (a["id"],))
    response = client.post(f"/api/attempts/{a['id']}/reanalyze", json={"retranscribe": True})
    assert response.status_code == 200
    after = db.one("SELECT * FROM attempts WHERE id=?", (a["id"],))
    assert after["audio_file"] == original["audio_file"] and after["status"] == "ready"
    history = client.get(f"/api/attempts/{a['id']}/analysis-history").json()
    assert len(history) == 1 and history[0]["attempt"]["transcript"] == original["transcript"]
    assert "audio_file" not in history[0]["attempt"]
    assert db.one("SELECT review_due FROM sessions WHERE id=?", (s["id"],))["review_due"] == "2026-10-30"


def test_optional_review_failure_does_not_discard_core_assessment(client, wav_bytes, monkeypatch):
    monkeypatch.setattr(
        models,
        "review_insights",
        lambda *args: (_ for _ in ()).throw(models.ServiceUnavailable("Unavailable")),
    )
    a = upload(client, create(client), wav_bytes)
    a = db.attempt_public(db.one("SELECT * FROM attempts WHERE id=?", (a["id"],)))
    assert a["assessment"] and a["acoustics"] and "insights" in a["errors"]


def test_manual_transcripts_protected_from_retranscription(client, wav_bytes):
    a = upload(client, create(client), wav_bytes)
    db.execute("UPDATE attempts SET transcript_source='manual' WHERE id=?", (a["id"],))
    assert client.post(f"/api/attempts/{a['id']}/reanalyze", json={"retranscribe": True}).status_code == 409
    assert client.post(f"/api/attempts/{a['id']}/reanalyze", json={}).status_code == 200


def test_failed_retranscription_keeps_text_but_cannot_create_stale_assessment(client, wav_bytes, monkeypatch):
    a = upload(client, create(client), wav_bytes)
    before = db.one("SELECT * FROM attempts WHERE id=?", (a["id"],))
    monkeypatch.setattr(
        models, "transcribe", lambda *args: (_ for _ in ()).throw(models.ServiceUnavailable("Offline"))
    )
    assert client.post(f"/api/attempts/{a['id']}/reanalyze", json={"retranscribe": True}).status_code == 200
    failed = db.one("SELECT * FROM attempts WHERE id=?", (a["id"],))
    assert failed["transcript"] == before["transcript"] and failed["assessment"] is None
    assert failed["retranscribe"] == 1 and failed["status"] == "partial"
    monkeypatch.setattr(models, "transcribe", lambda *args: ("A newly transcribed explanation.", []))
    pipeline.process(a["id"])
    fixed = db.attempt_public(db.one("SELECT * FROM attempts WHERE id=?", (a["id"],)))
    assert fixed["status"] == "ready" and fixed["retranscribe"] == 0
    assert fixed["assessment"]["concepts"][0]["evidence"] == "A newly transcribed explanation."


def test_schema_upgrade_preserves_v1_rows_and_is_repeatable(tmp_path, monkeypatch):
    monkeypatch.setattr(db.settings, "data_dir", tmp_path)
    with sqlite3.connect(tmp_path / "speaklab.sqlite3") as conn:
        conn.executescript(
            "CREATE TABLE attempts (id TEXT, session_id TEXT, status TEXT, errors TEXT); PRAGMA user_version=1; INSERT INTO attempts VALUES('kept','session','ready','{}');"
        )
    db.initialize()
    db.initialize()
    assert db.one("SELECT * FROM attempts")["id"] == "kept"
    assert db.one("SELECT * FROM attempts")["transcription_version"] == 0
