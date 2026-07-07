from __future__ import annotations

from pathlib import Path

from almabi_export_parsers import parse_exports
from almabi_pipeline_audit import PipelineAuditLog
from almabi_test_builder import build_test_dashboard_from_pipeline, filter_facts_by_tax_bucket
from almabi_test_pipeline import TestPipelineResult, build_test_facts
from tests.test_almabi_exports import create_buh_workbook, create_cost_workbook, create_realization_workbook


def _find_row(rows: list[dict], name: str) -> dict:
    return next(row for row in rows if row["name"] == name)


def _find_child(node: dict, name: str) -> dict:
    return next(child for child in node.get("children") or [] if child["name"] == name)


def test_filter_facts_by_tax_bucket(tmp_path: Path):
    paths = {
        "buh": tmp_path / "buh.xlsx",
        "realization": tmp_path / "realization.xlsx",
        "cost": tmp_path / "cost.xlsx",
    }
    create_buh_workbook(paths["buh"])
    create_realization_workbook(paths["realization"])
    create_cost_workbook(paths["cost"])

    facts = build_test_facts(parse_exports(paths)).facts
    privileged = filter_facts_by_tax_bucket(facts, "Льготные проекты")
    assert privileged
    assert all(item.kpi_l1 == "Выручка" for item in privileged)


def test_consolidated_table_order_and_tax_filter(tmp_path: Path):
    paths = {
        "buh": tmp_path / "buh.xlsx",
        "realization": tmp_path / "realization.xlsx",
        "cost": tmp_path / "cost.xlsx",
    }
    create_buh_workbook(paths["buh"])
    create_realization_workbook(paths["realization"])
    create_cost_workbook(paths["cost"])

    pipeline = TestPipelineResult(result=build_test_facts(parse_exports(paths)), audit=PipelineAuditLog())
    dashboard = build_test_dashboard_from_pipeline(pipeline, upload_names={})

    all_rows = dashboard["consolidated_by_tax"]["all"]
    assert [row["name"] for row in all_rows] == [
        "Выручка",
        "Себестоимость",
        "Коммерческие расходы",
        "Управленческие расходы",
        "Операционная прибыль",
        "Прочие доходы",
        "Прочие расходы",
        "Прибыль/убыток до налогообложения",
        "Налоги",
        "Чистая прибыль",
    ]
    assert all_rows[4]["is_calculated"] is True
    assert all_rows[9]["is_calculated"] is True

    privileged = dashboard["consolidated_by_tax"]["Льготные проекты"]
    privileged_revenue = next(row for row in privileged if row["name"] == "Выручка")
    non_privileged_revenue = next(
        row for row in dashboard["consolidated_by_tax"]["Нельготные проекты"] if row["name"] == "Выручка"
    )
    assert privileged_revenue["total_fact"] > 0
    assert non_privileged_revenue["total_fact"] == 0


def test_summary_by_tax_zeros_opposite_bucket(tmp_path: Path):
    paths = {
        "buh": tmp_path / "buh.xlsx",
        "realization": tmp_path / "realization.xlsx",
        "cost": tmp_path / "cost.xlsx",
    }
    create_buh_workbook(paths["buh"])
    create_realization_workbook(paths["realization"])
    create_cost_workbook(paths["cost"])

    pipeline = TestPipelineResult(result=build_test_facts(parse_exports(paths)), audit=PipelineAuditLog())
    dashboard = build_test_dashboard_from_pipeline(pipeline, upload_names={})

    privileged_rows = dashboard["summary_by_tax"]["Льготные проекты"]
    privileged_commercial = _find_child(
        _find_row(privileged_rows, "Коммерческие расходы"),
        "Льготные проекты",
    )
    privileged_non = _find_child(
        _find_row(privileged_rows, "Коммерческие расходы"),
        "Нельготные проекты",
    )
    assert privileged_commercial["total_fact"] == 0
    assert privileged_non["total_fact"] == 0

    operating = _find_row(privileged_rows, "Операционная прибыль")
    privileged_operating = _find_child(operating, "Льготные проекты")
    non_operating = _find_child(operating, "Нельготные проекты")
    assert privileged_operating["total_fact"] > 0
    assert non_operating["total_fact"] == 0
