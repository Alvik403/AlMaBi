"""Autonomous SQLite-backed local user authentication.

The module deliberately has no dependency on the application layer.  Passwords
are stored only as Argon2id hashes produced by ``argon2-cffi``.
"""

from __future__ import annotations

import sqlite3
import unicodedata
import hashlib
import secrets
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from os import PathLike
from pathlib import Path
from typing import Iterator

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from argon2.low_level import Type


ROLES = frozenset({"admin", "uploader", "viewer"})
_MAX_USERNAME_LENGTH = 128


class AuthStoreError(Exception):
    """Base class for local authentication store errors."""


class UserAlreadyExistsError(AuthStoreError):
    """Raised when a normalized username is already registered."""


class UserNotFoundError(AuthStoreError):
    """Raised when a requested user does not exist."""


class BootstrapError(AuthStoreError):
    """Raised when bootstrap is attempted after a user already exists."""


@dataclass(frozen=True, slots=True)
class User:
    id: int
    username: str
    role: str
    enabled: bool
    created_at: str
    updated_at: str


def normalize_username(username: str) -> str:
    """Return a stable, case-insensitive representation of a username."""
    if not isinstance(username, str):
        raise TypeError("username must be a string")
    normalized = unicodedata.normalize("NFKC", username).strip().casefold()
    if not normalized:
        raise ValueError("username must not be empty")
    if len(normalized) > _MAX_USERNAME_LENGTH:
        raise ValueError(f"username must not exceed {_MAX_USERNAME_LENGTH} characters")
    if any(unicodedata.category(char).startswith("C") for char in normalized):
        raise ValueError("username must not contain control characters")
    return normalized


def _validate_role(role: str) -> str:
    if role not in ROLES:
        raise ValueError(f"role must be one of: {', '.join(sorted(ROLES))}")
    return role


