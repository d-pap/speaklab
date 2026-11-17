"""Short plain-sentence voice summary for model prompts. Values only, no judgements or arrays."""

LONG_PAUSE_SECONDS = 3.0
MAX_LONG_PAUSES = 2
WINDOW_SECONDS = 30
WINDOW_MIN_SPREAD = 0.25


def _lines_covered(lines: list[dict], start: float, end: float) -> str:
    ids = [
        ln["id"]
        for ln in lines
        if ln.get("start") is not None and ln.get("end") is not None and ln["start"] < end and ln["end"] > start
    ]
    if not ids:
        return ""
    return ids[0] if len(ids) == 1 else f"{ids[0]}-{ids[-1]}"


def _window(lines: list[dict], point: dict, label: str) -> str:
    start = point["time"]
    text = f"{label} ({start:g}-{start + WINDOW_SECONDS:g}s) was {point['value']} wpm"
    covered = _lines_covered(lines, start, start + WINDOW_SECONDS)
    return f"{text}, covering {covered}" if covered else text


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def voice_summary(metrics: dict, lines: list[dict], tokens: list[dict]) -> list[str]:
    metrics = metrics or {}
    out: list[str] = []

    pauses = [t for t in tokens if t.get("type") == "pause" and _is_number(t.get("seconds"))]
    if pauses:
        longest = max(pauses, key=lambda t: t["seconds"])
        out.append(f"Longest pause {longest['seconds']:.1f}s before {longest['line_id']}.")
        others = sorted(
            (p for p in pauses if p is not longest and p["seconds"] >= LONG_PAUSE_SECONDS),
            key=lambda p: -p["seconds"],
        )[:MAX_LONG_PAUSES]
        if others:
            out.append(
                " ".join(f"A {p['seconds']:.1f}s pause before {p['line_id']}." for p in others)
            )

    if _is_number(metrics.get("wpm")):
        out.append(f"Overall pace was {round(metrics['wpm'])} words per minute.")

    rates = [r for r in metrics.get("rate_track") or [] if _is_number(r.get("value")) and r["value"] > 0]
    if len(rates) >= 2:
        fast, slow = max(rates, key=lambda r: r["value"]), min(rates, key=lambda r: r["value"])
        if (fast["value"] - slow["value"]) / slow["value"] >= WINDOW_MIN_SPREAD:
            out.append(
                f"{_window(lines, fast, f'Fastest {WINDOW_SECONDS}-second window')}; "
                f"{_window(lines, slow, 'the slowest')}."
            )

    if _is_number(metrics.get("pitch_range_semitones")):
        out.append(f"Pitch range across the recording was {metrics['pitch_range_semitones']:.1f} semitones.")
    if _is_number(metrics.get("loudness_range_db")):
        out.append(f"Loudness range across the recording was {metrics['loudness_range_db']:.1f} dB.")
    return out[:6]
