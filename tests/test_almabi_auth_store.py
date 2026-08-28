from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest


pytest.importorskip("argon2")

from almabi_auth_store import (  # noqa: E402
    ROLES,
    AuthStore,
    BootstrapError,
    UserAlreadyExistsError,
    UserNotFoundError,
    authenticate,
    bootstrap,
    create_user,
    disable_user,
    init_schema,
    list_users,
    normalize_username,
    update_password,
)


def test_schema_init_is_idempotent(tmp_path):
    database = tmp_path / "nested" / "auth.sqlite3"

    init_schema(database)
    init_schema(database)

    with sqlite3.connect(database) as connection:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(auth_users)")
        }
    assert columns == {
        "id",
        "username",
        "password_hash",
        "role",
        "enabled",
        "created_at",
        "updated_at",
    }


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (" Alice ", "alice"),
        ("АДМИН", "админ"),
        ("Ａｌｉｃｅ", "alice"),
        ("Straße", "strasse"),
    ],
)
def test_username_normalization(raw, expected):
    assert normalize_username(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "bad\x00name"])
def test_invalid_username_is_rejected(raw):
    with pytest.raises(ValueError):
        normalize_username(raw)


def test_bootstrap_creates_only_the_first_user(tmp_path):
    store = AuthStore(tmp_path / "auth.sqlite3")

    user = store.bootstrap(" Root ", "root-secret")

    assert user.username == "root"
    assert user.role == "admin"
    assert user.enabled is True
    assert store.authenticate("ROOT", "root-secret") == user
    with pytest.raises(BootstrapError):
        store.bootstrap("second", "another-secret")


def test_create_lists_roles_and_rejects_normalized_duplicates(tmp_path):
    store = AuthStore(tmp_path / "auth.sqlite3")
    store.bootstrap("admin", "admin-secret")

    for role in sorted(ROLES):
        store.create_user(f" {role}-user ", f"{role}-secret", role)

    assert [(user.username, user.role) for user in store.list_users()] == [
        ("admin", "admin"),
        ("admin-user", "admin"),
        ("uploader-user", "uploader"),
        ("viewer-user", "viewer"),
    ]
    with pytest.raises(UserAlreadyExistsError):
        store.create_user("VIEWER-USER", "different-secret", "viewer")
    with pytest.raises(ValueError):
        store.create_user("invalid-role-user", "secret", "owner")


def test_password_is_argon2id_hashed_and_never_stored_as_plaintext(tmp_path):
    database = tmp_path / "auth.sqlite3"
    password = "unique-plaintext-password"
    AuthStore(database).bootstrap("admin", password)

    with sqlite3.connect(database) as connection:
        stored_hash = connection.execute(
            "SELECT password_hash FROM auth_users WHERE username = 'admin'"
        ).fetchone()[0]

    assert stored_hash.startswith("$argon2id$")
    assert stored_hash != password
    assert password.encode() not in database.read_bytes()


def test_update_password_invalidates_old_password(tmp_path):
    store = AuthStore(tmp_path / "auth.sqlite3")
    store.bootstrap("admin", "old-secret")

    store.update_password("ADMIN", "new-secret")

    assert store.authenticate("admin", "old-secret") is None
    assert store.authenticate(" admin ", "new-secret") is not None
    with pytest.raises(UserNotFoundError):
        store.update_password("missing", "secret")


def test_server_side_session_can_be_resolved_and_revoked(tmp_path):
    store = AuthStore(tmp_path / "auth.sqlite3")
    user = store.bootstrap("admin", "admin-secret")

    token = store.create_session(user.id, 3600)
    assert store.resolve_session(token) == user
    assert store.resolve_session("not-a-session") is None

    store.revoke_session(token)
    assert store.resolve_session(token) is None


def test_password_change_revokes_active_sessions(tmp_path):
    store = AuthStore(tmp_path / "auth.sqlite3")
    user = store.bootstrap("admin", "admin-secret")
    token = store.create_session(user.id, 3600)

    store.update_password("admin", "new-secret")

    assert store.resolve_session(token) is None


def test_disabled_user_cannot_authenticate_and_can_be_filtered(tmp_path):
    store = AuthStore(tmp_path / "auth.sqlite3")
    store.bootstrap("admin", "admin-secret")
    store.create_user("reader", "reader-secret", "viewer")

    store.disable_user("READER")

    assert store.authenticate("reader", "reader-secret") is None
    assert [user.username for user in store.list_users(include_disabled=False)] == [
        "admin"
    ]
    disabled = next(user for user in store.list_users() if user.username == "reader")
    assert disabled.enabled is False
    with pytest.raises(UserNotFoundError):
        store.disable_user("missing")


def test_authentication_failures_do_not_raise(tmp_path):
    store = AuthStore(tmp_path / "auth.sqlite3")
    store.bootstrap("admin", "admin-secret")

    assert store.authenticate("admin", "wrong") is None
    assert store.authenticate("missing", "wrong") is None
    assert store.authenticate("", "wrong") is None
    assert store.authenticate("admin", object()) is None


def test_concurrent_bootstrap_is_atomic(tmp_path):
    database = tmp_path / "auth.sqlite3"

    def attempt(index):
        try:
            return AuthStore(database).bootstrap(f"admin-{index}", f"secret-{index}")
        except BootstrapError:
            return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(attempt, range(2)))

    assert sum(user is not None for user in results) == 1
    assert len(AuthStore(database).list_users()) == 1


def test_module_level_api(tmp_path):
    database = tmp_path / "auth.sqlite3"

    bootstrap(database, "admin", "admin-secret")
    create_user(database, "uploader", "upload-secret", "uploader")
    assert authenticate(database, "UPLOADER", "upload-secret").role == "uploader"

    update_password(database, "uploader", "new-upload-secret")
    disable_user(database, "uploader")

    users = list_users(database)
    assert [user.username for user in users] == ["admin", "uploader"]
    assert users[1].enabled is False
