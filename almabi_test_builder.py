from __future__ import annotations

from pathlib import Path
from typing import Any

from almabi_charts_builder import build_analytics_charts
from almabi_contractor_builder import build_contractor_cards, build_contractor_details
from almabi_test_dashboard_builder import build_test_summary_rows_from_facts
from almabi_mock_data import MONTHS, SCENARIOS, UNITS

from almabi_dashboard_builder import (
    _chart_cost_structure,
    _chart_cost_structure_from_pq_rows,
    _chart_series,
    _collect_filter_values,
    _empty_cost_structure,
)
from almabi_excel_utils import tax_bucket
from almabi_pipeline import Fact
from almabi_test_pipeline import TestPipelineResult, run_test_pipeline

from almabi_test_levels import build_test_summary_rows, empty_chart_series

TAX_BUCKET_OPTIONS = ("Льготные проекты", "Нельготные проекты")

CONSOLIDATED_KPI_ORDER = (
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
)

CONSOLIDATED_CALCULATED_KPIS = frozenset(
    {
        "Операционная прибыль",
        "Прибыль/убыток до налогообложения",
        "Чистая прибыль",
    }
)


def _build_consolidated_table(summary_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    lookup = {row["name"]: row for row in summary_rows}
    consolidated: list[dict[str, Any]] = []
    for name in CONSOLIDATED_KPI_ORDER:
        row = lookup.get(name)
        if row is None:
            continue
        consolidated.append(
            {
                "name": name,
                "total_fact": float(row.get("total_fact") or 0),
                "total_plan": float(row.get("total_plan") or 0),
                "values": row.get("values") or {},
                "is_calculated": name in CONSOLIDATED_CALCULATED_KPIS,
            }
        )
    return consolidated


def _build_consolidated_by_tax(summary_by_tax: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    return {bucket: _build_consolidated_table(rows) for bucket, rows in summary_by_tax.items()}


def filter_facts_by_tax_bucket(facts: list[Fact], bucket: str) -> list[Fact]:
    return [fact for fact in facts if tax_bucket(fact.tax_type) == bucket]


def _build_summary_by_tax(
    facts: list[Fact],
    *,
    plan_facts: list[Fact] | None = None,
    forecast_facts: list[Fact] | None = None,
    pq_cost_rows: list[dict[str, object]] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    return {
        "all": build_test_summary_rows_from_facts(
            facts,
            plan_facts=plan_facts,
            forecast_facts=forecast_facts,
            pq_cost_rows=pq_cost_rows,
        ),
        **{
            bucket: build_test_summary_rows_from_facts(
                filter_facts_by_tax_bucket(facts, bucket),
                plan_facts=filter_facts_by_tax_bucket(plan_facts or [], bucket),
                forecast_facts=filter_facts_by_tax_bucket(forecast_facts or [], bucket),
            )
            for bucket in TAX_BUCKET_OPTIONS
        },
    }


def _build_charts_by_tax(
    facts: list[Fact],
    *,
    pq_cost_rows: list[dict[str, object]] | None = None,
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    all_structure = (
        _chart_cost_structure_from_pq_rows(pq_cost_rows)
        if pq_cost_rows
        else _chart_cost_structure(facts)
    )
    charts: dict[str, dict[str, list[dict[str, Any]]]] = {
        "all": {
            "revenue_by_month": _chart_series(facts, "Выручка"),
            "cost_by_month": _chart_series(facts, "Себестоимость"),
            "cost_structure_by_month": all_structure,
        }
    }
    for bucket in TAX_BUCKET_OPTIONS:
        bucket_facts = filter_facts_by_tax_bucket(facts, bucket)
        charts[bucket] = {
            "revenue_by_month": _chart_series(bucket_facts, "Выручка"),
            "cost_by_month": _chart_series(bucket_facts, "Себестоимость"),
            "cost_structure_by_month": _chart_cost_structure(bucket_facts),
        }
    return charts


def build_test_dashboard_from_pipeline(
    pipeline: TestPipelineResult,
    *,
    upload_names: dict[str, str],
    plan_facts: list[Fact] | None = None,
    forecast_facts: list[Fact] | None = None,
    plan_warnings: list[str] | None = None,
) -> dict[str, Any]:
    result = pipeline.result
    audit = pipeline.audit
    summary_by_tax = _build_summary_by_tax(
        result.facts,
        plan_facts=plan_facts,
        forecast_facts=forecast_facts,
        pq_cost_rows=pipeline.pq_cost_rows,
    )
    charts_by_tax = _build_charts_by_tax(result.facts, pq_cost_rows=pipeline.pq_cost_rows)
    summary_rows = summary_by_tax["all"]
    consolidated_by_tax = _build_consolidated_by_tax(summary_by_tax)
    revenue_chart = charts_by_tax["all"]["revenue_by_month"]
    cost_chart = charts_by_tax["all"]["cost_by_month"]
    contractor_details = build_contractor_details(result.facts)
    contractor_cards = build_contractor_cards(contractor_details)
    audit_summary = audit.to_dict()["summary"]
    dashboard = {
        "months": MONTHS,
        "scenarios": SCENARIOS,
        "units": UNITS,
        "filters": _collect_filter_values(
            result.facts,
            plan_facts=plan_facts,
            forecast_facts=forecast_facts,
        ),
        "summary_rows": summary_rows,
        "summary_by_tax": summary_by_tax,
        "consolidated_by_tax": consolidated_by_tax,
        "consolidated_kpi_order": list(CONSOLIDATED_KPI_ORDER),
        "charts_by_tax": charts_by_tax,
        "analytics_charts": build_analytics_charts(
            result.facts,
            summary_rows,
            plan_facts=plan_facts,
        ),
        "tax_bucket_options": ["all", *TAX_BUCKET_OPTIONS],
        "contractor_details": contractor_details,
        "contractor_cards": contractor_cards,
        "revenue_by_month": revenue_chart,
        "cost_by_month": cost_chart,
        "cost_structure_by_month": charts_by_tax["all"]["cost_structure_by_month"],
        "cost_structure_total": sum(item["value"] for item in cost_chart),
        "meta": {
            "source": "upload",
            "mode": "test",
            "parsed": bool(result.facts),
            "upload_files": upload_names,
            "warnings": result.warnings,
            "pipeline": "test_pq",
            "message": "Тест BI: группировка и join как в Power Query «Свод_нов».",
            "audit": {
                "run_id": audit.run_id,
                "report_path": str(pipeline.audit_path) if pipeline.audit_path else None,
                "latest_path": str(pipeline.audit_path.parent / "audit-latest.json") if pipeline.audit_path else None,
                "jsonl_path": str(pipeline.audit_path.parent / "audit-latest.jsonl") if pipeline.audit_path else None,
                "summary": audit_summary,
            },
        },
    }
    if plan_warnings:
        dashboard.setdefault("meta", {})["plan_forecast_warnings"] = plan_warnings
    if plan_facts is not None or forecast_facts is not None:
        dashboard.setdefault("meta", {})["plan_forecast_loaded"] = bool(plan_facts or forecast_facts)
    return dashboard


def load_test_dashboard_from_exports(
    paths: dict[str, Path],
    *,
    upload_names: dict[str, str],
    logs_dir: Path | None = None,
    plan_forecast_path: Path | None = None,
) -> dict[str, Any]:
    pipeline = run_test_pipeline(paths, logs_dir=logs_dir)
    plan_facts: list[Fact] = []
    forecast_facts: list[Fact] = []
    plan_warnings: list[str] = []
    if plan_forecast_path and plan_forecast_path.exists():
        from almabi_plan_forecast_parser import parse_plan_forecast_workbook

        parsed = parse_plan_forecast_workbook(plan_forecast_path)
        plan_facts = parsed.plan_facts
        forecast_facts = parsed.forecast_facts
        plan_warnings = parsed.warnings
    return build_test_dashboard_from_pipeline(
        pipeline,
        upload_names=upload_names,
        plan_facts=plan_facts,
        forecast_facts=forecast_facts,
        plan_warnings=plan_warnings,
    )


def load_almabi_dashboard_from_exports(
    paths: dict[str, Path],
    *,
    upload_names: dict[str, str],
    logs_dir: Path | None = None,
    plan_forecast_path: Path | None = None,
) -> dict[str, Any]:
    """Единственный путь сборки BI-дашборда (PQ/test pipeline)."""
    return load_test_dashboard_from_exports(
        paths,
        upload_names=upload_names,
        logs_dir=logs_dir,
        plan_forecast_path=plan_forecast_path,
    )


def build_empty_test_dashboard() -> dict[str, Any]:
    return {
        "months": MONTHS,
        "scenarios": SCENARIOS,
        "units": UNITS,
        "filters": {
            "taxType": ["Все виды", "Льготные проекты", "Нельготные проекты"],
            "direction": ["Все направления"],
            "projectGroup": ["Все группы"],
            "project": ["Все проекты"],
            "contract": ["Все договоры"],
            "contractor": ["Все контрагенты"],
            "quarter": ["Все кварталы", "Q1", "Q2", "Q3", "Q4"],
            "month": ["Все месяцы", *MONTHS],
        },
        "summary_rows": build_test_summary_rows(),
        "summary_by_tax": {
            "all": build_test_summary_rows(),
            "Льготные проекты": build_test_summary_rows(),
            "Нельготные проекты": build_test_summary_rows(),
        },
        "consolidated_by_tax": {
            bucket: _build_consolidated_table(build_test_summary_rows())
            for bucket in ("all", "Льготные проекты", "Нельготные проекты")
        },
        "consolidated_kpi_order": list(CONSOLIDATED_KPI_ORDER),
        "charts_by_tax": {
            "all": {
                "revenue_by_month": empty_chart_series(),
                "cost_by_month": empty_chart_series(),
                "cost_structure_by_month": _empty_cost_structure(),
            },
            "Льготные проекты": {
                "revenue_by_month": empty_chart_series(),
                "cost_by_month": empty_chart_series(),
                "cost_structure_by_month": _empty_cost_structure(),
            },
            "Нельготные проекты": {
                "revenue_by_month": empty_chart_series(),
                "cost_by_month": empty_chart_series(),
                "cost_structure_by_month": _empty_cost_structure(),
            },
        },
        "tax_bucket_options": ["all", "Льготные проекты", "Нельготные проекты"],
        "contractor_details": [],
        "contractor_cards": [],
        "revenue_by_month": empty_chart_series(),
        "cost_by_month": empty_chart_series(),
        "cost_structure_by_month": _empty_cost_structure(),
        "cost_structure_total": 0,
        "analytics_charts": {
            "revenue_by_direction": [],
            "gross_profit_by_direction": [],
            "expense_kpis": [],
            "expenses_by_month": [
                {"month": short, "fact": 0.0, "plan": 0.0}
                for short in ["Янв.", "Фев.", "Мар.", "Апр.", "Май", "Июн.", "Июл.", "Авг.", "Сен.", "Окт.", "Ноя.", "Дек."]
            ],
        },
        "meta": {
            "source": "test",
            "mode": "test",
            "parsed": False,
            "pipeline": "test_pq",
            "levels_spec": "fixtures/almabi_dashboard_levels.json",
            "message": "Загрузите бухрегистр, реализацию и себестоимость — структура уже готова, данные подтянутся по join.",
        },
    }
