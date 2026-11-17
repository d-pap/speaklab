"""Exercise the real local inference/API loop using supplied synthetic test audio.

Usage: .venv/bin/python scripts/smoke-inference.py cold.wav learned.wav report.json
Uses a temporary database; never creates entries in normal practice history.

It drives only the current pipeline on one topic thread: record attempt 1, send a learner
note, wait for the passes and the review, chat once through the SSE endpoint, record attempt 2,
skip its note and wait again. Attempt 2's review compares with attempt 1's. The report lists, per attempt, each pass's status, model and seconds, the
review structure, the first 1,500 characters of the review message and the chat reply.
"""
import json
import logging
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

import httpx
from app import db
from app.config import settings
from app.main import app
from fastapi.testclient import TestClient

PASSES = ("memory", "technical", "communication", "writer")
FINISHED = {"done", "failed", "skipped"}
POLL_SECONDS = 0.5
TIMEOUT_SECONDS = 900
TOPIC = "hash-maps"
CHAT_QUESTION = "What would a senior engineer say?"
NOTE = "I felt rushed near the end and wasn't sure about the collision part."


def thread(client: TestClient) -> dict:
    response = client.get(f"/api/topics/{TOPIC}/thread")
    response.raise_for_status()
    return response.json()


def attempt_of(client: TestClient, number: int) -> dict:
    return next(a for a in thread(client)["attempts"] if a["number"] == number)


def open_next_attempt(sid: str) -> None:
    """The next attempt opens the day after the latest one. The harness records both in one
    sitting, so it moves the thread's attempts back a day in its temporary database. This
    bypasses the next-day rule on purpose; the rule itself is covered by unit tests."""
    for row in db.all_rows("SELECT id, created_at FROM attempts WHERE session_id=?", (sid,)):
        earlier = datetime.fromisoformat(row["created_at"]) - timedelta(days=1)
        db.execute("UPDATE attempts SET created_at=? WHERE id=?", (earlier.isoformat(), row["id"]))


def wait_for_review(client: TestClient, number: int, started: float) -> tuple[dict, dict]:
    """Poll until the attempt is idle and its writer finished (or a pass failed).

    Pass seconds come from polling: first time a pass is seen running to the first time it is
    seen finished, so they are accurate to about POLL_SECONDS and include queue time."""
    first_running: dict[str, float] = {}
    seconds: dict[str, float | None] = {name: None for name in PASSES}
    while True:
        attempt = attempt_of(client, number)
        now = time.monotonic()
        passes = (attempt["analysis"] or {}).get("passes", {})
        for name in PASSES:
            status = passes.get(name, {}).get("status")
            if status == "running":
                first_running.setdefault(name, now)
            if status in FINISHED and seconds[name] is None:
                seconds[name] = round(now - first_running.get(name, now), 2)
        idle = attempt["status"] not in {"pending", "processing"}
        writer = passes.get("writer", {}).get("status")
        failed = any(p.get("status") == "failed" for p in passes.values())
        if idle and attempt["analysis"] and (writer in FINISHED or failed):
            return attempt, seconds
        if idle and not attempt["analysis"]:
            return attempt, seconds  # nothing to wait for: no transcript, no analysis
        if now - started > TIMEOUT_SECONDS:
            raise RuntimeError("Inference exceeded fifteen minutes.")
        time.sleep(POLL_SECONDS)


def chat_once(client: TestClient, sid: str, number: int) -> dict:
    started = time.monotonic()
    response = client.post(
        f"/api/sessions/{sid}/chat", json={"message": CHAT_QUESTION, "attempt_number": number}
    )
    response.raise_for_status()
    events = [
        json.loads(chunk[len("data: "):]) for chunk in response.text.split("\n\n") if chunk.startswith("data: ")
    ]
    final = next((e for e in events if e.get("done") or e.get("error")), {})
    message = final.get("message") or {}
    return {
        "question": CHAT_QUESTION,
        "seconds": round(time.monotonic() - started, 2),
        "chunks": sum(1 for e in events if "delta" in e),
        "error": final.get("error"),
        "reply": message.get("content"),
        "model": message.get("model"),
        "warning": final.get("warning"),
    }


