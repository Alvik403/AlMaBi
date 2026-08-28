from __future__ import annotations

import asyncio
import secrets
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from almabi_file_security import directory_size

ASGIApp = Callable[[dict[str, Any], Callable[[], Awaitable[dict[str, Any]]], Callable[[dict[str, Any]], Awaitable[None]]], Awaitable[None]]


async def _plain_response(
    send: Callable[[dict[str, Any]], Awaitable[None]],
    status: int,
    body: bytes,
) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json; charset=utf-8"),
                (b"content-length", str(len(body)).encode("ascii")),
                (b"cache-control", b"no-store"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


class _BodyTooLarge(Exception):
    pass


class RequestTimeoutMiddleware:
    def __init__(self, app: ASGIApp, *, timeout_seconds: int) -> None:
        self.app = app
        self.timeout_seconds = timeout_seconds

    async def __call__(self, scope: dict[str, Any], receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def tracked_send(message: dict[str, Any]) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            async with asyncio.timeout(self.timeout_seconds):
                await self.app(scope, receive, tracked_send)
        except TimeoutError:
            if not started:
                await _plain_response(send, 504, b'{"detail":"Request processing timed out"}')


class RequestBodyLimitMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        max_bytes: int,
        uploads_dir: Path | None = None,
        quota_bytes: int | None = None,
    ) -> None:
        self.app = app
        self.max_bytes = max_bytes
        self.uploads_dir = uploads_dir
        self.quota_bytes = quota_bytes

    async def __call__(self, scope: dict[str, Any], receive, send) -> None:
        if scope["type"] != "http" or scope.get("method") not in {"POST", "PUT", "PATCH"}:
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        raw_length = headers.get(b"content-length")
        content_length = 0
        if raw_length:
            try:
                content_length = int(raw_length)
                if content_length > self.max_bytes:
                    await _plain_response(send, 413, b'{"detail":"Request body is too large"}')
                    return
            except ValueError:
                await _plain_response(send, 400, b'{"detail":"Invalid Content-Length"}')
                return
        session = scope.get("session") or {}
        user_id = session.get("auth_user_id")
        if self.uploads_dir and self.quota_bytes and user_id is not None:
            user_dirs = self.uploads_dir.glob(f"*/users/{user_id}")
            used_bytes = sum(directory_size(path) for path in user_dirs)
            if used_bytes + content_length > self.quota_bytes:
                await _plain_response(send, 413, b'{"detail":"User upload quota exceeded"}')
                return

        total = 0

        async def limited_receive() -> dict[str, Any]:
            nonlocal total
            message = await receive()
            if message["type"] == "http.request":
                total += len(message.get("body", b""))
                if total > self.max_bytes:
                    raise _BodyTooLarge
            return message

        started = False

        async def tracked_send(message: dict[str, Any]) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracked_send)
        except _BodyTooLarge:
            if not started:
                await _plain_response(send, 413, b'{"detail":"Request body is too large"}')


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp, *, hsts: bool = False) -> None:
        self.app = app
        self.hsts = hsts

    async def __call__(self, scope: dict[str, Any], receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        nonce = secrets.token_urlsafe(24)
        scope.setdefault("state", {})["csp_nonce"] = nonce
        path = scope.get("path", "")

        async def send_with_headers(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers") or [])
                csp = (
                    "default-src 'self'; "
                    f"script-src 'self' 'nonce-{nonce}'; "
                    "style-src 'self' 'unsafe-inline'; "
                    "img-src 'self' data:; font-src 'self' data:; "
                    "connect-src 'self'; object-src 'none'; base-uri 'self'; "
                    "frame-ancestors 'none'; form-action 'self'"
                )
                headers.extend(
                    [
                        (b"content-security-policy", csp.encode("ascii")),
                        (b"x-content-type-options", b"nosniff"),
                        (b"x-frame-options", b"DENY"),
                        (b"referrer-policy", b"no-referrer"),
                        (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
                    ]
                )
                if self.hsts or scope.get("scheme") == "https":
                    headers.append(
                        (b"strict-transport-security", b"max-age=31536000; includeSubDomains")
                    )
                if not path.startswith("/static/"):
                    headers.append((b"cache-control", b"no-store"))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)
