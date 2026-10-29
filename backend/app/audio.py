import re
import subprocess
from pathlib import Path

import imageio_ffmpeg
import numpy as np
import soundfile as sf


def detect_container(data: bytes) -> tuple[str, str]:
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return ".wav", "audio/wav"
    if data[:4] == b"\x1aE\xdf\xa3":
        return ".webm", "audio/webm"
    if data[:4] == b"OggS":
        return ".ogg", "audio/ogg"
    if data[4:8] == b"ftyp":
        return ".mp4", "audio/mp4"
    raise ValueError("Use a browser recording or a WAV, WebM, Ogg, or MP4 audio file.")


def decode(source: Path, target: Path) -> float:
    """No shell, remote protocols, or user filenames. Limit decoded output to six minutes."""
    try:
        result = subprocess.run(
            [
                imageio_ffmpeg.get_ffmpeg_exe(),
                "-nostdin",
                "-v",
                "error",
                "-y",
                "-protocol_whitelist",
                "file,pipe",
                "-i",
                str(source),
                "-map",
                "0:a:0",
                "-vn",
                "-t",
                "361",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "pcm_s16le",
                str(target),
            ],
            check=False,
            capture_output=True,
            timeout=45,
        )
        if result.returncode:
            raise ValueError(
                "This file could not be decoded as audio. Try recording again or use a WAV file."
            )
        duration = sf.info(target).duration
        if not 0.5 <= duration <= 360:
            raise ValueError("Recordings must be between half a second and six minutes.")
        return duration
    except subprocess.TimeoutExpired as exc:
        raise ValueError("Audio decoding timed out; try a smaller recording.") from exc


def _runs(mask: np.ndarray, value: bool) -> list[tuple[int, int]]:
    padded = np.r_[False, mask == value, False].astype(int)
    edges = np.diff(padded)
    return list(zip(np.where(edges == 1)[0].tolist(), np.where(edges == -1)[0].tolist()))


def acoustic_features(path: Path) -> dict:
    y, sr = sf.read(path, dtype="float32")
    if y.ndim > 1:
        y = y.mean(axis=1)
    frame, hop = int(sr * 0.03), int(sr * 0.01)
    windows = np.lib.stride_tricks.sliding_window_view(y, frame)[::hop]
    rms = np.sqrt(np.mean(windows**2, axis=1))
    db = 20 * np.log10(np.maximum(rms, 1e-6))
    threshold = max(-48.0, float(np.percentile(db, 90)) - 28.0)
    active = db > threshold
    # Bridge tiny unvoiced gaps; this remains an energy heuristic, not linguistic VAD.
    for start, end in _runs(active, False):
        if start > 0 and end < len(active) and end - start < 15:
            active[start:end] = True
    active_indices = np.flatnonzero(active)
    pauses = []
    if len(active_indices):
        first, last = int(active_indices[0]), int(active_indices[-1])
        for start, end in _runs(active, False):
            if end - start >= 30 and start > first and end <= last:
                pauses.append({"start": round(start * 0.01, 2), "duration": round((end - start) * 0.01, 2)})
    duration = len(y) / sr
    voiced_db = db[active]
    result = {
        "duration": round(duration, 2),
        "active_fraction": round(float(active.mean()), 3),
        "pause_count": len(pauses),
        "pauses": pauses,
        "pause_seconds": round(sum(p["duration"] for p in pauses), 2),
        "extended_silences": [
            {"start": round(s * 0.01, 2), "duration": round((e - s) * 0.01, 2)}
            for s, e in _runs(active, False)
            if e - s >= 200
        ],
        "loudness_dbfs": round(float(20 * np.log10(max(float(np.sqrt(np.mean(y**2))), 1e-6))), 1),
        "loudness_range_db": round(float(np.percentile(voiced_db, 90) - np.percentile(voiced_db, 10)), 1)
        if len(voiced_db)
        else None,
        "clipping_fraction": round(float((np.abs(y) >= 0.99).mean()), 4),
        "loudness_track": [
            {"time": round(i * 0.01, 2), "value": round(float(db[i]), 1)} for i in range(0, len(db), 10)
        ],
        "pitch_track": [],
        "pitch_median_hz": None,
        "pitch_range_semitones": None,
        "acoustic_version": 2,
        "delivery_windows": [],
        "limitations": [
            "Energy-based activity may count noise as speech and miss soft sounds. Pauses are gaps of at least 0.3 seconds between active regions.",
            "Loudness is relative dBFS, not calibrated sound pressure. Microphone gain and automatic processing affect comparisons.",
            "Pitch estimates can miss or mis-track voices. These measurements do not establish emotion, confidence, or engagement.",
        ],
    }
    try:
        import parselmouth

        pitch = parselmouth.Sound(y.astype(float), sampling_frequency=sr).to_pitch_ac(
            time_step=0.05, pitch_floor=60, pitch_ceiling=500
        )
        frequencies = pitch.selected_array["frequency"]
        valid = frequencies[frequencies > 0]
        result["pitch_track"] = [
            {"time": round(float(t), 2), "value": round(float(f), 1) if f else None}
            for t, f in zip(pitch.xs(), frequencies)
        ]
        if len(valid) >= 10:
            result["pitch_median_hz"] = round(float(np.median(valid)), 1)
            result["pitch_range_semitones"] = round(
                float(12 * np.log2(np.percentile(valid, 90) / np.percentile(valid, 10))), 1
            )
    except (ImportError, RuntimeError, ValueError):
        result["limitations"].append("Pitch estimation was unavailable for this recording.")
    for start in range(0, int(duration), 15):
        end = min(start + 15, duration)
        if end - start < 3:
            continue
        levels = db[int(start * 100) : int(end * 100)]
        activity = active[int(start * 100) : int(end * 100)]
        levels = levels[activity]
        pitches = [p["value"] for p in result["pitch_track"] if start <= p["time"] < end and p["value"]]
        result["delivery_windows"].append(
            {
                "start": start,
                "end": end,
                "loudness_range_db": round(float(np.percentile(levels, 90) - np.percentile(levels, 10)), 1)
                if len(levels) >= 100
                else None,
                "pitch_range_semitones": round(
                    float(12 * np.log2(np.percentile(pitches, 90) / np.percentile(pitches, 10))), 1
                )
                if len(pitches) >= 20
                else None,
            }
        )
    return result