def _validate_password(password: str) -> str:
    if not isinstance(password, str):
        raise TypeError("password must be a string")
    if not password:
        raise ValueError("password must not be empty")
    return password


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _row_to_user(row: sqlite3.Row) -> User:
    return User(
        id=int(row["id"]),
        username=str(row["username"]),
        role=str(row["role"]),
        enabled=bool(row["enabled"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


class AuthStore:
    """Local user store whose database location is supplied by the caller."""

    def __init__(
        self,
        path: str | PathLike[str],
        *,
        password_hasher: PasswordHasher | None = None,
    ) -> None:
        self.path = Path(path)
        if self.path.exists() and self.path.is_dir():
            raise ValueError("database path must point to a file")
        self._hasher = password_hasher or PasswordHasher(type=Type.ID)
        # Used to keep failed authentication work similar for known and unknown
        # usernames.  It is never persisted.
        self._dummy_hash = self._hasher.hash("almabi-auth-dummy-password")

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.path.parent.chmod(0o700)
        except OSError:
            pass
        connection = sqlite3.connect(
            self.path,
            timeout=10.0,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        try:
            self.path.chmod(0o600)
        except OSError:
            pass
        return connection

    @contextmanager
    def _transaction(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def init_schema(self) -> None:
        """Create the user schema if it does not exist."""
        with self._transaction(write=True) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS auth_users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL
                        CHECK (role IN ('admin', 'uploader', 'viewer')),
                    enabled INTEGER NOT NULL DEFAULT 1
                        CHECK (enabled IN (0, 1)),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS auth_sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES auth_users(id) ON DELETE CASCADE,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    revoked_at TEXT
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_auth_sessions_user_id ON auth_sessions(user_id)"
            )

    def bootstrap(
        self,
        username: str,
        password: str,
        *,
        role: str = "admin",
    ) -> User:
        """Atomically create the first user; fail if the store is not empty."""
        normalized = normalize_username(username)
        validated_password = _validate_password(password)
        validated_role = _validate_role(role)
        password_hash = self._hasher.hash(validated_password)
        now = _utc_now()

        self.init_schema()
        with self._transaction(write=True) as connection:
            if connection.execute("SELECT 1 FROM auth_users LIMIT 1").fetchone():
                raise BootstrapError("bootstrap is only allowed for an empty store")
            cursor = connection.execute(
                """
                INSERT INTO auth_users
                    (username, password_hash, role, enabled, created_at, updated_at)
                VALUES (?, ?, ?, 1, ?, ?)
                """,
                (normalized, password_hash, validated_role, now, now),
            )
            return User(
                id=int(cursor.lastrowid),
                username=normalized,
                role=validated_role,
                enabled=True,
                created_at=now,
                updated_at=now,
            )

    def create_user(self, username: str, password: str, role: str) -> User:
        """Create an enabled user with a normalized unique username."""
        normalized = normalize_username(username)
        validated_password = _validate_password(password)
        validated_role = _validate_role(role)
        password_hash = self._hasher.hash(validated_password)
        now = _utc_now()

        self.init_schema()
        try:
            with self._transaction(write=True) as connection:
                cursor = connection.execute(
                    """
                    INSERT INTO auth_users
                        (username, password_hash, role, enabled, created_at, updated_at)
                    VALUES (?, ?, ?, 1, ?, ?)
                    """,
                    (normalized, password_hash, validated_role, now, now),
                )
                return User(
                    id=int(cursor.lastrowid),
                    username=normalized,
                    role=validated_role,
                    enabled=True,
                    created_at=now,
                    updated_at=now,
                )
        except sqlite3.IntegrityError as exc:
            if "UNIQUE constraint failed" in str(exc):
                raise UserAlreadyExistsError(
                    f"user {normalized!r} already exists"
                ) from exc
            raise

    def list_users(self, *, include_disabled: bool = True) -> list[User]:
        """List users in deterministic username order without password hashes."""
        self.init_schema()
        where = "" if include_disabled else "WHERE enabled = 1"
        with self._transaction() as connection:
            rows = connection.execute(
                f"""
                SELECT id, username, role, enabled, created_at, updated_at
                FROM auth_users
                {where}
                ORDER BY username, id
                """
            ).fetchall()
        return [_row_to_user(row) for row in rows]

    def get_user(self, user_id: int) -> User | None:
        self.init_schema()
        with self._transaction() as connection:
            row = connection.execute(
                """
                SELECT id, username, role, enabled, created_at, updated_at
                FROM auth_users
                WHERE id = ?
                """,
                (user_id,),
            ).fetchone()
        return _row_to_user(row) if row is not None else None

    def create_session(self, user_id: int, max_age_seconds: int) -> str:
        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=max_age_seconds)
        self.init_schema()
        with self._transaction(write=True) as connection:
            connection.execute(
                "DELETE FROM auth_sessions WHERE expires_at <= ? OR revoked_at IS NOT NULL",
                (now.isoformat(timespec="seconds"),),
            )
            try:
                connection.execute(
                    """
                    INSERT INTO auth_sessions
                        (token_hash, user_id, created_at, expires_at, revoked_at)
                    VALUES (?, ?, ?, ?, NULL)
                    """,
                    (
                        token_hash,
                        user_id,
                        now.isoformat(timespec="seconds"),
                        expires_at.isoformat(timespec="seconds"),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise UserNotFoundError(f"user id {user_id} does not exist") from exc
        return token

    def resolve_session(self, token: str) -> User | None:
        if not token:
            return None
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.init_schema()
        with self._transaction() as connection:
            row = connection.execute(
                """
                SELECT u.id, u.username, u.role, u.enabled, u.created_at, u.updated_at
                FROM auth_sessions AS s
                JOIN auth_users AS u ON u.id = s.user_id
                WHERE s.token_hash = ?
                  AND s.revoked_at IS NULL
                  AND s.expires_at > ?
                  AND u.enabled = 1
                """,
                (token_hash, now),
            ).fetchone()
        return _row_to_user(row) if row is not None else None

    def revoke_session(self, token: str) -> None:
        if not token:
            return
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        self.init_schema()
        with self._transaction(write=True) as connection:
            connection.execute(
                "UPDATE auth_sessions SET revoked_at = ? WHERE token_hash = ?",
                (_utc_now(), token_hash),
            )

    def revoke_user_sessions(self, user_id: int) -> None:
        self.init_schema()
        with self._transaction(write=True) as connection:
            connection.execute(
                "UPDATE auth_sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL",
                (_utc_now(), user_id),
            )

    def update_password(self, username: str, new_password: str) -> None:
        """Replace a user's password hash."""
        normalized = normalize_username(username)
        validated_password = _validate_password(new_password)
        password_hash = self._hasher.hash(validated_password)

        self.init_schema()
        with self._transaction(write=True) as connection:
            cursor = connection.execute(
                """
                UPDATE auth_users
                SET password_hash = ?, updated_at = ?
                WHERE username = ?
                """,
                (password_hash, _utc_now(), normalized),
            )
            if cursor.rowcount != 1:
                raise UserNotFoundError(f"user {normalized!r} does not exist")
            connection.execute(
                """
                UPDATE auth_sessions
                SET revoked_at = ?
                WHERE user_id = (SELECT id FROM auth_users WHERE username = ?)
                  AND revoked_at IS NULL
                """,
                (_utc_now(), normalized),
            )

    def disable_user(self, username: str) -> None:
        """Disable a user account without deleting its audit identity."""
        normalized = normalize_username(username)

        self.init_schema()
        with self._transaction(write=True) as connection:
            cursor = connection.execute(
                """
                UPDATE auth_users
                SET enabled = 0, updated_at = ?
                WHERE username = ?
                """,
                (_utc_now(), normalized),
            )
            if cursor.rowcount != 1:
                raise UserNotFoundError(f"user {normalized!r} does not exist")
            connection.execute(
                """
                UPDATE auth_sessions
                SET revoked_at = ?
                WHERE user_id = (SELECT id FROM auth_users WHERE username = ?)
                  AND revoked_at IS NULL
                """,
                (_utc_now(), normalized),
            )

    def authenticate(self, username: str, password: str) -> User | None:
        """Return an enabled user on success, otherwise return ``None``."""
        try:
            normalized = normalize_username(username)
        except (TypeError, ValueError):
            normalized = None
        candidate = password if isinstance(password, str) else ""

        self.init_schema()
        with self._transaction() as connection:
            row = (
                connection.execute(
                    """
                    SELECT id, username, password_hash, role, enabled,
                           created_at, updated_at
                    FROM auth_users
                    WHERE username = ?
                    """,
                    (normalized,),
                ).fetchone()
                if normalized is not None
                else None
            )

        encoded_hash = str(row["password_hash"]) if row is not None else self._dummy_hash
        try:
            verified = self._hasher.verify(encoded_hash, candidate)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return None
        if not verified or row is None or not bool(row["enabled"]):
            return None

        if self._hasher.check_needs_rehash(encoded_hash):
            replacement_hash = self._hasher.hash(candidate)
            with self._transaction(write=True) as connection:
                connection.execute(
                    """
                    UPDATE auth_users
                    SET password_hash = ?, updated_at = ?
                    WHERE id = ? AND password_hash = ?
                    """,
                    (replacement_hash, _utc_now(), int(row["id"]), encoded_hash),
                )
        return _row_to_user(row)


def init_schema(path: str | PathLike[str]) -> None:
    AuthStore(path).init_schema()


def bootstrap(
    path: str | PathLike[str],
    username: str,
    password: str,
    *,
    role: str = "admin",
) -> User:
    return AuthStore(path).bootstrap(username, password, role=role)


def create_user(
    path: str | PathLike[str],
    username: str,
    password: str,
    role: str,
) -> User:
    return AuthStore(path).create_user(username, password, role)


def list_users(
    path: str | PathLike[str],
    *,
    include_disabled: bool = True,
) -> list[User]:
    return AuthStore(path).list_users(include_disabled=include_disabled)


def update_password(
    path: str | PathLike[str],
    username: str,
    new_password: str,
) -> None:
    AuthStore(path).update_password(username, new_password)


def disable_user(path: str | PathLike[str], username: str) -> None:
    AuthStore(path).disable_user(username)


def authenticate(
    path: str | PathLike[str],
    username: str,
    password: str,
) -> User | None:
    return AuthStore(path).authenticate(username, password)


__all__ = [
    "ROLES",
    "AuthStore",
    "AuthStoreError",
    "BootstrapError",
    "User",
    "UserAlreadyExistsError",
    "UserNotFoundError",
    "authenticate",
    "bootstrap",
    "create_user",
    "disable_user",
    "init_schema",
    "list_users",
    "normalize_username",
    "update_password",
]
