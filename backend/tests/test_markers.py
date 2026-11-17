from app.markers import MARKER, plain_timestamp_pattern, resolve, strip_unknown

LINES = [
    {"id": "L1", "start": 1.5, "end": 3.0, "text": "I think the cache is slow."},
    {"id": "L7", "start": 62.0, "end": 66.0, "text": "We use  a hash\nmap for lookups."},
    {"id": "L8", "start": None, "end": None, "text": "No times here."},
]


def refs(parts):
    return [p for p in parts if p["type"] == "ref"]


def test_resolve_bare_and_quoted_marker():
    parts = resolve('Start [[L1]] and [[L1:"cache is slow"]]', LINES)
    assert refs(parts) == [
        {"type": "ref", "line_id": "L1", "start": 1.5, "quote": ""},
        {"type": "ref", "line_id": "L1", "start": 1.5, "quote": "cache is slow"},
    ]


def test_unknown_line_dropped():
    parts = resolve("a [[L99]] b [[L99:\"x\"]] c", LINES)
    assert refs(parts) == []
    assert "".join(p["text"] for p in parts) == "a  b  c"
    assert strip_unknown("a [[L99]] b [[L1]] [[L2:\"q\"]]", LINES) == "a  b [[L1]] "


def test_inexact_quote_falls_back_to_whole_line():
    (ref,) = refs(resolve('[[L1:"the cache is fast"]]', LINES))
    assert ref["quote"] == "I think the cache is slow."


def test_quote_whitespace_and_case_tolerant_but_returns_original():
    (ref,) = refs(resolve('[[L7:"A HASH   MAP"]]', LINES))
    assert ref["quote"] == "a hash\nmap"
    (ref,) = refs(resolve('[[L1:"THE CACHE"]]', LINES))
    assert ref["quote"] == "the cache"


def test_untimed_line_keeps_none_start():
    (ref,) = refs(resolve("[[L8]]", LINES))
    assert ref["start"] is None


def test_text_between_markers_preserved():
    parts = resolve('Said [[L1]], then  [[L7:"hash"]]: ok.', LINES)
    assert [p["type"] for p in parts] == ["text", "ref", "text", "ref", "text"]
    assert [p["text"] for p in parts if p["type"] == "text"] == ["Said ", ", then  ", ": ok."]
    assert resolve("no markers", LINES) == [{"type": "text", "text": "no markers"}]
    assert resolve("", LINES) == []


def test_patterns():
    assert MARKER.search('[[L7:"x y"]]').groups() == ("L7", "x y")
    assert plain_timestamp_pattern.search("at 1:05 he said")
    assert not plain_timestamp_pattern.search("ratio 3 to 4")


def test_lowercase_length_change_does_not_misalign_quote():
    lines = [{"id": "L1", "start": 0.0, "end": 1.0, "text": "Visit İstanbul now and then"}]
    (ref,) = refs(resolve('[[L1:"now"]]', lines))
    assert ref["quote"] == "now"
    (ref,) = refs(resolve('[[L1:"then"]]', lines))
    assert ref["quote"] == "then"
    (ref,) = refs(resolve('[[L1:"İstanbul"]]', lines))
    assert ref["quote"] == "İstanbul"


def test_empty_lines_drops_markers_without_crashing():
    parts = resolve('a [[L1]] b [[L2:"x"]]', [])
    assert refs(parts) == []
    assert "".join(p["text"] for p in parts) == "a  b "
    assert strip_unknown("a [[L1]]", []) == "a "


def test_malformed_marker_stays_literal():
    text = "see [[l7]] and [[L7 ]] and [[L7:\"\"]]"
    assert resolve(text, LINES) == [{"type": "text", "text": text}]


def test_model_range_becomes_two_grounded_links_or_one_known_endpoint():
    assert strip_unknown("[[L1–L7]] [[L1-L99]] [[L7-L7]]", LINES) == "[[L1]]–[[L7]] [[L1]] [[L7]]"
    assert [part["line_id"] for part in refs(resolve("[[L1-L7]]", LINES))] == ["L1", "L7"]
