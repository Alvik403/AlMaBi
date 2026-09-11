from __future__ import annotations

from pathlib import Path

import pytest

from almabi_pipeline import Fact, PipelineResult
from almabi_pipeline_audit import PipelineAuditLog
from almabi_test_builder import (
    build_test_dashboard_from_pipeline,
    filter_facts_by_dimensions_and_period,
)
from almabi_dashboard_builder import calendar_periods_for_years
from almabi_test_pipeline import TestPipelineResult as _TestPipelineResult
from tests.test_almabi_exports import (
    create_buh_workbook,
    create_cost_workbook,
    create_realization_workbook,
)


def _fact(
    *,
    period: str,
    direction: str,
    project_group: str,
    project: str,
    contract: str,
    amount: float,
) -> Fact:
    return Fact(
        kpi_l1="Выручка",
        month="Январь",
        period=period,
        amount_buh=amount,
        amount_nu=amount,
        direction=direction,
        project_group=project_group,
        project=project,
        contract=contract,
    )


@pytest.mark.parametrize(
    ("query_name", "query_value"),
    [
        ("direction", "Услуги"),
        ("project_group", "Группа А"),
        ("project", "Проект А"),
        ("contract", "Д-001"),
    ],
)
def test_filter_facts_by_each_dimension(query_name: str, query_value: str):
    facts = [
        _fact(
            period="2024-01",
            direction="Услуги",
            project_group="Группа А",
            project="Проект А",
            contract="Д-001",
            amount=100,
        ),
        _fact(
            period="2025-01",
            direction="Производство",
            project_group="Группа Б",
            project="Проект Б",
            contract="Д-002",
            amount=250,
        ),
    ]

    filtered = filter_facts_by_dimensions_and_period(
        facts,
        **{query_name: query_value},
    )

    assert len(filtered) == 1
    assert filtered[0].amount_buh == 100


def test_filter_facts_accepts_multiple_dimension_values():
    facts = [
        _fact(
            period="2024-01",
            direction="Услуги",
            project_group="Группа А",
            project="Проект А",
            contract="Д-001",
            amount=100,
        ),
        _fact(
            period="2025-01",
            direction="Производство",
            project_group="Группа Б",
            project="Проект Б",
            contract="Д-002",
            amount=250,
        ),
        _fact(
            period="2025-02",
            direction="Перепродажа",
            project_group="Группа В",
            project="Проект В",
            contract="Д-003",
            amount=50,
        ),
    ]

    filtered = filter_facts_by_dimensions_and_period(
        facts,
        direction=["Услуги", "Производство"],
    )

    assert {fact.direction for fact in filtered} == {"Услуги", "Производство"}
    assert sum(fact.amount_buh for fact in filtered) == 350


def test_filter_facts_cross_year_period_range():
    facts = [
        _fact(
            period=period,
            direction="Услуги",
            project_group="Группа",
            project="Проект",
            contract="Д-001",
            amount=amount,
        )
        for period, amount in (
            ("2024-01", 100),
            ("2024-12", 200),
            ("2025-01", 300),
        )
    ]

    filtered = filter_facts_by_dimensions_and_period(
        facts,
        period_from="2024-12",
        period_to="2025-01",
    )

    assert [fact.period for fact in filtered] == ["2024-12", "2025-01"]


def test_available_periods_include_full_calendar_year():
    assert calendar_periods_for_years(["2026-01", "2026-07"]) == [
        f"2026-{month:02d}" for month in range(1, 13)
    ]

    dashboard = build_test_dashboard_from_pipeline(
        _TestPipelineResult(
            result=PipelineResult(
                facts=[
                    _fact(
                        period="2026-01",
                        direction="Услуги",
                        project_group="Группа",
                        project="Проект",
                        contract="Д-001",
                        amount=100,
                    )
                ]
            ),
            audit=PipelineAuditLog(),
        ),
        upload_names={},
    )

    assert dashboard["available_periods"][0] == "2026-01"
    assert dashboard["available_periods"][-1] == "2026-12"
    assert dashboard["data_periods"] == ["2026-01"]
    assert dashboard["period_labels"]["2026-12"] == "Декабрь 2026"
    assert dashboard["months"] == ["2026-01"]


