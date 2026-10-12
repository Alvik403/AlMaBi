from __future__ import annotations

import importlib.util
import json
import sys
from base64 import b64encode
from pathlib import Path

import itsdangerous
import pytest
from fastapi.testclient import TestClient


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def auth_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DEBUG", "true")
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("SESSION_SECRET", "test-auth-secret-with-at-least-32-characters")
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("LOGS_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("AUTH_DB", str(tmp_path / "runtime" / "auth.sqlite3"))
    for module_name in ["app", "settings", "logging_config"]:
        sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location("app", PROJECT_ROOT / "app.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["app"] = module
    spec.loader.exec_module(module)
    module.auth_store.bootstrap("admin", "admin-password-long")
    module.auth_store.create_user("viewer", "viewer-password-long", "viewer")
    module.auth_store.create_user("uploader", "uploader-password-long", "uploader")
    with TestClient(module.app) as client:
        client.auth_store = module.auth_store
        yield client


def _login(client: TestClient, username: str, password: str = "") -> str:
    del password
    store = client.auth_store
    user = next(item for item in store.list_users() if item.username == username)
    token = store.create_session(user.id, 8 * 60 * 60)
    csrf = "csrf-test-token"
    payload = {
        "auth_session_token": token,
        "auth_user_id": user.id,
        "csrf_token": csrf,
    }
    signer = itsdangerous.TimestampSigner("test-auth-secret-with-at-least-32-characters")
    raw = signer.sign(b64encode(json.dumps(payload).encode("utf-8"))).decode("utf-8")
    client.cookies.set("session", raw)
    return csrf


def test_anonymous_user_only_reaches_login(auth_client):
    page = auth_client.get("/dashboard/almabi", follow_redirects=False)
    api = auth_client.get("/api/almabi/data-source")

    assert page.status_code == 303
    assert page.headers["location"].startswith("/login")
    assert api.status_code == 401


def test_login_page_has_no_local_password_form(auth_client):
    page = auth_client.get("/login")
    assert page.status_code == 200
    assert 'type="password"' not in page.text
    assert "Защищённый контур" not in page.text
    assert "Сервер авторизации ещё не задан." in page.text


def test_viewer_can_read_but_cannot_upload(auth_client):
    csrf = _login(auth_client, "viewer", "viewer-password-long")

    assert auth_client.get("/api/almabi/data-source").status_code == 200
    denied = auth_client.post(
        "/api/almabi/files/upload",
        headers={"X-CSRF-Token": csrf},
        files={"file": ("bad.xlsx", b"bad", "application/octet-stream")},
    )
    assert denied.status_code == 403
    assert auth_client.get("/api/docs").status_code == 403


def test_uploader_requires_csrf_for_upload(auth_client):
    csrf = _login(auth_client, "uploader", "uploader-password-long")

    assert auth_client.post("/api/almabi/files/upload").status_code == 403
    response = auth_client.post(
        "/api/almabi/files/upload",
        headers={"X-CSRF-Token": csrf},
        files={"file": ("bad.xlsx", b"bad", "application/octet-stream")},
    )
    assert response.status_code in {400, 422}


def test_admin_can_reset_another_users_password(auth_client):
    csrf = _login(auth_client, "admin")
    users = auth_client.get("/admin/users")
    response = auth_client.post(
        "/admin/users/viewer/password",
        data={"password": "viewer-reset-password", "csrf_token": csrf},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert auth_client.auth_store.authenticate("viewer", "viewer-password-long") is None
    assert auth_client.auth_store.authenticate("viewer", "viewer-reset-password") is not None


def test_expired_admin_password_blocks_dashboard(auth_client, tmp_path: Path):
    import sqlite3
    from datetime import datetime, timedelta, timezone

    database = tmp_path / "runtime" / "auth.sqlite3"
    stale = (datetime.now(timezone.utc) - timedelta(days=61)).isoformat(timespec="seconds")
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE auth_users SET password_changed_at = ? WHERE role = 'admin'",
            (stale,),
        )
    _login(auth_client, "admin")
    dashboard = auth_client.get("/dashboard/almabi", follow_redirects=False)
    assert dashboard.status_code == 303
    assert dashboard.headers["location"] == "/account/password"


def test_admin_can_open_user_management_and_docs(auth_client):
    _login(auth_client, "admin", "admin-password-long")

    assert auth_client.get("/admin/users").status_code == 200
    assert auth_client.get("/api/docs").status_code == 200
