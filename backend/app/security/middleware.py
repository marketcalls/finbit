"""Transport level protections: security headers and a request body cap.

Both are ASGI middlewares rather than BaseHTTPMiddleware subclasses. They touch
one message each and never buffer a response, so they add nothing to the cost
of a request and cannot interfere with a streamed one.

install_security(app) is the single call main.py needs. It also registers the
error handler that gives every failure the {"detail", "code"} body the contract
specifies. That handler only touches exceptions that actually carry a code, so
every phase 1 error body keeps its exact shape.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import JSONResponse
from starlette.datastructures import MutableHeaders
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger(__name__)

# 256 KB. The largest legitimate body in this API is an admin article edit,
# which is a few kilobytes, so anything past this is either a mistake or an
# attempt to make the server do work.
MAX_BODY_BYTES = 256 * 1024

BODY_TOO_LARGE_CODE = "payload_too_large"
BODY_TOO_LARGE_DETAIL = "The request body is larger than this API accepts."

# Referrer-Policy and X-Frame-Options matter for the admin screens. The
# Permissions-Policy list denies every capability the API has no use for, so a
# response rendered in a browser cannot reach a camera, a microphone or a
# location.
SECURITY_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": (
        "accelerometer=(), ambient-light-sensor=(), autoplay=(), battery=(), "
        "camera=(), display-capture=(), fullscreen=(), geolocation=(), "
        "gyroscope=(), magnetometer=(), microphone=(), midi=(), payment=(), "
        "publickey-credentials-get=(), screen-wake-lock=(), usb=(), "
        "xr-spatial-tracking=()"
    ),
}


class SecurityHeadersMiddleware:
    """Add the standard hardening headers to every response.

    Existing headers win, so a route that deliberately sets its own value is
    never overwritten.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in SECURITY_HEADERS.items():
                    if name not in headers:
                        headers[name] = value
            await send(message)

        await self.app(scope, receive, send_with_headers)


class BodyTooLarge(StarletteHTTPException):
    """413 for a body that crossed the cap while it was being read."""

    code = BODY_TOO_LARGE_CODE

    def __init__(self) -> None:
        super().__init__(status_code=413, detail=BODY_TOO_LARGE_DETAIL)


class BodySizeLimitMiddleware:
    """Refuse a request body over MAX_BODY_BYTES with 413.

    A declared Content-Length is rejected before a single byte of the body is
    read, which is the case every normal client hits. A chunked upload has no
    length to check, so those bytes are counted as they arrive and the read is
    cut off with BodyTooLarge the moment it crosses the cap.
    """

    def __init__(self, app: ASGIApp, max_bytes: int = MAX_BODY_BYTES) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        declared = _declared_content_length(scope)
        if declared is not None:
            if declared > self.max_bytes:
                logger.info(
                    "%s %s declared %d bytes, over the %d byte cap",
                    scope.get("method", "?"),
                    scope.get("path", "?"),
                    declared,
                    self.max_bytes,
                )
                await _too_large_response()(scope, receive, send)
                return
            await self.app(scope, receive, send)
            return

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b"") or b"")
                if received > self.max_bytes:
                    raise BodyTooLarge()
            return message

        await self.app(scope, limited_receive, send)


def _declared_content_length(scope: Scope) -> int | None:
    """The Content-Length header as an int, or None when absent or junk."""
    for raw_name, raw_value in scope.get("headers", []):
        if raw_name == b"content-length":
            try:
                return int(raw_value.decode("latin-1"))
            except (ValueError, UnicodeDecodeError):
                return None
    return None


def _too_large_response() -> JSONResponse:
    """The 413 body, shaped like every other error in this API."""
    return JSONResponse(
        status_code=413,
        content={"detail": BODY_TOO_LARGE_DETAIL, "code": BODY_TOO_LARGE_CODE},
    )


async def coded_http_exception_handler(
    request: Request, exc: Exception
) -> Any:
    """Give an exception that carries a code the {"detail", "code"} body.

    Anything without a code falls through to the FastAPI default handler
    untouched, so every phase 1 error response keeps its exact shape.
    """
    code = getattr(exc, "code", None)
    status_code = int(getattr(exc, "status_code", 500))
    if not code:
        return await http_exception_handler(request, exc)  # type: ignore[arg-type]
    detail = getattr(exc, "detail", "")
    headers = getattr(exc, "headers", None)
    return JSONResponse(
        status_code=status_code,
        content={
            "detail": detail if isinstance(detail, str) else str(detail),
            "code": str(code),
        },
        headers=headers,
    )


def install_error_handlers(app: FastAPI) -> None:
    """Register the coded error handler for HTTPException."""
    app.add_exception_handler(StarletteHTTPException, coded_http_exception_handler)


def install_security(app: FastAPI, max_body_bytes: int = MAX_BODY_BYTES) -> None:
    """Wire every transport level protection onto an application.

    One call so nothing can be wired by halves: headers, the body cap and the
    coded error bodies always arrive together.

    Order matters. add_middleware puts the newest layer outermost, so the
    headers are added last and therefore wrap everything, including the 413 the
    body cap answers with.
    """
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=max_body_bytes)
    app.add_middleware(SecurityHeadersMiddleware)
    install_error_handlers(app)


__all__ = [
    "BODY_TOO_LARGE_CODE",
    "BODY_TOO_LARGE_DETAIL",
    "BodySizeLimitMiddleware",
    "BodyTooLarge",
    "MAX_BODY_BYTES",
    "SECURITY_HEADERS",
    "SecurityHeadersMiddleware",
    "coded_http_exception_handler",
    "install_error_handlers",
    "install_security",
]
