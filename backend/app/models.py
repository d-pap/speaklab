import math
from pathlib import Path

import httpx
from pydantic import BaseModel

from .config import settings


class ServiceUnavailable(Exception):
    pass


# Tests set this to an httpx.MockTransport so no real model is ever called.
transport: httpx.BaseTransport | None = None


def client(timeout: float | None = None):
    return httpx.Client(
        timeout=timeout or settings.model_timeout,
        trust_env=False,
        follow_redirects=False,
        transport=transport,
    )


def assert_local_model(http: httpx.Client, model: str | None = None):
    model = model or settings.ollama_model
    if "cloud" in model.lower():
        raise ServiceUnavailable("Cloud model tags are disabled. Configure a downloaded local Ollama model.")
    response = http.post(settings.ollama_url + "/api/show", json={"model": model})
    response.raise_for_status()
    info = response.json()
    if info.get("remote_host") or info.get("remote_model") or info.get("details", {}).get("remote_host"):
        raise ServiceUnavailable("This Ollama model routes remotely. Choose a downloaded local model.")
    return info


def installed_models() -> list[dict]:
    """Inspect the configured Ollama service only; never download or load weights."""
    try:
        with client(4) as http:
            response = http.get(settings.ollama_url + "/api/tags")
            response.raise_for_status()
            result = []
            for item in response.json()["models"]:
                name = item["name"]
                reason = None
                details = item.get("details", {})
                try:
                    info = assert_local_model(http, name)
                    details = info.get("details", details)
                    capabilities = info.get("capabilities", item.get("capabilities", []))
                    if capabilities and "completion" not in capabilities:
                        reason = "This model does not support chat/text generation."
                except ServiceUnavailable as exc:
                    reason = str(exc)
                except (httpx.HTTPError, ValueError, KeyError, TypeError):
                    reason = "Could not inspect this model. Refresh and try again."
                result.append(
                    {
                        "name": name,
                        "size_bytes": item.get("size", 0),
                        "parameters": details.get("parameter_size", ""),
                        "quantization": details.get("quantization_level", ""),
                        "selectable": reason is None,
                        "reason": reason,
                    }
                )
            return sorted(result, key=lambda item: item["name"].casefold())
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        raise ServiceUnavailable(
            "Cannot list installed models. Start the Ollama service and refresh."
        ) from exc


def validate_model_selection(name: str):
    try:
        with client(4) as http:
            response = http.get(settings.ollama_url + "/api/tags")
            response.raise_for_status()
            if name not in {item["name"] for item in response.json()["models"]}:
                raise ValueError(
                    "Choose a model already installed on the connected computer, then refresh the list."
                )
            info = assert_local_model(http, name)
            if info.get("capabilities") and "completion" not in info["capabilities"]:
                raise ValueError("Choose a chat/text-generation model, rather than an embedding-only model.")
    except (httpx.HTTPError, KeyError, TypeError) as exc:
        raise ServiceUnavailable("Could not inspect the selected model. Check Ollama and retry.") from exc


def health() -> dict:
    status = {
        "ollama": False,
        "whisper": False,
        "model": settings.ollama_model,
        "ollama_url": settings.ollama_url,
        "whisper_url": settings.whisper_url,
        "data_dir": str(settings.data_dir),
        "server_name": settings.server_name,
        "models": [],
    }
    with client(2) as http:
        try:
            response = http.get(settings.ollama_url + "/api/tags")
            response.raise_for_status()
            status["models"] = [m["name"] for m in response.json().get("models", [])]
            assert_local_model(http)
            status["ollama"] = True
        except (httpx.HTTPError, ValueError, ServiceUnavailable, KeyError):
            status["ollama_error"] = (
                "Ollama or the configured local model is unavailable. Check Settings and retry."
            )
        try:
            response = http.get(settings.whisper_url + "/health")
            if response.status_code == 404:
                response = http.get(settings.whisper_url + "/")
            status["whisper"] = response.is_success
        except httpx.HTTPError:
            pass
    return status


def transcribe(path: Path, duration: float) -> tuple[str, list[dict]]:
    try:
        with client() as http, path.open("rb") as audio:
            response = http.post(
                settings.whisper_url + "/inference",
                files={"file": ("recording.wav", audio, "audio/wav")},
                data={
                    "response_format": "verbose_json",
                    "temperature": "0.0",
                    "language": "en",
                    "prompt": "Um, well, I, I think—uh—let me start again. Hmm. You know, I mean, that's what I was saying.",
                    "suppress_non_speech": "false",
                    "token_timestamps": "true",
                    "split_on_word": "true",
                },
            )
            response.raise_for_status()
            data = response.json()
        text = data.get("text", "").strip()
        if not text or len(text) > 30000:
            raise ValueError("No usable transcript returned")
        segments = []
        for seg in data.get("segments", []):
            start, end = float(seg["start"]), float(seg["end"])
            if math.isfinite(start) and math.isfinite(end) and 0 <= start < end <= duration + 1:
                words = []
                for word in seg.get("words", []):
                    wstart, wend = word.get("start"), word.get("end")
                    if (
                        isinstance(wstart, (int, float))
                        and isinstance(wend, (int, float))
                        and math.isfinite(wstart)
                        and math.isfinite(wend)
                        and 0 <= wstart < wend <= duration + 1
                    ):
                        words.append(
                            {"word": str(word.get("word", "")), "start": wstart, "end": min(wend, duration)}
                        )
                segments.append(
                    {"start": start, "end": min(end, duration), "text": str(seg["text"]), "words": words}
                )
        return text, segments
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        raise ServiceUnavailable(
            "Local transcription is unavailable or returned no usable speech. Start whisper-server and retry, or enter a transcript manually."
        ) from exc


def structured(
    system: str, payload: dict, schema: type[BaseModel], validate=None, output_schema=None
) -> BaseModel:
    """Legacy entry point: runs the technical pass until callers move to llm.structured_call."""
    from . import llm

    result, _model = llm.structured_call("technical", system, payload, schema, validate, output_schema)
    return result
