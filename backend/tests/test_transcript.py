from app import speech, transcript


def _words(*pairs):
    return [{"word": w, "start": s, "end": s + 0.2} for w, s in pairs]


def _events(text, segments=None):
    return speech.speech_observations(text, 10.0, segments or [])["filler_events"]


def test_lines_follow_segments():
    text = "First part here. Second part there."
    segments = [
        {"start": 0.0, "end": 2.0, "text": " First part here."},
        {"start": 2.5, "end": 4.0, "text": " Second part there."},
    ]
    lines = transcript.build_lines(text, segments)
    assert [line["id"] for line in lines] == ["L1", "L2"]
    assert [line["start"] for line in lines] == [0.0, 2.5]
    assert lines[1]["end"] == 4.0
    assert lines[0]["text"] == "First part here."
    assert lines == transcript.build_lines(text, segments)


def test_edited_transcript_builds_untimed_lines():
    lines = transcript.build_lines("One. Two? Three!", [])
    assert [line["id"] for line in lines] == ["L1", "L2", "L3"]
    assert all(line["start"] is None and line["end"] is None for line in lines)
    assert [line["text"] for line in lines] == ["One.", "Two?", "Three!"]
    assert transcript.inline_tokens(lines, [], [], [{"start": 1.0, "duration": 2.0}]) == [
        {"type": "word", "text": t, "line_id": f"L{i}", "start": None}
        for i, t in enumerate(["One.", "Two?", "Three!"], 1)
    ]


def _timed():
    text = "Alpha beta. Gamma delta."
    segments = [
        {"start": 0.0, "end": 1.0, "text": "Alpha beta.", "words": _words(("Alpha", 0.0), ("beta.", 0.5))},
        {"start": 1.8, "end": 3.0, "text": "Gamma delta.", "words": _words(("Gamma", 1.8), ("delta.", 2.3))},
    ]
    return text, segments


def test_audio_pause_placed_before_next_word():
    text, segments = _timed()
    lines = transcript.build_lines(text, segments)
    tokens = transcript.inline_tokens(
        lines, segments, [], [{"start": 1.0, "duration": 0.8}, {"start": 2.0, "duration": 0.3}]
    )
    kinds = [t["type"] for t in tokens]
    assert kinds == ["word", "word", "pause", "word", "word"]
    assert tokens[2] == {"type": "pause", "seconds": 0.8, "line_id": "L2"}
    assert tokens[3]["text"] == "Gamma" and tokens[3]["start"] == 1.8


def test_audio_pause_falls_back_to_line_start_without_word_timings():
    segments = [
        {"start": 0.0, "end": 1.0, "text": "Alpha beta."},
        {"start": 1.8, "end": 3.0, "text": "Gamma delta."},
    ]
    lines = transcript.build_lines("Alpha beta. Gamma delta.", segments)
    tokens = transcript.inline_tokens(lines, segments, [], [{"start": 1.0, "duration": 0.8}])
    assert [t["type"] for t in tokens] == ["word", "word", "pause", "word", "word"]
    assert tokens[2]["line_id"] == "L2"


def test_fillers_inline_and_counted():
    text = "so, the, uh, you know, if"
    events = _events(text)
    lines = transcript.build_lines(text, [])
    tokens = transcript.inline_tokens(lines, [], events, [])
    fillers = [t for t in tokens if t["type"] == "filler"]
    possible = [t for t in tokens if t["type"] == "possible_filler"]
    assert [t["text"] for t in fillers] == ["uh"]
    assert [t["text"] for t in possible] == ["you know"]
    assert [t["text"] for t in tokens if t["type"] == "word"] == ["so,", "the,", "if"]
    stats = transcript.stats(tokens, 10.0)
    assert stats["fillers"] == 1 and stats["possible_fillers"] == 1


def test_filler_uses_word_time_and_other_candidates_stay_words():
    text = "I like uh tests."
    segments = [
        {
            "start": 0.0,
            "end": 2.0,
            "text": text,
            "words": _words(("I", 0.0), ("like", 0.3), ("uh", 0.9), ("tests.", 1.3)),
        },
    ]
    lines = transcript.build_lines(text, segments)
    tokens = transcript.inline_tokens(lines, segments, _events(text, segments), [])
    assert [(t["type"], t["start"]) for t in tokens] == [
        ("word", 0.0),
        ("word", 0.3),
        ("filler", 0.9),
        ("word", 1.3),
    ]


def test_stats_longest_pause():
    tokens = [
        {"type": "pause", "seconds": 0.6, "line_id": "L1"},
        {"type": "pause", "seconds": 1.4, "line_id": "L1"},
        {"type": "pause", "seconds": 1.0, "line_id": "L2"},
    ]
    assert transcript.stats(tokens, 12.5) == {
        "duration": 12.5,
        "fillers": 0,
        "possible_fillers": 0,
        "pauses_over_1s": 2,
        "longest_pause": 1.4,
    }
    assert transcript.stats([], 3.0)["longest_pause"] is None
