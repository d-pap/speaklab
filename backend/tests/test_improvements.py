import sqlite3

import httpx
from conftest import create, upload

from app import db, models, pipeline
from app.curriculum import CATALOG, TOPICS
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


def test_all_topics_carry_short_context_that_grounds_the_coach():
    # The prewritten lesson is gone; this context now reaches the coach chat as the topic reference.
    for topic in TOPICS:
        assert 15 <= len(topic["background"].split()) <= 70
        assert 20 <= len(topic["practice"].split()) <= 100
        for concept in topic["concepts"]:
            assert concept["bridge"] and concept["reference"] and concept["check"]
            assert len((concept["bridge"] + " " + concept["reference"]).split()) < 160
        assert topic["sources"] and topic["reviewed_at"]
    tokens = next(c for c in CATALOG["auth"]["concepts"] if c["name"] == "Sessions and tokens")
    assert "password again" in tokens["bridge"]
    assert "OIDC" in CATALOG["auth"]["practice"]


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


def test_failed_retranscription_keeps_text_and_analysis_until_new_text_arrives(client, wav_bytes, monkeypatch):
    a = upload(client, create(client), wav_bytes)
    before = db.attempt_public(db.one("SELECT * FROM attempts WHERE id=?", (a["id"],)))
    monkeypatch.setattr(
        models, "transcribe", lambda *args: (_ for _ in ()).throw(models.ServiceUnavailable("Offline"))
    )
    db.execute("UPDATE attempts SET retranscribe=1 WHERE id=?", (a["id"],))
    pipeline.process(a["id"])
    failed = db.attempt_public(db.one("SELECT * FROM attempts WHERE id=?", (a["id"],)))
    assert failed["transcript"] == before["transcript"] and failed["lines"] == before["lines"]
    assert failed["analysis"]["technical"] == before["analysis"]["technical"]
    assert failed["retranscribe"] == 1 and failed["status"] == "partial"
    text = "A newly transcribed explanation of how a hash map hashes each key to choose one bucket."
    monkeypatch.setattr(models, "transcribe", lambda *args: (text, []))
    pipeline.process(a["id"])
    fixed = db.attempt_public(db.one("SELECT * FROM attempts WHERE id=?", (a["id"],)))
    assert fixed["status"] == "ready" and fixed["retranscribe"] == 0
    assert fixed["lines"][0]["text"] == text
    assert fixed["analysis"]["passes"]["technical"]["status"] == "done"
    assert fixed["analysis"]["technical"]["concepts"][0]["line_ids"] == ["L1"]


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
