from __future__ import annotations

from urllib.parse import quote

from fastapi.testclient import TestClient


def test_root_redirects_to_dashboard(app_client):
    response = app_client.get("/", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"].endswith("/dashboard/almabi")


def test_dashboard_uses_fixture_file(app_client):
    response = app_client.get("/dashboard")

    assert response.status_code == 200
    assert "AlMaBi BI" in response.text


def test_almabi_dashboard_available(app_client):
    response = app_client.get("/dashboard/almabi")

    assert response.status_code == 200
    assert "Сводная информация" in response.text
    assert "Детализация по контрагентам" in response.text


def test_excel_editor_page_available(app_client):
    response = app_client.get("/dashboard/excel")

    assert response.status_code == 200
    assert "Просмотр Excel" in response.text
    assert "/static/dist/excel.js" in response.text


def test_active_excel_download(app_client):
    response = app_client.get("/api/excel/active")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert response.content.startswith(b"PK")


def test_debug_routes_available_when_debug_enabled(app_client):
    response = app_client.get("/debug")

    assert response.status_code == 200
    assert "Debug-инструменты" in response.text


def test_path_routes_support_slashes_in_class_and_service(app_client):
    class_name = quote("экспорт/сибур", safe="/")
    service_name = quote("Комплексная/услуга 2", safe="/")

    response = app_client.get(f"/dashboard/class/{class_name}/service/{service_name}")

    assert response.status_code == 200
    assert "Комплексная/услуга 2" in response.text


def test_active_file_cookie_does_not_change_latest(app_client):
    files_before = app_client.get("/api/files").json()
    latest_id = files_before["latest_file_id"]

    response = app_client.post(f"/api/session/active-file/{latest_id}")
    files_after = response.json()["files"]

    assert response.status_code == 200
    assert files_after["active_file_id"] == latest_id
    assert files_after["latest_file_id"] == latest_id


def test_excel_save_version_updates_latest_for_current_session_only(app_client, sample_excel_path):
    with TestClient(app_client.app) as other_client:
        other_before = other_client.get("/api/files").json()
        other_active_id = other_before["active_file_id"]

        with sample_excel_path.open("rb") as workbook:
            response = app_client.post(
                "/api/excel/save-version",
                files={
                    "file": (
                        "edited.xlsx",
                        workbook,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                },
            )

        assert response.status_code == 201
        payload = response.json()
        new_file_id = payload["file"]["id"]
        assert payload["files"]["active_file_id"] == new_file_id
        assert payload["files"]["latest_file_id"] == new_file_id

        other_after = other_client.get("/api/files").json()
        assert other_after["active_file_id"] == other_active_id
        assert other_after["latest_file_id"] == new_file_id
        assert other_after["has_newer_version"] is True
