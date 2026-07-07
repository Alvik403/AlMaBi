from __future__ import annotations

from urllib.parse import quote

from fastapi.testclient import TestClient


def test_root_redirects_to_dashboard(app_client):
    response = app_client.get("/", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"].endswith("/dashboard/almabi-test")


def test_dashboard_uses_fixture_file(app_client):
    response = app_client.get("/dashboard")

    assert response.status_code == 200
    assert "Al Ma BI" in response.text


def test_almabi_dashboard_redirects_to_test(app_client):
    response = app_client.get("/dashboard/almabi", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"].endswith("/dashboard/almabi-test")


def test_almabi_test_dashboard_available(app_client):
    response = app_client.get("/dashboard/almabi-test")

    assert response.status_code == 200
    assert "Тест BI" in response.text
    assert "Сводная информация" in response.text
    assert "almabiConsolidatedBody" in response.text
    assert "data-tax-bucket" in response.text
    assert "data-dashboard-toolbar-toggle" in response.text
    assert "Al Ma BI" in response.text
    assert "test_pq" in response.text
    assert "AlMaBi R&D" not in response.text


def test_almabi_test_excel_page_available(app_client):
    response = app_client.get("/dashboard/almabi-test-excel")

    assert response.status_code == 200
    assert "Тест Excel" in response.text
    assert "data-test-excel-root" in response.text


def test_almabi_test_excel_cost_tab(app_client):
    response = app_client.get("/dashboard/almabi-test-excel?tab=cost")

    assert response.status_code == 200
    assert "Себестоимость" in response.text
    assert "projects_file" in response.text


def test_almabi_test_excel_projects_tab(app_client):
    response = app_client.get("/dashboard/almabi-test-excel?tab=projects")

    assert response.status_code == 200
    assert "data-test-excel-panel=\"projects\"" in response.text
    assert "Раздел = «Выручка»" in response.text


def test_almabi_test_excel_buh_tab(app_client):
    response = app_client.get("/dashboard/almabi-test-excel?tab=buh")

    assert response.status_code == 200
    assert "data-test-excel-panel=\"buh\"" in response.text
    assert "Бух.регистр" in response.text
    assert "revenue_file" in response.text


def test_almabi_revenue_report_page(app_client):
    response = app_client.get("/dashboard/almabi-revenue-report")

    assert response.status_code == 200
    assert "Отчёт по выручке" in response.text
    assert "data-revenue-report-root" in response.text


def test_almabi_cost_report_page(app_client):
    response = app_client.get("/dashboard/almabi-cost-report")

    assert response.status_code == 200
    assert "Отчёт по себестоимости" in response.text
    assert "data-cost-report-root" in response.text


def test_almabi_other_income_report_page(app_client):
    response = app_client.get("/dashboard/almabi-other-income-report")

    assert response.status_code == 200
    assert "Отчёт по прочим доходам" in response.text
    assert "data-other-income-report-root" in response.text


def test_almabi_other_income_report_upload_api(app_client, tmp_path):
    from tests.test_almabi_exports import (
        create_cost_workbook,
        create_other_income_buh_workbook,
        create_realization_workbook,
    )

    buh_path = tmp_path / "buh.xlsx"
    cost_path = tmp_path / "cost.xlsx"
    realization_path = tmp_path / "realization.xlsx"
    create_other_income_buh_workbook(buh_path)
    create_cost_workbook(cost_path)
    create_realization_workbook(realization_path, document="Другой документ")

    with buh_path.open("rb") as buh_handle, cost_path.open("rb") as cost_handle, realization_path.open("rb") as revenue_handle:
        response = app_client.post(
            "/api/almabi-other-income-report/upload",
            files={
                "buh_file": ("buh.xlsx", buh_handle, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
                "cost_file": ("cost.xlsx", cost_handle, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
                "revenue_file": ("realization.xlsx", revenue_handle, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            },
        )

    assert response.status_code == 201
    payload = response.json()
    assert payload["summary"]["total_amount"] == 400_000
    assert len(payload["tree"]) >= 1


def test_almabi_other_expense_report_page(app_client):
    response = app_client.get("/dashboard/almabi-other-expense-report")

    assert response.status_code == 200
    assert "Отчёт по прочим расходам" in response.text
    assert "data-other-expense-report-root" in response.text
    assert "report_page.js" in response.text
    assert "data-other-expense-report-tree" in response.text


def test_almabi_other_expense_report_upload_api(app_client, tmp_path):
    from tests.test_almabi_exports import (
        create_cost_workbook,
        create_other_expense_buh_workbook,
        create_realization_workbook,
    )

    buh_path = tmp_path / "buh.xlsx"
    cost_path = tmp_path / "cost.xlsx"
    realization_path = tmp_path / "realization.xlsx"
    create_other_expense_buh_workbook(buh_path)
    create_cost_workbook(cost_path)
    create_realization_workbook(realization_path, document="Другой документ")

    with buh_path.open("rb") as buh_handle, cost_path.open("rb") as cost_handle, realization_path.open("rb") as revenue_handle:
        response = app_client.post(
            "/api/almabi-other-expense-report/upload",
            files={
                "buh_file": ("buh.xlsx", buh_handle, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
                "cost_file": ("cost.xlsx", cost_handle, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
                "revenue_file": ("realization.xlsx", revenue_handle, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            },
        )

    assert response.status_code == 201
    payload = response.json()
    assert payload["summary"]["total_amount"] == -50_000
    assert len(payload["tree"]) >= 1


def test_almabi_commercial_expense_report_page(app_client):
    response = app_client.get("/dashboard/almabi-commercial-expense-report")

    assert response.status_code == 200
    assert "Отчёт по коммерческим расходам" in response.text
    assert "data-commercial-expense-report-root" in response.text


def test_almabi_commercial_expense_report_upload_api(app_client, tmp_path):
    from tests.test_almabi_exports import create_buh_workbook, create_cost_workbook, create_realization_workbook

    buh_path = tmp_path / "buh.xlsx"
    cost_path = tmp_path / "cost.xlsx"
    realization_path = tmp_path / "realization.xlsx"
    create_buh_workbook(buh_path)
    create_cost_workbook(cost_path)
    create_realization_workbook(realization_path)

    with buh_path.open("rb") as buh_handle, cost_path.open("rb") as cost_handle, realization_path.open("rb") as revenue_handle:
        response = app_client.post(
            "/api/almabi-commercial-expense-report/upload",
            files={
                "buh_file": ("buh.xlsx", buh_handle, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
                "cost_file": ("cost.xlsx", cost_handle, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
                "revenue_file": ("realization.xlsx", revenue_handle, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            },
        )

    assert response.status_code == 201
    payload = response.json()
    assert payload["summary"]["total_amount"] == -50_000
    assert payload["tree"][0]["name"] == "Реклама"


def test_almabi_management_expense_report_page(app_client):
    response = app_client.get("/dashboard/almabi-management-expense-report")

    assert response.status_code == 200
    assert "Отчёт по управленческим расходам" in response.text
    assert "data-management-expense-report-root" in response.text


def test_almabi_management_expense_report_upload_api(app_client, tmp_path):
    from tests.test_almabi_exports import (
        create_cost_workbook,
        create_management_expense_buh_workbook,
        create_realization_workbook,
    )

    buh_path = tmp_path / "buh.xlsx"
    cost_path = tmp_path / "cost.xlsx"
    realization_path = tmp_path / "realization.xlsx"
    create_management_expense_buh_workbook(buh_path)
    create_cost_workbook(cost_path)
    create_realization_workbook(realization_path, document="Другой документ")

    with buh_path.open("rb") as buh_handle, cost_path.open("rb") as cost_handle, realization_path.open("rb") as revenue_handle:
        response = app_client.post(
            "/api/almabi-management-expense-report/upload",
            files={
                "buh_file": ("buh.xlsx", buh_handle, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
                "cost_file": ("cost.xlsx", cost_handle, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
                "revenue_file": ("realization.xlsx", revenue_handle, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            },
        )

    assert response.status_code == 201
    payload = response.json()
    assert payload["summary"]["total_amount"] == -75_000
    assert payload["tree"][0]["name"] == "Аренда офиса"


def test_almabi_operating_profit_report_page(app_client):
    response = app_client.get("/dashboard/almabi-operating-profit-report")

    assert response.status_code == 200
    assert "Операционная прибыль" in response.text
    assert "data-operating-profit-report-root" in response.text
    assert "Состав расчёта" in response.text


def test_almabi_operating_profit_report_upload_api(app_client, tmp_path):
    from tests.test_almabi_exports import create_buh_workbook, create_cost_workbook, create_realization_workbook

    buh_path = tmp_path / "buh.xlsx"
    cost_path = tmp_path / "cost.xlsx"
    realization_path = tmp_path / "realization.xlsx"
    create_buh_workbook(buh_path)
    create_cost_workbook(cost_path)
    create_realization_workbook(realization_path)

    with buh_path.open("rb") as buh_handle, cost_path.open("rb") as cost_handle, realization_path.open("rb") as revenue_handle:
        response = app_client.post(
            "/api/almabi-operating-profit-report/upload",
            files={
                "buh_file": ("buh.xlsx", buh_handle, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
                "cost_file": ("cost.xlsx", cost_handle, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
                "revenue_file": ("realization.xlsx", revenue_handle, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            },
        )

    assert response.status_code == 201
    payload = response.json()
    assert payload["summary"]["total_amount"] == 550_000
    assert payload["summary"]["component_totals"]["Выручка"] == 1_000_000
    assert payload["summary"]["component_totals"]["Себестоимость"] == -400_000
    assert len(payload["tree"]) >= 3


def test_almabi_profit_before_tax_report_page(app_client):
    response = app_client.get("/dashboard/almabi-profit-before-tax-report")

    assert response.status_code == 200
    assert "Прибыль/убыток до налогообложения" in response.text
    assert "data-profit-before-tax-report-root" in response.text
    assert "Состав расчёта" in response.text


def test_almabi_profit_before_tax_report_upload_api(app_client, tmp_path):
    from tests.test_almabi_exports import (
        create_cost_workbook,
        create_profit_before_tax_buh_workbook,
        create_realization_workbook,
    )

    buh_path = tmp_path / "buh.xlsx"
    cost_path = tmp_path / "cost.xlsx"
    realization_path = tmp_path / "realization.xlsx"
    create_profit_before_tax_buh_workbook(buh_path)
    create_cost_workbook(cost_path)
    create_realization_workbook(realization_path)

    with buh_path.open("rb") as buh_handle, cost_path.open("rb") as cost_handle, realization_path.open("rb") as revenue_handle:
        response = app_client.post(
            "/api/almabi-profit-before-tax-report/upload",
            files={
                "buh_file": ("buh.xlsx", buh_handle, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
                "cost_file": ("cost.xlsx", cost_handle, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
                "revenue_file": ("realization.xlsx", revenue_handle, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            },
        )

    assert response.status_code == 201
    payload = response.json()
    assert payload["summary"]["total_amount"] == 900_000
    assert payload["summary"]["component_totals"]["Операционная прибыль"] == 550_000
    assert payload["summary"]["component_totals"]["Прочие доходы"] == 400_000
    assert payload["summary"]["component_totals"]["Прочие расходы"] == -50_000
    assert len(payload["tree"]) == 3


def test_almabi_taxes_report_page(app_client):
    response = app_client.get("/dashboard/almabi-taxes-report")

    assert response.status_code == 200
    assert "Налоги" in response.text
    assert "data-taxes-report-root" in response.text
    assert "Состав расчёта" in response.text
    assert "2%" in response.text
    assert "25%" in response.text


def test_almabi_taxes_report_upload_api(app_client, tmp_path):
    from tests.test_almabi_exports import (
        create_cost_workbook,
        create_profit_before_tax_buh_workbook,
        create_realization_workbook,
    )

    buh_path = tmp_path / "buh.xlsx"
    cost_path = tmp_path / "cost.xlsx"
    realization_path = tmp_path / "realization.xlsx"
    create_profit_before_tax_buh_workbook(buh_path)
    create_cost_workbook(cost_path)
    create_realization_workbook(realization_path)

    with buh_path.open("rb") as buh_handle, cost_path.open("rb") as cost_handle, realization_path.open("rb") as revenue_handle:
        response = app_client.post(
            "/api/almabi-taxes-report/upload",
            files={
                "buh_file": ("buh.xlsx", buh_handle, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
                "cost_file": ("cost.xlsx", cost_handle, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
                "revenue_file": ("realization.xlsx", revenue_handle, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            },
        )

    assert response.status_code == 201
    payload = response.json()
    assert payload["summary"]["total_amount"] == -132_500
    assert payload["summary"]["component_totals"]["Льготные проекты"] == -20_000
    assert payload["summary"]["component_totals"]["Нельготные проекты"] == -112_500
    assert len(payload["tree"]) == 2


def test_almabi_net_profit_report_page(app_client):
    response = app_client.get("/dashboard/almabi-net-profit-report")

    assert response.status_code == 200
    assert "Чистая прибыль" in response.text
    assert "data-net-profit-report-root" in response.text
    assert "Состав расчёта" in response.text


def test_almabi_net_profit_report_upload_api(app_client, tmp_path):
    from tests.test_almabi_exports import (
        create_cost_workbook,
        create_profit_before_tax_buh_workbook,
        create_realization_workbook,
    )

    buh_path = tmp_path / "buh.xlsx"
    cost_path = tmp_path / "cost.xlsx"
    realization_path = tmp_path / "realization.xlsx"
    create_profit_before_tax_buh_workbook(buh_path)
    create_cost_workbook(cost_path)
    create_realization_workbook(realization_path)

    with buh_path.open("rb") as buh_handle, cost_path.open("rb") as cost_handle, realization_path.open("rb") as revenue_handle:
        response = app_client.post(
            "/api/almabi-net-profit-report/upload",
            files={
                "buh_file": ("buh.xlsx", buh_handle, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
                "cost_file": ("cost.xlsx", cost_handle, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
                "revenue_file": ("realization.xlsx", revenue_handle, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            },
        )

    assert response.status_code == 201
    payload = response.json()
    assert payload["summary"]["total_amount"] == 767_500
    assert payload["summary"]["component_totals"]["Прибыль/убыток до налогообложения"] == 900_000
    assert payload["summary"]["component_totals"]["Налоги"] == -132_500
    assert len(payload["tree"]) == 2


def test_almabi_cost_report_upload_api(app_client, tmp_path):
    from tests.test_almabi_exports import create_buh_workbook, create_cost_workbook, create_realization_workbook

    buh_path = tmp_path / "buh.xlsx"
    cost_path = tmp_path / "cost.xlsx"
    realization_path = tmp_path / "realization.xlsx"
    create_buh_workbook(buh_path)
    create_cost_workbook(cost_path)
    create_realization_workbook(realization_path)

    with buh_path.open("rb") as buh_handle, cost_path.open("rb") as cost_handle, realization_path.open("rb") as revenue_handle:
        response = app_client.post(
            "/api/almabi-cost-report/upload",
            files={
                "buh_file": ("buh.xlsx", buh_handle, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
                "cost_file": ("cost.xlsx", cost_handle, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
                "revenue_file": ("realization.xlsx", revenue_handle, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            },
        )

    assert response.status_code == 201
    payload = response.json()
    assert payload["summary"]["total_amount"] == -400_000
    assert len(payload["tree"]) >= 1


def test_almabi_revenue_report_upload_api(app_client, tmp_path):
    from tests.test_almabi_exports import create_buh_workbook, create_cost_workbook, create_realization_workbook

    buh_path = tmp_path / "buh.xlsx"
    cost_path = tmp_path / "cost.xlsx"
    realization_path = tmp_path / "realization.xlsx"
    create_buh_workbook(buh_path)
    create_cost_workbook(cost_path)
    create_realization_workbook(realization_path)

    with buh_path.open("rb") as buh_handle, cost_path.open("rb") as cost_handle, realization_path.open("rb") as revenue_handle:
        response = app_client.post(
            "/api/almabi-revenue-report/upload",
            files={
                "buh_file": ("buh.xlsx", buh_handle, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
                "cost_file": ("cost.xlsx", cost_handle, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
                "revenue_file": ("realization.xlsx", revenue_handle, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            },
        )

    assert response.status_code == 201
    payload = response.json()
    assert payload["summary"]["total_amount"] == 1_000_000
    assert len(payload["tree"]) >= 1


def test_almabi_test_excel_upload_api(app_client, tmp_path):
    from tests.test_almabi_exports import create_realization_workbook

    path = tmp_path / "realization.xlsx"
    create_realization_workbook(path)

    with path.open("rb") as handle:
        response = app_client.post(
            "/api/almabi-test-excel/revenue/upload",
            files={"file": ("realization.xlsx", handle, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )

    assert response.status_code == 201
    payload = response.json()
    assert payload["loaded"] is True
    assert payload["summary"]["row_count"] == 1
    assert payload["rows"][0]["Раздел"] == "Доходы"


def test_almabi_test_excel_cost_upload_api(app_client, tmp_path):
    from tests.test_almabi_exports import create_cost_workbook, create_realization_workbook

    cost_path = tmp_path / "cost.xlsx"
    realization_path = tmp_path / "realization.xlsx"
    create_cost_workbook(cost_path)
    create_realization_workbook(realization_path)

    with cost_path.open("rb") as cost_handle, realization_path.open("rb") as projects_handle:
        response = app_client.post(
            "/api/almabi-test-excel/cost/upload",
            files={
                "cost_file": ("cost.xlsx", cost_handle, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
                "projects_file": ("realization.xlsx", projects_handle, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            },
        )

    assert response.status_code == 201
    payload = response.json()
    assert payload["loaded"] is True
    assert payload["summary"]["row_count"] >= 2
    sections = {row["Основной раздел"] for row in payload["rows"]}
    assert "Расходы" in sections
    assert "Доходы" in sections
    assert any(row["Раздел"] == "Выручка" for row in payload["rows"])


def test_almabi_test_excel_projects_upload_api(app_client, tmp_path):
    from tests.test_almabi_exports import create_realization_workbook

    path = tmp_path / "realization.xlsx"
    create_realization_workbook(path)

    with path.open("rb") as handle:
        response = app_client.post(
            "/api/almabi-test-excel/projects/upload",
            files={"file": ("realization.xlsx", handle, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )

    assert response.status_code == 201
    payload = response.json()
    assert payload["loaded"] is True
    assert payload["summary"]["row_count"] == 1
    assert payload["rows"][0]["Раздел"] == "Выручка"


def test_almabi_test_excel_buh_upload_api(app_client, tmp_path):
    from tests.test_almabi_exports import create_buh_workbook, create_cost_workbook, create_realization_workbook

    buh_path = tmp_path / "buh.xlsx"
    cost_path = tmp_path / "cost.xlsx"
    realization_path = tmp_path / "realization.xlsx"
    create_buh_workbook(buh_path)
    create_cost_workbook(cost_path)
    create_realization_workbook(realization_path)

    with buh_path.open("rb") as buh_handle, cost_path.open("rb") as cost_handle, realization_path.open("rb") as revenue_handle:
        response = app_client.post(
            "/api/almabi-test-excel/buh/upload",
            files={
                "buh_file": ("buh.xlsx", buh_handle, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
                "cost_file": ("cost.xlsx", cost_handle, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
                "revenue_file": ("realization.xlsx", revenue_handle, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            },
        )

    assert response.status_code == 201
    payload = response.json()
    assert payload["loaded"] is True
    assert payload["summary"]["row_count"] >= 3
    assert payload["summary"]["amount_column"] == "Сумма БУ"
    assert any(row["Раздел"] == "Себестоимость" and row["Сумма БУ"] == -400_000 for row in payload["rows"])


def test_almabi_test_summary_matches_levels_spec():
    from almabi_test_levels import build_test_summary_rows

    rows = build_test_summary_rows()
    assert len(rows) == 10
    assert rows[0]["name"] == "Выручка"
    assert rows[0]["children"][0]["name"] == "Направление"
    assert rows[0]["total_fact"] == 0


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
