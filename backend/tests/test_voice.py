from app.voice import voice_summary

LINES = [
    {"id": "L1", "start": 0.0, "end": 10.0, "text": "a"},
    {"id": "L2", "start": 10.0, "end": 25.0, "text": "b"},
    {"id": "L3", "start": 30.0, "end": 45.0, "text": "c"},
    {"id": "L4", "start": 60.0, "end": 85.0, "text": "d"},
]
TOKENS = [
    {"type": "word", "text": "a", "line_id": "L1", "start": 0.0},
    {"type": "pause", "seconds": 1.6, "line_id": "L2"},
    {"type": "word", "text": "b", "line_id": "L2", "start": 11.0},
    {"type": "pause", "seconds": 13.0, "line_id": "L3"},
    {"type": "pause", "seconds": 3.4, "line_id": "L4"},
]
METRICS = {
    "wpm": 120,
    "rate_track": [
        {"time": 0, "value": 170},
        {"time": 30, "value": 140},
        {"time": 60, "value": 110},
    ],
    "pitch_range_semitones": 4.2,
    "loudness_range_db": 9.5,
    "pitch_track": [{"time": 0.0, "value": 100.0}] * 50,
    "loudness_track": [{"time": 0.0, "value": -30.0}] * 50,
    "delivery_windows": [{"start": 0, "end": 15, "pitch_range_semitones": 3.0}],
}


def test_summary_names_longest_pause_line():
    out = voice_summary(METRICS, LINES, TOKENS)
    assert out[0] == "Longest pause 13.0s before L3."
    assert any("3.4s pause before L4" in s for s in out)


def test_summary_reports_pace_and_window_lines():
    text = " ".join(voice_summary(METRICS, LINES, TOKENS))
    assert "120 words per minute" in text
    assert "170 wpm" in text and "L1-L2" in text
    assert "110 wpm" in text and "L4" in text


def test_summary_has_no_judgement_words():
    text = " ".join(voice_summary(METRICS, LINES, TOKENS)).lower()
    for word in ("monotone", "quiet", "boring", "confident", "nervous"):
        assert word not in text
    assert "4.2 semitones" in text and "9.5 db" in text


def test_summary_at_most_six_sentences_and_no_arrays():
    out = voice_summary(METRICS, LINES, TOKENS)
    assert len(out) <= 6
    assert all("[" not in s and "{" not in s for s in out)


def test_summary_skips_missing_data_without_raising():
    assert voice_summary({}, [], []) == []
    out = voice_summary({"wpm": 100, "pitch_range_semitones": None}, LINES, [])
    assert out == ["Overall pace was 100 words per minute."]


def test_similar_windows_are_not_reported():
    metrics = {"rate_track": [{"time": 0, "value": 120}, {"time": 30, "value": 130}]}
    assert voice_summary(metrics, LINES, []) == []


def test_untimed_lines_omit_window_lines():
    lines = [{"id": "L1", "start": None, "end": None, "text": "a"}]
    out = voice_summary(METRICS, lines, [])
    assert any("170 wpm" in s and "covering" not in s for s in out)
