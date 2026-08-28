from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

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
        yield client


def _csrf(html: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match
    return match.group(1)


def _login(client: TestClient, username: str, password: str) -> str:
    page = client.get("/login")
    response = client.post(
        "/login",
        data={
            "username": username,
            "password": password,
            "csrf_token": _csrf(page.text),
            "next_url": "/dashboard/almabi",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    dashboard = client.get("/dashboard/almabi")
    assert dashboard.status_code == 200
    token = re.search(r'<meta name="csrf-token" content="([^"]+)"', dashboard.text)
    assert token
    return token.group(1)


def test_anonymous_user_only_reaches_login(auth_client):
    page = auth_client.get("/dashboard/almabi", follow_redirects=False)
    api = auth_client.get("/api/almabi/data-source")

    assert page.status_code == 303
    assert page.headers["location"].startswith("/login")
    assert api.status_code == 401


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


def test_admin_can_open_user_management_and_docs(auth_client):
    _login(auth_client, "admin", "admin-password-long")

    assert auth_client.get("/admin/users").status_code == 200
    assert auth_client.get("/api/docs").status_code == 200
