from __future__ import annotations

from collections import defaultdict
from typing import Any

from almabi_dashboard_builder import _ordered_period_keys, period_labels, periods_from_facts
from almabi_excel_utils import period_label
from almabi_pipeline import Fact

EXPENSE_KPI_NAMES = (
    "Себестоимость",
    "Коммерческие расходы",
    "Управленческие расходы",
    "Прочие расходы",
)


def _sum_facts_by_field(
    facts: list[Fact],
    *,
    kpi_l1: str,
    field: str,
) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    for fact in facts:
        if fact.kpi_l1 != kpi_l1:
            continue
        key = (getattr(fact, field, None) or "").strip() or "Прочее"
        totals[key] += float(fact.amount_buh or 0)
    return dict(totals)


def _merge_plan_fact_groups(
    fact_totals: dict[str, float],
    plan_totals: dict[str, float],
) -> list[dict[str, Any]]:
    names = sorted(set(fact_totals) | set(plan_totals), key=lambda name: (-abs(fact_totals.get(name, 0)), name))
    rows: list[dict[str, Any]] = []
    for name in names:
        fact = float(fact_totals.get(name, 0) or 0)
        plan = float(plan_totals.get(name, 0) or 0)
        rows.append(
            {
                "name": name,
                "fact": fact,
                "plan": plan,
                "gross_profit": fact,
            }
        )
    return rows


def build_direction_charts(
    facts: list[Fact],
    *,
    plan_facts: list[Fact] | None = None,
) -> dict[str, Any]:
    revenue_fact = _sum_facts_by_field(facts, kpi_l1="Выручка", field="direction")
    revenue_plan = _sum_facts_by_field(plan_facts or [], kpi_l1="Выручка", field="direction")
    cost_fact = _sum_facts_by_field(facts, kpi_l1="Себестоимость", field="direction")
    cost_plan = _sum_facts_by_field(plan_facts or [], kpi_l1="Себестоимость", field="direction")

    revenue_rows = _merge_plan_fact_groups(revenue_fact, revenue_plan)
    gross_rows: list[dict[str, Any]] = []
    names = sorted(set(revenue_fact) | set(cost_fact), key=lambda name: (-abs(revenue_fact.get(name, 0)), name))
    for name in names:
        rev = float(revenue_fact.get(name, 0) or 0)
        cost = float(cost_fact.get(name, 0) or 0)
        rev_plan = float(revenue_plan.get(name, 0) or 0)
        cost_plan_value = float(cost_plan.get(name, 0) or 0)
        gross_rows.append(
            {
                "name": name,
                "fact": rev - cost,
                "plan": rev_plan - cost_plan_value,
                "revenue": rev,
            }
        )

    return {
        "revenue_by_direction": revenue_rows[:12],
        "gross_profit_by_direction": gross_rows[:12],
    }


def build_expense_kpi_chart(summary_lookup: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name in EXPENSE_KPI_NAMES:
        node = summary_lookup.get(name)
        if not node:
            continue
        values = node.get("values") or {}
        fact = values.get("Факт БУ") or {}
        plan = values.get("План") or {}
        rows.append(
            {
                "name": name,
                "fact": sum(abs(float(value or 0)) for value in fact.values()),
                "plan": sum(abs(float(value or 0)) for value in plan.values()),
            }
        )
    return rows


def build_monthly_expense_series(
    summary_lookup: dict[str, dict[str, Any]],
    *,
    periods: list[str] | None = None,
) -> list[dict[str, Any]]:
    active_periods = periods or _ordered_period_keys(
        {
            period
            for node in summary_lookup.values()
            for scenario_values in (node.get("values") or {}).values()
            for period in scenario_values
        }
    )
    totals = {period: {"fact": 0.0, "plan": 0.0} for period in active_periods}
    for name in EXPENSE_KPI_NAMES:
        node = summary_lookup.get(name)
        if not node:
            continue
        values = node.get("values") or {}
        fact = values.get("Факт БУ") or {}
        plan = values.get("План") or {}
        for period in active_periods:
            totals[period]["fact"] += abs(float(fact.get(period, 0) or 0))
            totals[period]["plan"] += abs(float(plan.get(period, 0) or 0))

    return [
        {
            "month": period_label(period, fallback=period),
            "period": period,
            "fact": totals[period]["fact"],
            "plan": totals[period]["plan"],
        }
        for period in active_periods
    ]


def build_analytics_charts(
    facts: list[Fact],
    summary_rows: list[dict[str, Any]],
    *,
    plan_facts: list[Fact] | None = None,
    periods: list[str] | None = None,
) -> dict[str, Any]:
    active_periods = periods or periods_from_facts(facts, plan_facts)
    lookup = {row["name"]: row for row in summary_rows}
    direction = build_direction_charts(facts, plan_facts=plan_facts)
    return {
        **direction,
        "expense_kpis": build_expense_kpi_chart(lookup),
        "expenses_by_month": build_monthly_expense_series(lookup, periods=active_periods),
        "period_labels": period_labels(active_periods),
    }
