import io
import json
import threading
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta

import httpx
import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from app import llm, models, pipeline
from app.config import settings
from app.main import app

TRANSCRIPT = "A hash map stores keys and values. A hash selects a bucket. Collisions need key comparisons."


@pytest.fixture
def wav_bytes():
    sr = 16000
    t = np.arange(sr) / sr
    signal = 0.25 * np.sin(2 * np.pi * 220 * t)
    y = np.r_[signal, np.zeros(int(sr * 0.6)), signal]
    buffer = io.BytesIO()
    sf.write(buffer, y, sr, format="WAV", subtype="PCM_16")
    return buffer.getvalue()


class HeldTimer:
    """Stands in for threading.Timer: records the note timeout instead of running it."""

    started: list["HeldTimer"]

    def __init__(self, interval, function, args=None, kwargs=None):
        self.interval, self.function = interval, function
        self.args, self.kwargs = args or (), kwargs or {}
        self.daemon = False

    def start(self):
        self.started.append(self)

    def cancel(self):
        pass


@pytest.fixture
def client(tmp_path, monkeypatch, fake_llm):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "ollama_model", settings.ollama_model)
    monkeypatch.setattr(pipeline, "submit", pipeline.process)
    monkeypatch.setattr(pipeline, "submit_writer", pipeline.write)
    timers: list[HeldTimer] = []
    monkeypatch.setattr(HeldTimer, "started", timers, raising=False)
    monkeypatch.setattr(threading, "Timer", HeldTimer)
    monkeypatch.setattr(
        models,
        "transcribe",
        lambda path, duration: (TRANSCRIPT, [{"start": 0, "end": 2.6, "text": TRANSCRIPT}]),
    )
    fake_llm.defaults.update(minimal_replies())
    with TestClient(app, headers={"X-SpeakLab-Client": "1"}) as client:
        client.note_timers = timers
        yield client


def upload(client, wav_bytes, topic_id="hash-maps", **form):
    """Record an attempt on the topic's thread; form fields (prompt_kind, style, duration) are optional."""
    response = client.post(
        f"/api/topics/{topic_id}/attempts",
        files={"file": ("../../unsafe.wav", wav_bytes, "audio/wav")},
        data={k: str(v) for k, v in form.items()},
    )
    assert response.status_code == 201, response.text
    return response.json()


def get_thread(client, topic_id="hash-maps"):
    response = client.get(f"/api/topics/{topic_id}/thread")
    assert response.status_code == 200, response.text
    return response.json()


def next_day(session_id, days=1):
    """Move the thread's attempts back in time, as if `days` had passed: the next attempt opens."""
    from app import db

    with db.connect() as conn:
        for row in conn.execute("SELECT id, created_at FROM attempts WHERE session_id=?", (session_id,)).fetchall():
            shifted = datetime.fromisoformat(row["created_at"]) - timedelta(days=days)
            conn.execute("UPDATE attempts SET created_at=? WHERE id=?", (shifted.isoformat(), row["id"]))


@dataclass
class Reply:
    """A model reply with an explicit Ollama done_reason, e.g. Reply("...", "length")."""

    content: object
    done_reason: str = "stop"


