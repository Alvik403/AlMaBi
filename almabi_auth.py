from __future__ import annotations

import json
import secrets
import threading
import time
from collections import defaultdict, deque
from typing import Any
from urllib.parse import quote

from almabi_auth_store import AuthStore, User


SESSION_TOKEN_KEY = "auth_session_token"
SESSION_USER_ID_KEY = "auth_user_id"
SESSION_CSRF_KEY = "csrf_token"
PUBLIC_PATHS = {"/login", "/health", "/ready"}


async def _response(send, status: int, body: bytes, content_type: bytes, headers=None) -> None:
    response_headers = [
        (b"content-type", content_type),
        (b"content-length", str(len(body)).encode("ascii")),
        (b"cache-control", b"no-store"),
    ]
    response_headers.extend(headers or [])
    await send({"type": "http.response.start", "status": status, "headers": response_headers})
    await send({"type": "http.response.body", "body": body})


def _is_admin_path(path: str) -> bool:
    return path.startswith(("/admin", "/api/admin", "/api/docs", "/api/redoc", "/api/openapi.json"))


def _is_api(path: str) -> bool:
    return path.startswith("/api/")


class AuthMiddleware:
    def __init__(self, app, *, store: AuthStore, enabled: bool = True) -> None:
        self.app = app
        self.store = store
        self.enabled = enabled
        if enabled:
            self.store.init_schema()

    async def __call__(self, scope: dict[str, Any], receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if not self.enabled:
            scope.setdefault("state", {})["current_user"] = None
            await self.app(scope, receive, send)
            return
        if path.startswith("/static/") or path in PUBLIC_PATHS:
            await self.app(scope, receive, send)
            return

        session = scope.get("session") or {}
        token = session.get(SESSION_TOKEN_KEY)
        user = self.store.resolve_session(token) if isinstance(token, str) else None
        if user is None:
            session.pop(SESSION_TOKEN_KEY, None)
            session.pop(SESSION_USER_ID_KEY, None)
            if _is_api(path):
                await _response(
                    send,
                    401,
                    json.dumps({"detail": "Authentication required"}).encode("utf-8"),
                    b"application/json; charset=utf-8",
                )
            else:
                target = quote(path if path.startswith("/") else "/", safe="/?=&")
                await _response(
                    send,
                    303,
                    b"",
                    b"text/plain; charset=utf-8",
                    [(b"location", f"/login?next={target}".encode("ascii", "ignore"))],
                )
            return

        scope.setdefault("state", {})["current_user"] = user
        session[SESSION_USER_ID_KEY] = user.id
        session.setdefault(SESSION_CSRF_KEY, secrets.token_urlsafe(32))

        if _is_admin_path(path) and user.role != "admin":
            await self._forbidden(path, send)
            return
        if scope.get("method") in {"POST", "PUT", "PATCH", "DELETE"}:
            self_service = path in {"/logout", "/account/password"}
            if not self_service and user.role not in {"admin", "uploader"}:
                await self._forbidden(path, send)
                return
            if _is_api(path):
                headers = dict(scope.get("headers") or [])
                supplied = headers.get(b"x-csrf-token", b"").decode("ascii", "ignore")
                expected = session.get(SESSION_CSRF_KEY, "")
                if not supplied or not secrets.compare_digest(supplied, expected):
                    await _response(
                        send,
                        403,
                        json.dumps({"detail": "Invalid CSRF token"}).encode("utf-8"),
                        b"application/json; charset=utf-8",
                    )
                    return

        await self.app(scope, receive, send)

    @staticmethod
    async def _forbidden(path: str, send) -> None:
        if _is_api(path):
            await _response(
                send,
                403,
                json.dumps({"detail": "Insufficient role"}).encode("utf-8"),
                b"application/json; charset=utf-8",
            )
        else:
            await _response(
                send,
                403,
                "Недостаточно прав".encode("utf-8"),
                b"text/plain; charset=utf-8",
            )


class LoginThrottle:
    def __init__(self, *, attempts: int = 5, window_seconds: int = 300, lock_seconds: int = 900) -> None:
        self.attempts = attempts
        self.window_seconds = window_seconds
        self.lock_seconds = lock_seconds
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._locked_until: dict[str, float] = {}
        self._lock = threading.Lock()

    def retry_after(self, key: str) -> int:
        now = time.monotonic()
        with self._lock:
            locked_until = self._locked_until.get(key, 0)
            if locked_until > now:
                return max(1, int(locked_until - now))
            self._locked_until.pop(key, None)
            events = self._events[key]
            while events and events[0] < now - self.window_seconds:
                events.popleft()
            return 0

    def failure(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            events = self._events[key]
            while events and events[0] < now - self.window_seconds:
                events.popleft()
            events.append(now)
            if len(events) >= self.attempts:
                self._locked_until[key] = now + self.lock_seconds
                events.clear()

    def success(self, key: str) -> None:
        with self._lock:
            self._events.pop(key, None)
            self._locked_until.pop(key, None)


def session_user(scope: dict[str, Any]) -> User | None:
    user = (scope.get("state") or {}).get("current_user")
    return user if isinstance(user, User) else None
