"""Local, reproducible speech observations; no inferred emotions or vocabulary scores."""

import math
import re
from collections import Counter

WORD = re.compile(r"\b[\w]+(?:['’-][\w]+)*\b")
HESITATION = re.compile(r"\b(?:u+m+|u+h+|e+r+m+|h+m+)\b", re.I)
CANDIDATE = re.compile(r"\b(?:you know|i mean|like|basically|actually|so|right)\b", re.I)


def timed_segments(text: str, segments: list[dict]) -> list[dict]:
    """Attach character offsets only when a segment actually occurs in the transcript."""
    result, cursor = [], 0
    for seg in segments:
        phrase = seg["text"].strip()
        at = text.find(phrase, cursor)
        if phrase and at >= 0:
            result.append({**seg, "char_start": at, "char_end": at + len(phrase)})
            cursor = at + len(phrase)
    return result


def speech_observations(text: str, duration: float, segments: list[dict]) -> dict:
    aligned = timed_segments(text, segments)
    events = []
    for pattern, kind in ((HESITATION, "hesitation"), (CANDIDATE, "context-dependent")):
        for match in pattern.finditer(text):
            segment = next((s for s in aligned if s["char_start"] <= match.start() < s["char_end"]), None)
            start = segment["start"] if segment else None
            timing = "segment" if segment else "unavailable"
            if segment:
                cursor = segment["char_start"]
                for word in segment.get("words", []):
                    phrase = word["word"].strip()
                    at = text.find(phrase, cursor, segment["char_end"])
                    if at < 0 or not phrase:
                        continue
                    cursor = at + len(phrase)
                    if at <= match.start() < cursor:
                        start, timing = word["start"], "estimated-word"
                        break
            raw = match.group()
            term = raw.casefold()
            if kind == "hesitation":
                term = (
                    "um"
                    if re.fullmatch("u+m+", term)
                    else "uh"
                    if re.fullmatch("u+h+", term)
                    else "erm"
                    if term.startswith("er")
                    else "hmm"
                )
            events.append(
                {
                    "term": term,
                    "text": raw,
                    "kind": kind,
                    "char_start": match.start(),
                    "char_end": match.end(),
                    "start": start,
                    "timing": timing,
                }
            )
    events.sort(key=lambda e: e["char_start"])
    counts = Counter(e["term"] for e in events if e["kind"] == "hesitation")
    candidates = Counter(e["term"] for e in events if e["kind"] == "context-dependent")
    repetitions = [
        {"text": m.group(), "char_start": m.start(), "char_end": m.end()}
        for m in re.finditer(r"\b(\w+)(?:[ ,—-]+\1\b)+", text, re.I)
    ]
    return {
        "fillers": dict(counts.most_common()),
        "filler_count": sum(counts.values()),
        "fillers_per_minute": round(sum(counts.values()) * 60 / duration, 1) if duration else None,
        "filler_candidates": dict(candidates.most_common()),
        "filler_events": events,
        "repetitions": repetitions,
        "analysis_version": 2,
        "note": "Counts cover detected transcribed hesitations, not every sound you made. Words such as “like” and “you know” are context-dependent candidates, excluded from the total. Word times are model estimates; segment links point to the start of the containing segment. Repetitions can be intentional. WPM includes pauses.",
        "readability": readability(text),
    }


def syllables(word: str) -> int:
    word = re.sub("[^a-z]", "", word.lower())
    groups = len(re.findall("[aeiouy]+", word))
    if word.endswith("e") and not word.endswith(("le", "ye")) and groups > 1:
        groups -= 1
    return max(1, groups)


