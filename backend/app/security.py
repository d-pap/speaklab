"""Exact browser-origin and host checks for loopback and explicitly configured HTTPS access."""
import time
from urllib.parse import urlparse

from fastapi import Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware


def configure_browser_security(app, settings, log):
    origins = [
        f"http://{host}:{port}"
        for host in ("localhost", "127.0.0.1")
        for port in (5173, 5174, 4173, 8765, 8766)
    ] + settings.browser_origins
    hosts = ["localhost", "127.0.0.1", "[::1]", "testserver"]
    hosts += [urlparse(origin).hostname for origin in settings.browser_origins]
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=hosts)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["GET", "POST", "PUT"],
        allow_headers=["Content-Type", "X-SpeakLab-Client"],
    )

    @app.middleware("http")
    async def browser_request_boundary(request: Request, call_next):
        start = time.monotonic()
        origin = request.headers.get("origin")
        if origin and origin not in origins:
            return JSONResponse({"detail": "This browser origin is not allowed."}, status_code=403)
        if request.method in {"POST", "PUT", "DELETE", "PATCH"}:
            if request.headers.get("x-speaklab-client") != "1":
                return JSONResponse({"detail": "Missing local client header."}, status_code=403)
            length = request.headers.get("content-length")
            if length and (not length.isdigit() or int(length) > settings.max_upload_bytes + 1024 * 1024):
                return JSONResponse({"detail": "Request exceeds the 30 MB audio upload limit."}, status_code=413)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        log.info(
            "request",
            extra={
                "method": request.method,
                "route": request.scope.get("route").path if request.scope.get("route") else "unknown",
                "status": response.status_code,
                "elapsed_ms": round((time.monotonic() - start) * 1000),
            },
        )
        return response
