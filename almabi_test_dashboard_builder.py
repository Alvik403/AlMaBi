"""Сборка дерева P&L для «Тест BI» — группировка как в Power Query «Свод_нов»."""
from __future__ import annotations

from typing import Any

import almabi_dashboard_builder as dashboard_builder
from almabi_dashboard_builder import (
    ARTICLE_SECTIONS,
    DRILLABLE_KPIS,
    _aggregate_months,
    _attach_drill,
    _attach_metrics,
    _build_benefit_children,
    _build_calculated_node,
    _build_group_tree,
    _build_tax_facts,
    _group_facts,
    _merge_signed_fact_groups,
    _month_totals_from_nodes,
    _month_values,
)
from almabi_pipeline import Fact

TEST_REVENUE_PATH = ["direction", "project_group", "project", "contract"]
TEST_COST_PATH = list(TEST_REVENUE_PATH)
TEST_BENEFIT_ONLY = {
    "Коммерческие расходы",
    "Управленческие расходы",
    "Прочие доходы",
    "Прочие расходы",
    "Налоги",
}


def _build_test_section_children(
    kpi_l1: str,
    items: list[Fact],
    *,
    plan_items: list[Fact] | None = None,
    forecast_items: list[Fact] | None = None,
    plan_forecast_from_file: bool = False,
) -> list[dict[str, Any]]:
    if kpi_l1 == "Выручка":
        return _build_group_tree(
            items,
            TEST_REVENUE_PATH,
            level=2,
            always_nu=True,
            plan_items=plan_items,
            forecast_items=forecast_items,
            plan_forecast_from_file=plan_forecast_from_file,
        )
    if kpi_l1 == "Себестоимость":
        return _build_group_tree(
            items,
            TEST_COST_PATH,
            level=2,
            plan_items=plan_items,
            forecast_items=forecast_items,
            plan_forecast_from_file=plan_forecast_from_file,
        )
    if kpi_l1 in TEST_BENEFIT_ONLY:
        return _build_benefit_children(
            items,
            with_articles=kpi_l1 in ARTICLE_SECTIONS,
            plan_items=plan_items,
            forecast_items=forecast_items,
            plan_forecast_from_file=plan_forecast_from_file,
        )
    return []


def _build_test_kpi_node(
    name: str,
    items: list[Fact],
    *,
    sign: int = 1,
    always_nu: bool = False,
    plan_items: list[Fact] | None = None,
    forecast_items: list[Fact] | None = None,
    plan_forecast_from_file: bool = False,
) -> dict[str, Any]:
    scaled_items = [
        Fact(
            kpi_l1=fact.kpi_l1,
            month=fact.month,
            amount_buh=fact.amount_buh * sign,
            amount_nu=fact.amount_nu * sign,
            direction=fact.direction,
            project_group=fact.project_group,
            project=fact.project,
            contract=fact.contract,
            nomenclature=fact.nomenclature,
            cost_section=fact.cost_section,
            expense_article=fact.expense_article,
            tax_type=fact.tax_type,
            contractor=fact.contractor,
            quantity=fact.quantity,
        )
        for fact in items
    ]
    scaled_plan = dashboard_builder._scale_facts(plan_items or [], sign)
    scaled_forecast = dashboard_builder._scale_facts(forecast_items or [], sign)
    node = _attach_metrics(
        {
            "id": dashboard_builder._next_id(f"kpi-{name}"),
            "name": name,
            "level": 1,
            "plan_forecast_from_file": plan_forecast_from_file,
            "values": _month_values(
                _aggregate_months(scaled_items),
                always_nu=always_nu,
                plan_amounts=dashboard_builder._scenario_amounts(scaled_plan, always_nu=always_nu),
                forecast_amounts=dashboard_builder._scenario_amounts(scaled_forecast, always_nu=always_nu),
                from_file=plan_forecast_from_file,
            ),
            "children": _build_test_section_children(
                name,
                scaled_items,
                plan_items=scaled_plan,
                forecast_items=scaled_forecast,
                plan_forecast_from_file=plan_forecast_from_file,
            ),
        }
    )
    _attach_drill(node, scaled_items, enabled=name in DRILLABLE_KPIS)
    return node


