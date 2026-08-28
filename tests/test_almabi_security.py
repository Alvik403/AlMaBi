from __future__ import annotations

from pathlib import Path
from datetime import UTC, datetime
import os
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from fastapi.testclient import TestClient
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from almabi_file_security import resolve_stored_xlsx, resolve_user_stored_xlsx, user_upload_dir
from almabi_file_validation import validate_xlsx_container
from almabi_http_security import RequestBodyLimitMiddleware
from almabi_retention import cleanup
from settings import Settings


def test_resolve_stored_xlsx_rejects_directory_escape(tmp_path: Path):
    base = tmp_path / "uploads"
    base.mkdir()
    outside = tmp_path / "outside.xlsx"
    outside.write_bytes(b"xlsx")

    assert resolve_stored_xlsx(base, "../outside.xlsx") is None
    assert resolve_stored_xlsx(base, r"..\outside.xlsx") is None
    assert resolve_stored_xlsx(base, outside) is None


def test_resolve_stored_xlsx_accepts_server_name(tmp_path: Path):
    base = tmp_path / "uploads"
    base.mkdir()
    workbook = base / "buh-0123456789abcdef.xlsx"
    workbook.write_bytes(b"xlsx")

    assert resolve_stored_xlsx(base, workbook.name) == workbook.resolve()


def test_authenticated_users_receive_separate_upload_directories(tmp_path: Path):
    first = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
    first.scope["session"] = {"auth_user_id": 1}
    second = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
    second.scope["session"] = {"auth_user_id": 2}

    first_dir = user_upload_dir(first, tmp_path, "almabi")
    second_dir = user_upload_dir(second, tmp_path, "almabi")

    assert first_dir != second_dir
    assert first_dir == tmp_path / "almabi" / "users" / "1"
    assert second_dir == tmp_path / "almabi" / "users" / "2"


def test_user_resolver_reads_legacy_uuid_file_without_directory_escape(tmp_path: Path):
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
    request.scope["session"] = {"auth_user_id": 10}
    legacy = tmp_path / "almabi"
    legacy.mkdir()
    workbook = legacy / "cost-0123456789abcdef.xlsx"
    workbook.write_bytes(b"legacy")

    assert resolve_user_stored_xlsx(request, tmp_path, "almabi", workbook.name) == workbook.resolve()
    assert resolve_user_stored_xlsx(request, tmp_path, "almabi", "../outside.xlsx") is None


def test_request_body_limit_rejects_streamed_oversize_body():
    async def endpoint(request):
        return JSONResponse({"length": len(await request.body())})

    limited = RequestBodyLimitMiddleware(
        Starlette(routes=[Route("/upload", endpoint, methods=["POST"])]),
        max_bytes=4,
    )
    with TestClient(limited) as client:
        response = client.post("/upload", content=b"12345")

    assert response.status_code == 413


def test_xlsx_container_rejects_zip_bomb_ratio(tmp_path: Path):
    workbook = tmp_path / "bomb.xlsx"
    with ZipFile(workbook, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("xl/worksheets/sheet1.xml", "0" * (2 * 1024 * 1024))

    with pytest.raises(ValueError, match="коэффициент сжатия"):
        validate_xlsx_container(workbook)


def test_retention_is_dry_run_by_default_and_journals_apply(tmp_path: Path):
    uploads = tmp_path / "uploads"
    logs = tmp_path / "logs"
    uploads.mkdir()
    logs.mkdir()
    old_upload = uploads / "old.xlsx"
    old_upload.write_bytes(b"x")
    old_log = logs / "old.json"
    old_log.write_text("{}", encoding="utf-8")
    old_timestamp = datetime(2020, 1, 1, tzinfo=UTC).timestamp()
    os.utime(old_upload, (old_timestamp, old_timestamp))
    os.utime(old_log, (old_timestamp, old_timestamp))

    report = cleanup(
        uploads_dir=uploads,
        logs_dir=logs,
        upload_retention_days=30,
        log_retention_days=30,
    )
    assert report["dry_run"] is True
    assert old_upload.exists() and old_log.exists()

    applied = cleanup(
        uploads_dir=uploads,
        logs_dir=logs,
        upload_retention_days=30,
        log_retention_days=30,
        apply=True,
    )
    assert len(applied["deleted"]) == 2
    assert not old_upload.exists() and not old_log.exists()
    assert (logs / "retention.jsonl").is_file()


def test_production_settings_reject_weak_session_secret(tmp_path: Path):
    settings = Settings(
        _env_file=None,
        DEBUG=False,
        AUTH_ENABLED=True,
        SESSION_HTTPS_ONLY=True,
        SESSION_SECRET="change-me-in-production",
        UPLOADS_DIR=tmp_path / "uploads",
        RUNTIME_DIR=tmp_path / "runtime",
        LOGS_DIR=tmp_path / "logs",
    )
    with pytest.raises(RuntimeError, match="SESSION_SECRET"):
        settings.validate_security()


def test_dashboard_has_security_headers_and_local_assets(app_client):
    response = app_client.get("/dashboard/almabi")

    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert "cdn.jsdelivr.net" not in response.text
    assert "fonts.googleapis.com" not in response.text
    assert "/static/dist/chart_vendor.js" in response.text
    assert 'nonce="' in response.text


def test_dashboard_sources_escape_excel_text():
    dashboard = Path("templates/almabi_dashboard.html").read_text(encoding="utf-8")
    test_excel = Path("assets/src/test_excel_panel.js").read_text(encoding="utf-8")

    assert "${escapeHtml(article.name)}" in dashboard
    assert "${escapeHtml(node.name)}" in dashboard
    assert "${escapeHtml(row.name)}" in dashboard
    assert "escapeHtml(row[column])" in test_excel
