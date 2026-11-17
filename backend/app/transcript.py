"""Transcript lines with stable IDs, inline word/filler/pause tokens and a stats summary."""

import re

from .speech import timed_segments

PAUSE_MIN_SECONDS = 0.5
PAUSE_PLACEMENT_SLOP = 0.15
POSSIBLE_FILLER_TERMS = {"you know", "i mean"}
SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+")


def _norm(word: str) -> str:
    return re.sub(r"^\W+|\W+$", "", word).casefold()


def build_lines(transcript: str, segments: list[dict]) -> list[dict]:
    aligned = timed_segments(transcript, segments)
    if aligned:
        parts = [(s.get("start"), s.get("end"), s["text"].strip()) for s in aligned]
    else:
        parts = [(None, None, s) for s in SENTENCE_BREAK.split(transcript.strip()) if s]
    return [
        {"id": f"L{n}", "start": start, "end": end, "text": text}
        for n, (start, end, text) in enumerate(parts, 1)
    ]


def _line_segment_words(lines: list[dict], segments: list[dict]) -> dict[str, list[dict]]:
    """Map each line ID to the timed words of the segment it came from."""
    result, cursor = {}, 0
    for line in lines:
        if line["start"] is None:
            continue
        for i in range(cursor, len(segments)):
            seg = segments[i]
            if seg.get("start") == line["start"] and seg.get("text", "").strip() == line["text"]:
                result[line["id"]] = seg.get("words") or []
                cursor = i + 1
                break
    return result


def inline_tokens(
    lines: list[dict], segments: list[dict], filler_events: list[dict], audio_pauses: list[dict]
) -> list[dict]:
    seg_words = _line_segment_words(lines, segments)
    # (token, word-derived start used for pause placement)
    entries: list[tuple[dict, float | None]] = []
    stream: list[tuple[int, str]] = []  # (entry index, normalized word) for filler alignment
    for line in lines:
        timed, cursor = seg_words.get(line["id"], []), 0
        for raw in line["text"].split():
            norm = _norm(raw)
            start = None
            for j in range(cursor, len(timed)):
                if _norm(timed[j]["word"]) == norm:
                    start, cursor = timed[j]["start"], j + 1
                    break
            entries.append(({"type": "word", "text": raw, "line_id": line["id"], "start": start}, start))
            stream.append((len(entries) - 1, norm))

    pointer = 0
    for event in sorted(filler_events, key=lambda e: e.get("char_start", 0)):
        if event["kind"] == "hesitation":
            kind = "filler"
        elif event["kind"] == "context-dependent" and event["term"] in POSSIBLE_FILLER_TERMS:
            kind = "possible_filler"
        else:
            continue
        target = [_norm(w) for w in event["text"].split()]
        for at in range(pointer, len(stream) - len(target) + 1):
            if [n for _, n in stream[at : at + len(target)]] == target:
                first = stream[at][0]
                token, word_start = entries[first]
                token.update(
                    type=kind,
                    text=event["text"],
                    start=word_start if word_start is not None else event.get("start"),
                )
                for idx, _ in stream[at + 1 : at + len(target)]:
                    entries[idx] = (None, None)  # type: ignore[assignment]
                pointer = at + len(target)
                break
    entries = [e for e in entries if e[0] is not None]

    has_word_timing = any(start is not None for _, start in entries)
    has_line_timing = any(line["start"] is not None for line in lines)
    pauses = sorted(
        (
            (p["start"] + p["duration"], round(p["duration"], 1))
            for p in audio_pauses
            if p["duration"] >= PAUSE_MIN_SECONDS
        )
    )
    inserts: dict[int, list[dict]] = {}
    for end, seconds in pauses:
        threshold = end - PAUSE_PLACEMENT_SLOP
        if has_word_timing:
            at = next((i for i, (_, s) in enumerate(entries) if s is not None and s >= threshold), None)
        elif has_line_timing:
            line = next((ln for ln in lines if ln["start"] is not None and ln["start"] >= threshold), None)
            at = next((i for i, (t, _) in enumerate(entries) if line and t["line_id"] == line["id"]), None)
        else:
            at = None
        if at is not None:
            inserts.setdefault(at, []).append(
                {"type": "pause", "seconds": seconds, "line_id": entries[at][0]["line_id"]}
            )

    tokens: list[dict] = []
    for i, (token, _) in enumerate(entries):
        tokens.extend(inserts.get(i, []))
        tokens.append(token)
    return tokens


def stats(tokens: list[dict], duration: float) -> dict:
    pauses = [t["seconds"] for t in tokens if t["type"] == "pause"]
    return {
        "duration": duration,
        "fillers": sum(t["type"] == "filler" for t in tokens),
        "possible_fillers": sum(t["type"] == "possible_filler" for t in tokens),
        "pauses_over_1s": sum(s >= 1.0 for s in pauses),
        "longest_pause": max(pauses) if pauses else None,
    }