def build_test_summary_rows_from_facts(
    facts: list[Fact],
    *,
    plan_facts: list[Fact] | None = None,
    forecast_facts: list[Fact] | None = None,
) -> list[dict[str, Any]]:
    dashboard_builder._id_seq = 0

    plan_facts = plan_facts or []
    forecast_facts = forecast_facts or []
    plan_forecast_from_file = bool(plan_facts or forecast_facts)

    base_kpis = [
        ("Выручка", 1, True),
        ("Себестоимость", 1, False),
        ("Коммерческие расходы", 1, False),
        ("Управленческие расходы", 1, False),
    ]
    nodes: list[dict[str, Any]] = []
    for name, sign, always_nu in base_kpis:
        nodes.append(
            _build_test_kpi_node(
                name,
                _group_facts(facts, kpi_l1=name),
                sign=sign,
                always_nu=always_nu,
                plan_items=_group_facts(plan_facts, kpi_l1=name),
                forecast_items=_group_facts(forecast_facts, kpi_l1=name),
                plan_forecast_from_file=plan_forecast_from_file,
            )
        )

    revenue_facts = _group_facts(facts, kpi_l1="Выручка")
    cost_facts = _group_facts(facts, kpi_l1="Себестоимость")
    for node in nodes:
        if node["name"] == "Выручка":
            dashboard_builder._attach_revenue_cost_level_drills(
                node,
                revenue_facts,
                cost_facts,
                child_path=list(dashboard_builder.REVENUE_PATH),
            )
        elif node["name"] == "Себестоимость":
            dashboard_builder._attach_revenue_cost_level_drills(
                node,
                revenue_facts,
                cost_facts,
                child_path=list(dashboard_builder.COST_PATH),
            )

    operating_component_names = [
        "Выручка",
        "Себестоимость",
        "Коммерческие расходы",
        "Управленческие расходы",
    ]
    operating_lookup = {node["name"]: node for node in nodes}
    operating_totals = _month_totals_from_nodes(nodes, operating_component_names)
    operating_facts = _merge_signed_fact_groups(
        [
            (_group_facts(facts, kpi_l1="Выручка"), 1),
            (_group_facts(facts, kpi_l1="Себестоимость"), 1),
            (_group_facts(facts, kpi_l1="Коммерческие расходы"), 1),
            (_group_facts(facts, kpi_l1="Управленческие расходы"), 1),
        ]
    )
    nodes.append(
        _build_calculated_node(
            "Операционная прибыль",
            operating_totals,
            component_nodes=[operating_lookup[name] for name in operating_component_names],
            component_facts={name: _group_facts(facts, kpi_l1=name) for name in operating_component_names},
            drill_facts=operating_facts,
            plan_forecast_from_file=plan_forecast_from_file,
        )
    )

    for name, sign, always_nu in (("Прочие доходы", 1, False), ("Прочие расходы", 1, False)):
        nodes.append(
            _build_test_kpi_node(
                name,
                _group_facts(facts, kpi_l1=name),
                sign=sign,
                always_nu=always_nu,
                plan_items=_group_facts(plan_facts, kpi_l1=name),
                forecast_items=_group_facts(forecast_facts, kpi_l1=name),
                plan_forecast_from_file=plan_forecast_from_file,
            )
        )

    other_pnl_drill = dashboard_builder._build_other_pnl_drill(
        _group_facts(facts, kpi_l1="Прочие доходы"),
        _group_facts(facts, kpi_l1="Прочие расходы"),
    )
    for node in nodes:
        if node["name"] in dashboard_builder.OTHER_PNL_KPIS:
            node["drill"] = other_pnl_drill

    pbt_component_names = ["Операционная прибыль", "Прочие доходы", "Прочие расходы"]
    pbt_lookup = {node["name"]: node for node in nodes}
    pbt_totals = _month_totals_from_nodes(nodes, pbt_component_names)
    pbt_facts = _merge_signed_fact_groups(
        [
            (operating_facts, 1),
            (_group_facts(facts, kpi_l1="Прочие доходы"), 1),
            (_group_facts(facts, kpi_l1="Прочие расходы"), 1),
        ]
    )
    nodes.append(
        _build_calculated_node(
            "Прибыль/убыток до налогообложения",
            pbt_totals,
            component_nodes=[pbt_lookup[name] for name in pbt_component_names],
            drill_facts=pbt_facts,
            with_articles=True,
            plan_forecast_from_file=plan_forecast_from_file,
        )
    )

    tax_facts = _build_tax_facts(nodes, facts)
    nodes.append(
        _build_test_kpi_node(
            "Налоги",
            tax_facts,
            sign=1,
            plan_items=_group_facts(plan_facts, kpi_l1="Налоги"),
            forecast_items=_group_facts(forecast_facts, kpi_l1="Налоги"),
            plan_forecast_from_file=plan_forecast_from_file,
        )
    )

    net_component_names = ["Прибыль/убыток до налогообложения", "Налоги"]
    net_lookup = {node["name"]: node for node in nodes}
    net_totals = _month_totals_from_nodes(nodes, net_component_names)
    net_facts = _merge_signed_fact_groups([(pbt_facts, 1), (tax_facts, 1)])
    nodes.append(
        _build_calculated_node(
            "Чистая прибыль",
            net_totals,
            component_nodes=[net_lookup[name] for name in net_component_names],
            drill_facts=net_facts,
            plan_forecast_from_file=plan_forecast_from_file,
        )
    )

    return nodes
