from __future__ import annotations

from pathlib import Path

import pytest

from almabi_dashboard_builder import _build_summary_rows, load_almabi_dashboard_from_exports
from almabi_plan_forecast_parser import parse_plan_forecast_workbook, validate_plan_forecast_workbook
from almabi_pipeline import Fact
from almabi_test_dashboard_builder import build_test_summary_rows_from_facts

FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "plan_forecast_sample.xlsx"


def _find_child(node: dict, name: str) -> dict:
    return next(child for child in node["children"] if child["name"] == name)


def test_validate_plan_forecast_workbook():
    validate_plan_forecast_workbook(FIXTURE_PATH)


def test_parse_plan_forecast_sample():
    result = parse_plan_forecast_workbook(FIXTURE_PATH)
    assert not result.plan_facts
    assert len(result.forecast_facts) == 1
    fact = result.forecast_facts[0]
    assert fact.kpi_l1 == "Выручка"
    assert fact.month == "Апрель"
    assert fact.amount_buh == 18_450_000.0


def test_summary_rows_use_forecast_from_file():
    buh_facts = [
        Fact(
            kpi_l1="Выручка",
            month="Апрель",
            amount_buh=10_000_000,
            amount_nu=10_000_000,
            direction="Направление А",
        )
    ]
    forecast_facts = parse_plan_forecast_workbook(FIXTURE_PATH).forecast_facts
    rows = _build_summary_rows(buh_facts, forecast_facts=forecast_facts)
    revenue = next(row for row in rows if row["name"] == "Выручка")
    assert revenue["values"]["Прогноз"]["Апрель"] == 18_450_000.0
    assert revenue["values"]["План"]["Апрель"] == 0.0


def test_summary_rows_add_plan_only_dimensions():
    buh_facts = [
        Fact(
            kpi_l1="Выручка",
            month="Апрель",
            amount_buh=10_000_000,
            amount_nu=10_000_000,
            direction="Направление А",
        )
    ]
    plan_facts = [
        Fact(
            kpi_l1="Выручка",
            month="Май",
            amount_buh=5_000_000,
            amount_nu=5_000_000,
            direction="Перепродажа",
            project_group="Производство игрушек",
            project="Проект X",
        )
    ]
    forecast_facts = [
        Fact(
            kpi_l1="Выручка",
            month="Июнь",
            amount_buh=3_000_000,
            amount_nu=3_000_000,
            direction="Перепродажа",
            project_group="Производство игрушек",
            project="Проект Y",
        )
    ]
    rows = _build_summary_rows(buh_facts, plan_facts=plan_facts, forecast_facts=forecast_facts)
    revenue = next(row for row in rows if row["name"] == "Выручка")

    assert _find_child(revenue, "Направление А")["values"]["Факт БУ"]["Апрель"] == 10_000_000
    resale = _find_child(revenue, "Перепродажа")
    toys = _find_child(resale, "Производство игрушек")
    project_x = _find_child(toys, "Проект X")
    project_y = _find_child(toys, "Проект Y")

    assert project_x["values"]["План"]["Май"] == 5_000_000
    assert project_x["values"]["Факт БУ"]["Май"] == 0.0
    assert project_y["values"]["Прогноз"]["Июнь"] == 3_000_000
    assert project_y["values"]["Факт БУ"]["Июнь"] == 0.0


def test_test_summary_rows_add_plan_only_dimensions():
    buh_facts = [
        Fact(
            kpi_l1="Выручка",
            month="Апрель",
            amount_buh=10_000_000,
            amount_nu=10_000_000,
            direction="Направление А",
        )
    ]
    plan_facts = [
        Fact(
            kpi_l1="Выручка",
            month="Май",
            amount_buh=5_000_000,
            amount_nu=5_000_000,
            direction="Перепродажа",
            project_group="Производство игрушек",
            project="Проект X",
        )
    ]
    rows = build_test_summary_rows_from_facts(buh_facts, plan_facts=plan_facts)
    revenue = next(row for row in rows if row["name"] == "Выручка")
    project_x = _find_child(_find_child(_find_child(revenue, "Перепродажа"), "Производство игрушек"), "Проект X")
    assert project_x["values"]["План"]["Май"] == 5_000_000


def test_load_dashboard_with_plan_forecast_file(tmp_path: Path):
    from tests.test_almabi_exports import (
        create_buh_workbook,
        create_cost_workbook,
        create_realization_workbook,
    )

    buh = tmp_path / "buh.xlsx"
    realization = tmp_path / "realization.xlsx"
    cost = tmp_path / "cost.xlsx"
    create_buh_workbook(buh)
    create_realization_workbook(realization)
    create_cost_workbook(cost)

    dashboard = load_almabi_dashboard_from_exports(
        {"buh": buh, "realization": realization, "cost": cost},
        upload_names={"buh": "buh.xlsx", "realization": "realization.xlsx", "cost": "cost.xlsx"},
        plan_forecast_path=FIXTURE_PATH,
    )
    assert dashboard["meta"]["plan_forecast_loaded"] is True
    revenue = next(row for row in dashboard["summary_rows"] if row["name"] == "Выручка")
    assert revenue["values"]["Прогноз"]["Апрель"] == 18_450_000.0