class FakeLLM:
    """Model double behind the real `llm` entry points; see the `fake_llm` fixture."""

    def __init__(self):
        self.queues: dict[str, deque] = defaultdict(deque)
        self.defaults: dict[str, object] = {}
        self.requests: list[dict] = []
        self.unexpected: list[str] = []
        self._current = threading.local()

    def queue(self, pass_name: str, *responses):
        self.queues[pass_name].extend(responses)

    def requests_for(self, pass_name: str) -> list[dict]:
        return [r for r in self.requests if r["pass"] == pass_name]

    def _handle(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/show":
            return httpx.Response(200, json={"details": {}})
        if request.method != "POST" or request.url.path != "/api/chat":
            # Not a model call (e.g. health or model listing): answer benignly, consume nothing.
            return httpx.Response(200, json={"models": []} if request.url.path == "/api/tags" else {})
        body = json.loads(request.content)
        pass_name = getattr(self._current, "pass_name", None)
        try:
            payload = json.loads(next(m["content"] for m in body["messages"] if m["role"] == "user"))
        except (StopIteration, ValueError):
            payload = None
        record = {"pass": pass_name, "messages": body["messages"], "payload": payload, "body": body}
        self.requests.append(record)
        if self.queues[pass_name]:
            response = self.queues[pass_name].popleft()
        elif pass_name in self.defaults:
            response = self.defaults[pass_name]
        else:
            # Recorded as well as raised: the pipeline's broad except would otherwise hide it.
            message = f"Unexpected {pass_name!r} model call; queue a response first."
            self.unexpected.append(message)
            raise AssertionError(message)
        if callable(response):
            response = response(record)
        if isinstance(response, BaseException):
            raise response
        if isinstance(response, httpx.Response):
            return response
        reply = response if isinstance(response, Reply) else Reply(response)
        content = reply.content if isinstance(reply.content, str) else json.dumps(reply.content)
        data = {"message": {"content": content}, "done": True, "done_reason": reply.done_reason}
        if body.get("stream"):
            return httpx.Response(200, content=json.dumps(data) + "\n")
        return httpx.Response(200, json=data)

    def _tag(self, original):
        def wrapped(pass_name, *args, **kwargs):
            self._current.pass_name = pass_name
            try:
                return original(pass_name, *args, **kwargs)
            finally:
                self._current.pass_name = None

        return wrapped

    def _tag_stream(self, original):
        # Keyword arguments (e.g. llm.stream_call's result=) pass straight through.
        def wrapped(pass_name, *args, **kwargs):
            self._current.pass_name = pass_name  # runs at first next(), right before the request
            try:
                yield from original(pass_name, *args, **kwargs)
            finally:
                self._current.pass_name = None

        return wrapped


@pytest.fixture
def fake_llm(tmp_path, monkeypatch):
    """Scripted local model for every pass, with the real `llm` code path in between.

    It replaces the HTTP transport (`models.transport`) and wraps `llm.structured_call`,
    `llm.text_call` and `llm.stream_call` only to note which pass is calling, so the
    budget guard, schema-in-prompt, repair loop and validation all run for real.

    - `fake_llm.queue(pass_name, *responses)` adds replies for that pass, consumed in order.
      A repair attempt consumes the next reply. A reply is a callable taking the request
      record and returning one of the other kinds, a dict or list (sent as JSON),
      a str (sent as is), `Reply(content, done_reason)` (e.g. "length" for truncation),
      an `httpx.Response` (returned as is), or an exception instance raised by the
      transport (`httpx.ConnectError("down")` becomes `ServiceUnavailable`).
    - `fake_llm.defaults[pass_name]` is used when that queue is empty. Without one, an
      unexpected call fails the test: it raises in the calling code and is checked
      again at teardown, so a broad `except` in the code under test can't hide it.
      The `client` fixture installs `minimal_replies()` as defaults for every pass.
    - `fake_llm.requests` records every chat request, repairs included, as
      `{"pass", "messages", "payload", "body"}`; `payload` is the parsed JSON of the user
      message (or None). `fake_llm.requests_for(pass_name)` filters them.
    - Only POST /api/chat counts as a model call. /api/show reports a local model;
      /api/tags lists no models; any other request gets an empty 200.

    Settings are read from an isolated database under `tmp_path`, so every pass uses the
    default model and limits unless a test saves pass settings. Compatible with `client`.
    """
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    fake = FakeLLM()
    monkeypatch.setattr(models, "transport", httpx.MockTransport(fake._handle))
    monkeypatch.setattr(llm, "structured_call", fake._tag(llm.structured_call))
    monkeypatch.setattr(llm, "text_call", fake._tag(llm.text_call))
    monkeypatch.setattr(llm, "stream_call", fake._tag_stream(llm.stream_call))
    yield fake
    assert not fake.unexpected, fake.unexpected


CORE_SCORES = (
    "Overall",
    "Clarity",
    "Structure",
    "Conciseness",
    "Technical accuracy",
    "Technical coverage",
    "Handling uncertainty",
)
MINIMAL_NOTES = "## Focus: structure\nSince the first session. Opens with a definition."
MINIMAL_REVIEW = "Test double review. You opened with [[L1]]. Main focus for next time: structure."


def _technical(record):
    props = record["body"].get("format", {}).get("properties", {})
    payload = record["payload"] or {}
    if "reviews" in props:  # correction second check
        return {
            "reviews": [
                {
                    "id": item["id"],
                    "verdict": "incorrect",
                    "explanation": "Test double check.",
                    "correction": "",
                    "reference_ids": item["reference_ids"],
                }
                for item in payload["proposed_corrections"]
            ]
        }
    first_line = list(payload["transcript_lines"])[:1]
    return {
        "concepts": [
            {
                "concept_id": concept["id"],
                "status": "correct" if i == 0 else "missing",
                "line_ids": first_line if i == 0 else [],
                "note": "Test double finding.",
            }
            for i, concept in enumerate(payload["concepts"])
        ],
        "corrections": [],
        "senior_points": [{"point": f"Senior point {n}.", "basis": "reference"} for n in (1, 2, 3)],
    }


def _communication(record):
    lines = list(record["payload"]["transcript_lines"])
    return {
        "sections": [{"label": "Whole answer", "first_line": lines[0], "last_line": lines[-1]}],
        "points": [],
        "gaps": [],
        "focus": [],
    }


def _writer(record):
    if "format" not in record["body"]:
        return MINIMAL_REVIEW
    previous = record["payload"].get("previous_attempt_scores")
    return {
        "scores": [{"name": name, "score": 5.0, "reason": "Test double estimate."} for name in CORE_SCORES],
        "key_points": [{"text": f"Key point {n}.", "line_ids": []} for n in (1, 2, 3)],
        "checklist": ["Open with a one-sentence definition.", "Close with a summary."],
        "comparison": {
            "changes": [
                {"name": s["name"], "before": s["score"], "after": 5.0} for s in previous if s["name"] in CORE_SCORES
            ],
            "what_changed": "Test double comparison.",
        }
        if previous
        else None,
    }


MINIMAL_CHAT_REPLY = "Test double coach reply about [[L1]]."
MINIMAL_CHAT_SUMMARY = "Test double summary of the earlier conversation."


def _chat(record):
    # One pass, two calls: the streamed reply, and the running summary (a plain text call).
    return MINIMAL_CHAT_REPLY if record["body"].get("stream") else MINIMAL_CHAT_SUMMARY


def minimal_replies() -> dict:
    """Valid minimal model output for every pass, built from each request's own IDs."""
    return {
        "technical": _technical,
        "communication": _communication,
        "writer": _writer,
        "memory": MINIMAL_NOTES,
        "chat": _chat,
    }