def test_cross_year_range_rebuilds_summary_calculated_charts_and_drills():
    facts = [
        _fact(
            period=period,
            direction="Услуги",
            project_group="Группа",
            project="Проект",
            contract="Д-001",
            amount=amount,
        )
        for period, amount in (("2024-01", 100), ("2025-01", 300))
    ]
    filtered = filter_facts_by_dimensions_and_period(
        facts,
        period_from="2025-01",
        period_to="2025-12",
    )
    dashboard = build_test_dashboard_from_pipeline(
        _TestPipelineResult(
            result=PipelineResult(facts=filtered),
            audit=PipelineAuditLog(),
        ),
        upload_names={},
    )

    revenue = next(row for row in dashboard["summary_rows"] if row["name"] == "Выручка")
    operating = next(
        row for row in dashboard["summary_rows"] if row["name"] == "Операционная прибыль"
    )
    assert dashboard["months"] == ["2025-01"]
    assert revenue["total_fact"] == 300
    assert operating["total_fact"] == 300
    assert set(revenue["drill"]["months"]) == {"2025-01"}
    assert dashboard["revenue_by_month"][0]["value"] == 300
    assert [item["period"] for item in dashboard["contractor_details"]] == ["2025-01"]


def test_period_range_is_not_applied_to_month_only_plan_facts():
    plan = [Fact("Выручка", "Январь", 100, 100)]

    filtered = filter_facts_by_dimensions_and_period(
        plan,
        period_from="2025-01",
        period_to="2025-12",
        apply_period=False,
    )

    assert filtered == plan


def _upload_dashboard_bundle(app_client, tmp_path: Path) -> None:
    paths = {
        "buh": tmp_path / "buh.xlsx",
        "realization": tmp_path / "realization.xlsx",
        "cost": tmp_path / "cost.xlsx",
    }
    create_buh_workbook(paths["buh"])
    create_realization_workbook(paths["realization"])
    create_cost_workbook(paths["cost"])
    with (
        paths["buh"].open("rb") as buh,
        paths["realization"].open("rb") as realization,
        paths["cost"].open("rb") as cost,
    ):
        response = app_client.post(
            "/api/almabi/files/upload-set",
            files={
                "buh_file": ("buh.xlsx", buh),
                "realization_file": ("realization.xlsx", realization),
                "cost_file": ("cost.xlsx", cost),
            },
        )
    assert response.status_code == 201


@pytest.mark.parametrize(
    ("query_name", "query_value"),
    [
        ("direction", "Услуги"),
        ("project_group", "Обслуживание"),
        ("project", "Обслуживание Долго"),
        ("contract", "Д-001"),
    ],
)
def test_dashboard_api_filters_dimensions_and_keeps_full_options(
    app_client,
    tmp_path: Path,
    query_name: str,
    query_value: str,
):
    _upload_dashboard_bundle(app_client, tmp_path)

    response = app_client.get(
        "/api/almabi/dashboard",
        params={query_name: query_value},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["meta"]["applied_filters"][query_name] == query_value
    assert query_value in payload["filters"][
        {
            "direction": "direction",
            "project_group": "projectGroup",
            "project": "project",
            "contract": "contract",
        }[query_name]
    ]
    revenue = next(row for row in payload["summary_rows"] if row["name"] == "Выручка")
    assert revenue["total_fact"] == 1_000_000


def test_dashboard_api_accepts_repeated_dimension_params(app_client, tmp_path: Path):
    _upload_dashboard_bundle(app_client, tmp_path)

    response = app_client.get(
        "/api/almabi/dashboard",
        params=[("direction", "Услуги"), ("direction", "Услуги")],
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["filter_tree"]
    assert payload["available_periods"]
    assert "Услуги" in [row["direction"] for row in payload["filter_tree"]]


@pytest.mark.parametrize(
    ("params", "message"),
    [
        ({"period_from": "2025-13"}, "YYYY-MM"),
        (
            {"period_from": "2025-02", "period_to": "2025-01"},
            "period_from",
        ),
    ],
)
def test_dashboard_api_rejects_invalid_periods(app_client, params, message):
    response = app_client.get("/api/almabi/dashboard", params=params)

    assert response.status_code == 400
    assert message in response.json()["detail"]


def test_dashboard_api_rejects_unknown_dimension_value(app_client, tmp_path: Path):
    _upload_dashboard_bundle(app_client, tmp_path)

    response = app_client.get(
        "/api/almabi/dashboard",
        params={"direction": "Неизвестное направление"},
    )

    assert response.status_code == 400
    assert "Неизвестное значение направления" in response.json()["detail"]


def test_dashboard_api_drill_expands_realization_rows(app_client, tmp_path: Path):
    _upload_dashboard_bundle(app_client, tmp_path)

    response = app_client.get("/api/almabi/dashboard")
    assert response.status_code == 200
    revenue = next(row for row in response.json()["summary_rows"] if row["name"] == "Выручка")
    drill = revenue["drill"]
    assert drill["type"] == "revenue_cost"
    period = next(iter(drill["months"]))
    lines = drill["months"][period]["lines"]
    assert lines
    assert "Реализация товаров" not in {line["name"] for line in lines}
    assert any(line["name"] == "Лицензия ПО" for line in lines)