def readability(text: str) -> dict:
    cleaned = HESITATION.sub("", text)
    words = WORD.findall(cleaned)
    sentences = [s for s in re.split(r"[.!?]+", cleaned) if WORD.search(s)]
    result = {
        "available": len(words) >= 100 and len(sentences) >= 3,
        "words": len(words),
        "sentences": len(sentences),
        "method": "Approximate Flesch–Kincaid US grade: 0.39 × words/sentences + 11.8 × estimated syllables/words − 15.59.",
        "basis": "Calculated on a separate copy with detected um/uh/erm/hmm removed. Repetitions and meaningful words remain. The original transcript is unchanged.",
        "limitation": "Experimental text readability, not a vocabulary or intelligence score. Speech fragments, ASR punctuation, acronyms and heuristic syllable counts can distort the result. Higher is not better.",
    }
    if result["available"]:
        grade = (
            0.39 * len(words) / len(sentences) + 11.8 * sum(syllables(w) for w in words) / len(words) - 15.59
        )
        result["grade_band"] = [max(0, math.floor(grade) - 1), max(1, math.ceil(grade) + 1)]
    else:
        result["reason"] = (
            "Needs at least 100 words and three punctuated sentences for even a rough estimate."
        )
    stop = {
        "the",
        "a",
        "an",
        "and",
        "or",
        "to",
        "of",
        "in",
        "is",
        "it",
        "that",
        "this",
        "i",
        "you",
        "we",
        "they",
        "so",
        "are",
        "be",
        "with",
        "for",
        "on",
        "as",
        "can",
        "have",
        "will",
        "but",
        "not",
        "your",
        "its",
        "if",
        "what",
        "which",
        "then",
    }
    result["repeated_words"] = [
        {"word": w, "count": n}
        for w, n in Counter(w.casefold() for w in words if w.casefold() not in stop).most_common(6)
        if n >= 3
    ]
    return result


def vocal_foundations(metrics: dict, style: str) -> list[dict]:
    windows = metrics.get("delivery_windows", [])
    rates = [p for p in metrics.get("rate_track", []) if p["value"] is not None]
    pitch = [w for w in windows if w.get("pitch_range_semitones") is not None]
    volume = [w for w in windows if w.get("loudness_range_db") is not None]
    quietest = min(volume, key=lambda w: w["loudness_range_db"]) if volume else None
    narrowest = min(pitch, key=lambda w: w["pitch_range_semitones"]) if pitch else None
    fastest = max(rates, key=lambda w: w["value"]) if rates else None
    pauses = metrics.get("pauses", [])
    longest = max(pauses, key=lambda p: p["duration"]) if pauses else None

    def card(name, observation, practice, marker=None):
        return {
            "foundation": name,
            "observation": observation,
            "practice": practice,
            "start": marker.get("start", marker.get("time")) if marker else None,
            "basis": "Measured audio / transcript timing; interpretation is tentative.",
        }

    return [
        card(
            "Rate",
            f"Overall {metrics['wpm']} words/minute, including pauses."
            if metrics.get("wpm") is not None
            else "Speaking rate needs a transcript.",
            f"For your {style.lower()} delivery, replay the fastest measured window. Try slowing only the key explanation, then return to your natural pace. Faster is not automatically worse.",
            fastest,
        ),
        card(
            "Volume",
            f"The least varied measured 15-second window has a {quietest['loudness_range_db']} dB P10–P90 spread."
            if quietest
            else "Not enough active audio to compare local volume variation.",
            "Choose one important phrase and try a gentle volume contrast. Compare the recordings; microphone gain and automatic processing can conceal or exaggerate changes.",
            quietest,
        ),
        card(
            "Pitch & melody",
            f"The narrowest usable window has a {narrowest['pitch_range_semitones']} semitone P10–P90 spread."
            if narrowest
            else "Not enough reliably tracked voiced audio for a local pitch comparison.",
            "Replay this passage and listen for purposeful emphasis. Try stressing a different word in the same sentence. An optional gentle siren glide is a warm-up, not a target pitch range; avoid strain. A narrow range alone does not prove monotone delivery.",
            narrowest,
        ),
        card(
            "Pauses",
            f"{metrics.get('pause_count', 0)} internal energy gaps of at least 0.3s; {metrics.get('pause_seconds', 0)}s total."
            if "pause_count" in metrics
            else "Pause measurements are unavailable.",
            "Listen at the marked gap, or choose the end of a complex idea. Try a deliberate pause so the listener can process it. Keep a filler if it serves a purpose; silence is not always preferable.",
            longest,
        ),
        card(
            "Intended tonality",
            "Audio measurements cannot establish your emotion, facial expression, or how an audience feels.",
            f"Choose an intention within your {style.lower()} style—curious, reassuring, or matter-of-fact. Say the same sentence two ways, optionally changing your facial expression, then listen and choose the delivery that matches your meaning.",
        ),
    ]
