from __future__ import annotations

from almabi_pipeline import Fact, PipelineResult
from almabi_pipeline_audit import PipelineAuditLog
from almabi_dashboard_builder import _chart_cost_structure
from almabi_taxes_report import compute_tax_with_loss_carryforward
from almabi_test_builder import build_test_dashboard_from_pipeline
from almabi_test_pipeline import TestPipelineResult as _TestPipelineResult


def _sum_by_calendar_year(values: dict[str, float]) -> dict[str, float]:
    totals: dict[str, float] = {}
    leftover = 0.0
    for period, amount in values.items():
        if len(period) == 7 and period[4] == "-" and period[:4].isdigit():
            year = period[:4]
            totals[year] = totals.get(year, 0.0) + float(amount or 0)
        else:
            leftover += float(amount or 0)
    if leftover:
        totals["Год"] = leftover
    return totals


def _revenue(period: str, amount: float, *, tax_type: str) -> Fact:
    year, month = period.split("-")
    month_name = "Январь" if month == "01" else f"{month}.{year}"
    return Fact(
        kpi_l1="Выручка",
        month=month_name,
        period=period,
        amount_buh=amount,
        amount_nu=amount,
        direction="Услуги",
        project_group="Группа",
        project="Проект",
        contract="Д-001",
        nomenclature="Лицензия",
        contractor="ООО Клиент",
        tax_type=tax_type,
    )


def test_dynamic_periods_separate_years_in_summary_chart_drill_and_contractors():
    facts = [
        _revenue("2025-01", 250.0, tax_type="Общие условия налогообложения"),
        _revenue(
            "2024-01",
            100.0,
            tax_type="Доходы по льготируемым видам деятельности",
        ),
    ]
    pipeline = _TestPipelineResult(
        result=PipelineResult(facts=facts),
        audit=PipelineAuditLog(),
    )

    dashboard = build_test_dashboard_from_pipeline(pipeline, upload_names={})

    assert dashboard["months"] == ["2024-01", "2025-01"]
    assert dashboard["period_labels"]["2024-01"] == "Январь 2024"
    assert dashboard["period_labels"]["2025-01"] == "Январь 2025"
    assert dashboard["available_periods"][0] == "2024-01"
    assert dashboard["available_periods"][-1] == "2025-12"
    assert dashboard["data_periods"] == ["2024-01", "2025-01"]

    revenue = next(row for row in dashboard["summary_rows"] if row["name"] == "Выручка")
    assert revenue["values"]["Факт БУ"] == {"2024-01": 100.0, "2025-01": 250.0}
    assert set(revenue["drill"]["months"]) == {"2024-01", "2025-01"}

    chart = dashboard["revenue_by_month"]
    assert [(item["period"], item["value"]) for item in chart] == [
        ("2024-01", 100.0),
        ("2025-01", 250.0),
    ]
    assert {item["period"] for item in dashboard["contractor_details"]} == {
        "2024-01",
        "2025-01",
    }

    privileged = next(
        row
        for row in dashboard["summary_by_tax"]["Льготные проекты"]
        if row["name"] == "Выручка"
    )
    non_privileged = next(
        row
        for row in dashboard["summary_by_tax"]["Нельготные проекты"]
        if row["name"] == "Выручка"
    )
    assert privileged["values"]["Факт БУ"] == {"2024-01": 100.0, "2025-01": 0.0}
    assert non_privileged["values"]["Факт БУ"] == {"2024-01": 0.0, "2025-01": 250.0}

    year_totals = _sum_by_calendar_year(revenue["values"]["Факт БУ"])
    assert year_totals == {"2024": 100.0, "2025": 250.0}
    assert year_totals["2024"] + year_totals["2025"] == sum(revenue["values"]["Факт БУ"].values())


def test_legacy_month_only_dashboard_keeps_russian_months():
    fact = Fact("Выручка", "Январь", 100.0, 100.0)
    pipeline = _TestPipelineResult(
        result=PipelineResult(facts=[fact]),
        audit=PipelineAuditLog(),
    )

    dashboard = build_test_dashboard_from_pipeline(pipeline, upload_names={})

    assert dashboard["months"][0] == "Январь"
    assert len(dashboard["months"]) == 12
    revenue = next(row for row in dashboard["summary_rows"] if row["name"] == "Выручка")
    assert revenue["values"]["Факт БУ"]["Январь"] == 100.0
    assert _sum_by_calendar_year(revenue["values"]["Факт БУ"]) == {"Год": 100.0}


def test_tax_loss_carryforward_resets_at_calendar_year_boundary():
    taxes, bases = compute_tax_with_loss_carryforward(
        {
            "2025-01": 100.0,
            "2024-12": -100.0,
        },
        rate=0.25,
    )

    assert bases["2024-12"] == 0.0
    assert bases["2025-01"] == 100.0
    assert taxes["2025-01"] == -25.0


def test_cost_structure_keeps_same_month_in_different_years_separate():
    facts = [
        Fact(
            "Себестоимость",
            "Январь",
            -100.0,
            -100.0,
            cost_section="ФОТ",
            period="2024-01",
        ),
        Fact(
            "Себестоимость",
            "Январь",
            -250.0,
            -250.0,
            cost_section="ФОТ",
            period="2025-01",
        ),
    ]

    structure = _chart_cost_structure(facts)

    assert [
        (item["period"], item["sections"]["ФОТ"])
        for item in structure["by_month"]
    ] == [("2024-01", 100.0), ("2025-01", 250.0)]
