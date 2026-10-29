"""Exercise the real local inference/API loop using supplied synthetic test audio.

Usage: .venv/bin/python scripts/smoke-inference.py cold.wav learned.wav report.json
Uses a temporary database; never creates entries in normal practice history.
"""
import json
import logging
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

import httpx
from app.config import settings
from app.main import app
from fastapi.testclient import TestClient


def run(cold: Path, learned: Path) -> dict:
    logging.getLogger("speaklab").setLevel(logging.ERROR)
    report = {"kind": "synthetic-speech integration test with real local models", "attempts": []}
    with tempfile.TemporaryDirectory(prefix="speaklab-inference-") as directory:
        settings.data_dir = Path(directory)
        settings.serve_frontend = False
        with TestClient(app, headers={"X-SpeakLab-Client": "1"}) as client:
            created = client.post("/api/sessions", json={"topic_id": "hash-maps"})
            created.raise_for_status()
            sid = created.json()["id"]
            for number, path in enumerate((cold, learned), start=1):
                if number == 2:
                    stage = client.put(f"/api/sessions/{sid}/stage", json={"stage": "record2"})
                    stage.raise_for_status()
                started = time.monotonic()
                saved = client.post(
                    f"/api/sessions/{sid}/attempts/{number}",
                    files={"file": (path.name, path.read_bytes(), "audio/wav")},
                )
                saved.raise_for_status()
                while True:
                    detail = client.get(f"/api/sessions/{sid}").json()
                    attempt = next(a for a in detail["attempts"] if a["number"] == number)
                    if attempt["status"] not in {"pending", "processing"}:
                        break
                    if time.monotonic() - started > 600:
                        raise RuntimeError("Inference exceeded ten minutes.")
                    time.sleep(2)
                result = {
                    "number": number, "elapsed_seconds": round(time.monotonic() - started, 2),
                    "audio_seconds": attempt["duration"], "status": attempt["status"],
                    "errors": attempt["errors"], "transcript": attempt["transcript"],
                    "concepts": attempt["assessment"]["concepts"] if attempt["assessment"] else None,
                    "wpm": attempt["acoustics"].get("wpm") if attempt["acoustics"] else None,
                }
                report["attempts"].append(result)
                print(json.dumps({"attempt": number, "status": result["status"], "seconds": result["elapsed_seconds"]}), flush=True)
                if attempt["status"] != "ready":
                    report["success"] = False
                    return report
                if number == 1:
                    lesson = client.get(f"/api/sessions/{sid}/lesson")
                    lesson.raise_for_status()
                    report["personalized_lesson"] = lesson.json()["personalized"]
                    start = time.monotonic()
                    reply = client.post(f"/api/sessions/{sid}/tutor", json={"message": "Can a hash map ever take linear time, and why?"})
                    reply.raise_for_status()
                    report["tutor_seconds"] = round(time.monotonic() - start, 2)
                    report["tutor"] = reply.json()
            comparison = client.get(f"/api/sessions/{sid}/comparison")
            comparison.raise_for_status()
            report["comparison"] = comparison.json()
            complete = client.post(f"/api/sessions/{sid}/complete", json={"recall": "good"})
            complete.raise_for_status()
            report["review_due"] = complete.json()["review_due"]
            report["success"] = True
    with httpx.Client(trust_env=False, timeout=10) as http:
        report["loaded_models"] = http.get(settings.ollama_url + "/api/ps").json()
    return report


if __name__ == "__main__":
    result = run(Path(sys.argv[1]), Path(sys.argv[2]))
    Path(sys.argv[3]).write_text(json.dumps(result, indent=2))
    print(json.dumps({
        "success": result["success"],
        "attempt_seconds": [a["elapsed_seconds"] for a in result["attempts"]],
        "coverage": [dict(Counter(c["status"] for c in a["concepts"] or [])) for a in result["attempts"]],
        "tutor_seconds": result.get("tutor_seconds"),
        "report": sys.argv[3],
    }), flush=True)
    sys.exit(0 if result["success"] else 1)
