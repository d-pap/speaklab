from pathlib import Path
from urllib.parse import urlparse

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SPEAKLAB_", env_file=ROOT / ".env", extra="ignore")
    data_dir: Path = ROOT / "data"
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3.5:9b-q4_K_M"
    whisper_url: str = "http://127.0.0.1:8080"
    model_timeout: int = 180
    ollama_context: int = Field(default=8192, ge=4096, le=32768)
    ollama_max_output: int = Field(default=2048, ge=512, le=4096)
    serve_frontend: bool = False
    server_name: str = Field(default="This computer", max_length=80)
    browser_origins: list[str] = Field(default_factory=list, max_length=8)
    max_upload_bytes: int = 30 * 1024 * 1024

    @field_validator("browser_origins")
    @classmethod
    def exact_https_origins(cls, values: list[str]) -> list[str]:
        origins = []
        for value in values:
            url = urlparse(value)
            if (url.scheme != "https" or not url.hostname or "*" in value
                    or any(c.isspace() for c in value) or url.username or url.password
                    or url.query or url.fragment or url.path not in {"", "/"}):
                raise ValueError("Additional browser origins must be exact HTTPS origins without paths or wildcards.")
            host = f"[{url.hostname}]" if ":" in url.hostname else url.hostname
            port = f":{url.port}" if url.port not in {None, 443} else ""
            origin = f"https://{host}{port}"
            if origin not in origins:
                origins.append(origin)
        return origins

    @field_validator("data_dir")
    @classmethod
    def absolute_data_dir(cls, value: Path) -> Path:
        return value.resolve() if value.is_absolute() else (ROOT / value).resolve()

    @field_validator("ollama_url", "whisper_url")
    @classmethod
    def local_only(cls, value: str) -> str:
        url = urlparse(value)
        if url.scheme != "http" or url.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("Model services must use HTTP on loopback; external providers are disabled.")
        if url.username or url.password or url.query or url.fragment or url.path not in {"", "/"}:
            raise ValueError("Use a plain local service URL without credentials, query, or path.")
        return value.rstrip("/")


settings = Settings()