def transcript_metrics(text: str, duration: float, segments: list[dict] | None) -> dict:
    words = re.findall(r"\b[\w]+(?:['’-][\w]+)*\b", text)
    fillers = {
        term: len(re.findall(r"\b" + term + r"\b", text, re.I))
        for term in ("um", "uh", "erm", "er", "you know", "i mean")
    }
    fillers = {k: v for k, v in fillers.items() if v}
    rates = []
    if segments:
        for start in range(0, int(duration), 30):
            end = min(start + 30, duration)
            count = 0.0
            for seg in segments:
                length = seg["end"] - seg["start"]
                if length <= 0:
                    continue
                overlap = max(0, min(end, seg["end"]) - max(start, seg["start"]))
                count += len(re.findall(r"\b\w+\b", seg["text"])) * overlap / length
            rates.append({"time": start, "value": round(count / (end - start) * 60)})
    return {
        "word_count": len(words),
        "wpm": round(len(words) / duration * 60) if duration else None,
        "fillers": fillers,
        "filler_count": sum(fillers.values()),
        "rate_track": rates,
        "note": "WPM includes pauses. Segment rates are estimates from segment timestamps. Transcription may omit fillers; 'like' is excluded because its meaning is ambiguous.",
    }


def delivery_suggestions(metrics: dict, style: str) -> list[str]:
    suggestions = []
    if metrics.get("clipping_fraction", 0) > 0.01:
        suggestions.append(
            "The signal clips in places. Move slightly away from the microphone or reduce input gain before judging vocal dynamics."
        )
    if metrics.get("extended_silences"):
        suggestions.append(
            "Replay the marked long silences. Decide which pauses help the listener and where you could use a brief transition instead."
        )
    if metrics.get("filler_count", 0) > 0:
        suggestions.append(
            "Listen to one detected filler phrase. If it distracts from your point, rehearse replacing it with a short intentional pause."
        )
    if len(suggestions) < 3:
        suggestions.append(
            f"For your {style.lower()} style, choose one important sentence and try two deliveries. Listen for which version makes its meaning easier to follow."
        )
    return suggestions[:3]