def review_structure(attempt: dict) -> dict | None:
    review = (attempt["analysis"] or {}).get("review")
    if not review:
        return None
    return {
        "too_short": bool(review.get("too_short")),
        "scores": [
            {"name": s["name"], "score": s["score"], "reason": s["reason"]} for s in review.get("scores", [])
        ],
        "key_points": len(review.get("key_points", [])),
        "checklist": review.get("checklist"),
        "comparison": review.get("comparison"),
    }


def run(cold: Path, learned: Path) -> dict:
    logging.getLogger("speaklab").setLevel(logging.ERROR)
    report = {
        "kind": "synthetic-speech integration test with real local models",
        "attempts": [],
        "success": False,
    }
    with tempfile.TemporaryDirectory(prefix="speaklab-inference-") as directory:
        settings.data_dir = Path(directory)
        settings.serve_frontend = False
        with TestClient(app, headers={"X-SpeakLab-Client": "1"}) as client:
            sid = None
            for number, path in enumerate((cold, learned), start=1):
                if number == 2:
                    open_next_attempt(sid)
                started = time.monotonic()
                uploaded = client.post(
                    f"/api/topics/{TOPIC}/attempts",
                    files={"file": (path.name, path.read_bytes(), "audio/wav")},
                )
                uploaded.raise_for_status()
                sid = uploaded.json()["session_id"]  # the thread is created with attempt 1
                # Attempt 1 gets a written note, attempt 2 a skip; both are picked up by phase 1
                # or the writer, whichever is running when they arrive.
                note = {"text": NOTE} if number == 1 else {"skip": True}
                attempt_id = uploaded.json()["id"]
                client.post(f"/api/attempts/{attempt_id}/note", json=note).raise_for_status()
                attempt, seconds = wait_for_review(client, number, started)
                passes = (attempt["analysis"] or {}).get("passes", {})
                review_message = next(
                    (
                        m["content"]
                        for m in thread(client)["messages"]
                        if m["kind"] == "review" and m["attempt_number"] == number
                    ),
                    None,
                )
                result = {
                    "number": number,
                    "elapsed_seconds": round(time.monotonic() - started, 2),
                    "audio_seconds": attempt["duration"],
                    "status": attempt["status"],
                    "errors": attempt["errors"],
                    "transcript": attempt["transcript"],
                    "wpm": attempt["acoustics"].get("wpm") if attempt["acoustics"] else None,
                    "passes": {
                        name: {
                            "status": passes.get(name, {}).get("status"),
                            "model": passes.get(name, {}).get("model"),
                            "seconds": seconds[name],
                        }
                        for name in PASSES
                    },
                    "review_structure": review_structure(attempt),
                    "review_message": review_message[:1500] if review_message else None,
                }
                report["attempts"].append(result)
                print(
                    json.dumps({"attempt": number, "status": result["status"], "seconds": result["elapsed_seconds"]}),
                    flush=True,
                )
                if attempt["status"] != "ready" or not review_message:
                    return report
                if number == 1:
                    report["chat"] = chat_once(client, sid, 1)
                    print(json.dumps({"chat_seconds": report["chat"]["seconds"]}), flush=True)
                    if report["chat"]["error"]:
                        return report
            final = thread(client)
            report["attempt_count"] = len(final["attempts"])
            report["recording"] = final["recording"]
            report["review_due"] = (db.one("SELECT due FROM reviews WHERE topic_id=?", (TOPIC,)) or {}).get("due")
            report["success"] = True
    with httpx.Client(trust_env=False, timeout=10) as http:
        report["loaded_models"] = http.get(settings.ollama_url + "/api/ps").json()
    return report


if __name__ == "__main__":
    result = run(Path(sys.argv[1]), Path(sys.argv[2]))
    Path(sys.argv[3]).write_text(json.dumps(result, indent=2))
    print(
        json.dumps(
            {
                "success": result["success"],
                "attempt_seconds": [a["elapsed_seconds"] for a in result["attempts"]],
                "pass_status": [{n: p["status"] for n, p in a["passes"].items()} for a in result["attempts"]],
                "chat_seconds": (result.get("chat") or {}).get("seconds"),
                "report": sys.argv[3],
            }
        ),
        flush=True,
    )
    sys.exit(0 if result["success"] else 1)
