from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from pathlib import Path
from typing import Any

from almabi_excel_utils import tax_bucket
from almabi_mock_data import MONTHS, SCENARIOS, UNITS, _MONTHS_SHORT
from almabi_contractor_builder import build_contractor_cards, build_contractor_details
from almabi_pipeline import Fact, PipelineResult, run_pipeline

_id_seq = 0

BENEFIT_SECTIONS = {
    "Коммерческие расходы",
    "Управленческие расходы",
    "Прочие доходы",
    "Прочие расходы",
    "Налоги",
}
ARTICLE_SECTIONS = {"Прочие доходы", "Прочие расходы"}
CALCULATED_KPIS = [
    ("Операционная прибыль", ["Выручка", "Себестоимость", "Коммерческие расходы", "Управленческие расходы"]),
    ("Прибыль/убыток до налогообложения", ["Операционная прибыль", "Прочие доходы", "Прочие расходы"]),
    ("Налоги", []),
    ("Чистая прибыль", ["Прибыль/убыток до налогообложения", "Налоги"]),
]
REVENUE_PATH = ["direction", "project_group", "project", "contract", "nomenclature"]
COST_PATH = ["cost_section", "direction", "project_group", "project", "nomenclature"]
ORG_PATH = ["direction", "project_group", "project"]


def _next_id(prefix: str) -> str:
    global _id_seq
    _id_seq += 1
    return f"{prefix}-{_id_seq}"


def _month_values(month_amounts: dict[str, dict[str, float]], *, revenue_aligned: bool = False) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {}
    for scenario in SCENARIOS:
        scenario_map: dict[str, int] = {}
        for month in MONTHS:
            buh = int(round(month_amounts.get(month, {}).get("buh", 0)))
            nu = int(round(month_amounts.get(month, {}).get("nu", 0)))
            if scenario == "Факт БУХ":
                scenario_map[month] = buh
            elif scenario == "Факт НУ":
                scenario_map[month] = nu if not revenue_aligned else buh
            elif scenario == "План":
                scenario_map[month] = round(buh * 1.08)
            else:
                scenario_map[month] = round(buh * 1.12)
        result[scenario] = scenario_map
    return result


def _attach_metrics(node: dict[str, Any]) -> dict[str, Any]:
    children = node.get("children") or []
    if children:
        for child in children:
            _attach_metrics(child)
        for scenario in SCENARIOS:
            totals = {month: 0 for month in MONTHS}
            for child in children:
                for month in MONTHS:
                    totals[month] += int(child["values"][scenario].get(month, 0))
            node["values"][scenario] = totals

    fact = node["values"]["Факт БУХ"]
    plan = node["values"]["План"]
    total_fact = sum(fact.values())
    total_plan = sum(plan.values())
    node["total_fact"] = total_fact
    node["total_plan"] = total_plan
    node["percent"] = (total_fact / total_plan * 100) if total_plan else 0.0
    node["expandable"] = bool(children)
    return node


def _group_facts(facts: list[Fact], *, kpi_l1: str) -> list[Fact]:
    return [fact for fact in facts if fact.kpi_l1 == kpi_l1]


def _aggregate_months(items: list[Fact]) -> dict[str, dict[str, float]]:
    totals: dict[str, dict[str, float]] = defaultdict(lambda: {"buh": 0.0, "nu": 0.0})
    for fact in items:
        bucket = totals[fact.month]
        bucket["buh"] += fact.amount_buh
        bucket["nu"] += fact.amount_nu
    return totals


def _dimension_value(fact: Fact, key: str) -> str:
    mapping = {
        "direction": fact.direction or "Без направления",
        "project_group": fact.project_group or "Без группы",
        "project": fact.project or "Без проекта",
        "contract": fact.contract or "Без договора",
        "nomenclature": fact.nomenclature or "Без номенклатуры",
        "cost_section": fact.cost_section or "Прочие затраты",
        "tax_bucket": tax_bucket(fact.tax_type),
        "expense_article": fact.expense_article or "Прочее",
    }
    return mapping[key]


def _build_group_tree(
    items: list[Fact],
    path: list[str],
    *,
    level: int,
    revenue_aligned: bool = False,
) -> list[dict[str, Any]]:
    if not path:
        return []

    current_key = path[0]
    grouped: dict[str, list[Fact]] = defaultdict(list)
    for fact in items:
        grouped[_dimension_value(fact, current_key)].append(fact)

    nodes: list[dict[str, Any]] = []
    for name in sorted(grouped):
        group_items = grouped[name]
        children = _build_group_tree(
            group_items,
            path[1:],
            level=level + 1,
            revenue_aligned=revenue_aligned,
        )
        nodes.append(
            _attach_metrics(
                {
                    "id": _next_id(f"node-{current_key}"),
                    "name": name,
                    "level": level,
                    "values": _month_values(_aggregate_months(group_items), revenue_aligned=revenue_aligned),
                    "children": children,
                }
            )
        )
    return nodes


def _build_benefit_children(items: list[Fact], *, with_articles: bool) -> list[dict[str, Any]]:
    grouped: dict[str, list[Fact]] = defaultdict(list)
    for fact in items:
        grouped[_dimension_value(fact, "tax_bucket")].append(fact)

    nodes: list[dict[str, Any]] = []
    for benefit_name in ("Льготные проекты", "Нельготные проекты"):
        benefit_items = grouped.get(benefit_name, [])
        children: list[dict[str, Any]] = []
        if with_articles and benefit_items:
            children = _build_group_tree(benefit_items, ["expense_article"], level=3)
        nodes.append(
            _attach_metrics(
                {
                    "id": _next_id("benefit"),
                    "name": benefit_name,
                    "level": 2,
                    "values": _month_values(_aggregate_months(benefit_items)),
                    "children": children,
                }
            )
        )
    return nodes


def _build_section_children(kpi_l1: str, items: list[Fact]) -> list[dict[str, Any]]:
    if kpi_l1 == "Выручка":
        return _build_group_tree(items, REVENUE_PATH, level=2, revenue_aligned=True)
    if kpi_l1 == "Себестоимость":
        return _build_group_tree(items, COST_PATH, level=2)
    if kpi_l1 in BENEFIT_SECTIONS:
        return _build_benefit_children(items, with_articles=kpi_l1 in ARTICLE_SECTIONS)
    return _build_group_tree(items, ORG_PATH, level=2)


def _build_kpi_node(name: str, items: list[Fact], *, sign: int = 1, revenue_aligned: bool = False) -> dict[str, Any]:
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
        )
        for fact in items
    ]
    return _attach_metrics(
        {
            "id": _next_id(f"kpi-{name}"),
            "name": name,
            "level": 1,
            "values": _month_values(_aggregate_months(scaled_items), revenue_aligned=revenue_aligned),
            "children": _build_section_children(name, scaled_items),
        }
    )


def _sum_nodes_by_name(nodes: list[dict[str, Any]], names: list[str], scenario: str) -> dict[str, int]:
    totals = {month: 0 for month in MONTHS}
    lookup = {node["name"]: node for node in nodes}
    for name in names:
        node = lookup.get(name)
        if not node:
            continue
        for month in MONTHS:
            totals[month] += int(node["values"][scenario].get(month, 0))
    return totals


def _build_tax_facts(component_nodes: list[dict[str, Any]], source_facts: list[Fact]) -> list[Fact]:
    taxable = [fact for fact in source_facts if fact.kpi_l1 in {"Выручка", "Прочие доходы", "Прочие расходы", "Себестоимость"}]
    if not taxable:
        pbt = _sum_nodes_by_name(component_nodes, ["Прибыль/убыток до налогообложения"], "Факт НУ")
        tax_facts: list[Fact] = []
        for month in MONTHS:
            base = pbt.get(month, 0)
            if not base:
                continue
            tax_facts.append(
                Fact(
                    kpi_l1="Налоги",
                    month=month,
                    amount_buh=-round(abs(base) * 0.25),
                    amount_nu=-round(abs(base) * 0.25),
                    tax_type="Общие условия налогообложения",
                )
            )
        return tax_facts

    grouped: dict[tuple[str, str], float] = defaultdict(float)
    for fact in taxable:
        grouped[(fact.month, fact.tax_type)] += fact.amount_nu

    tax_facts: list[Fact] = []
    for (month, tax_type), amount in grouped.items():
        if not amount:
            continue
        rate = 0.02 if "льгот" in tax_type.casefold() else 0.25
        tax_value = -round(abs(amount) * rate)
        tax_facts.append(
            Fact(
                kpi_l1="Налоги",
                month=month,
                amount_buh=tax_value,
                amount_nu=tax_value,
                tax_type=tax_type,
            )
        )
    return tax_facts


def _build_calculated_node(name: str, month_totals: dict[str, dict[str, float]], children: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return _attach_metrics(
        {
            "id": _next_id(f"calc-{name}"),
            "name": name,
            "level": 1,
            "values": _month_values(month_totals),
            "children": children or [],
        }
    )


def _month_totals_from_nodes(nodes: list[dict[str, Any]], names: list[str]) -> dict[str, dict[str, float]]:
    totals: dict[str, dict[str, float]] = defaultdict(lambda: {"buh": 0.0, "nu": 0.0})
    lookup = {node["name"]: node for node in nodes}
    for name in names:
        node = lookup.get(name)
        if not node:
            continue
        for month in MONTHS:
            totals[month]["buh"] += float(node["values"]["Факт БУХ"].get(month, 0))
            totals[month]["nu"] += float(node["values"]["Факт НУ"].get(month, 0))
    return totals


def _build_summary_rows(facts: list[Fact]) -> list[dict[str, Any]]:
    global _id_seq
    _id_seq = 0

    base_kpis = [
        ("Выручка", 1, True),
        ("Себестоимость", -1, False),
        ("Коммерческие расходы", -1, False),
        ("Управленческие расходы", -1, False),
    ]
    nodes: list[dict[str, Any]] = []
    for name, sign, revenue_aligned in base_kpis:
        nodes.append(_build_kpi_node(name, _group_facts(facts, kpi_l1=name), sign=sign, revenue_aligned=revenue_aligned))

    operating_totals = _month_totals_from_nodes(
        nodes,
        ["Выручка", "Себестоимость", "Коммерческие расходы", "Управленческие расходы"],
    )
    nodes.append(_build_calculated_node("Операционная прибыль", operating_totals))

    for name, sign, revenue_aligned in (("Прочие доходы", 1, False), ("Прочие расходы", -1, False)):
        nodes.append(_build_kpi_node(name, _group_facts(facts, kpi_l1=name), sign=sign, revenue_aligned=revenue_aligned))

    pbt_totals = _month_totals_from_nodes(
        nodes,
        ["Операционная прибыль", "Прочие доходы", "Прочие расходы"],
    )
    nodes.append(_build_calculated_node("Прибыль/убыток до налогообложения", pbt_totals))

    tax_facts = _build_tax_facts(nodes, facts)
    nodes.append(_build_kpi_node("Налоги", tax_facts, sign=1))

    net_totals = _month_totals_from_nodes(nodes, ["Прибыль/убыток до налогообложения", "Налоги"])
    nodes.append(_build_calculated_node("Чистая прибыль", net_totals))

    return nodes


def _collect_filter_values(facts: list[Fact]) -> dict[str, list[str]]:
    directions = sorted({fact.direction for fact in facts if fact.direction})
    groups = sorted({fact.project_group for fact in facts if fact.project_group})
    projects = sorted({fact.project for fact in facts if fact.project})
    contracts = sorted({fact.contract for fact in facts if fact.contract})
    contractors = sorted({fact.contractor for fact in facts if fact.contractor})
    return {
        "taxType": ["Все виды", "Льготные проекты", "Нельготные проекты"],
        "direction": ["Все направления", *directions],
        "projectGroup": ["Все группы", *groups],
        "project": ["Все проекты", *projects],
        "contract": ["Все договоры", *contracts],
        "contractor": ["Все контрагенты", *contractors],
        "quarter": ["Все кварталы", "Q1", "Q2", "Q3", "Q4"],
        "month": ["Все месяцы", *MONTHS],
    }


def _chart_series(facts: list[Fact], kpi_l1: str) -> list[dict[str, Any]]:
    totals = {month: 0.0 for month in MONTHS}
    for fact in facts:
        if fact.kpi_l1 != kpi_l1:
            continue
        totals[fact.month] += abs(fact.amount_buh)
    return [
        {"month": short, "value": round(totals[full])}
        for full, short in zip(MONTHS, _MONTHS_SHORT, strict=True)
    ]


def build_dashboard_from_pipeline(result: PipelineResult, *, upload_names: dict[str, str]) -> dict[str, Any]:
    summary_rows = _build_summary_rows(result.facts)
    contractor_details = build_contractor_details(result.facts)
    contractor_cards = build_contractor_cards(contractor_details)
    revenue_chart = _chart_series(result.facts, "Выручка")
    cost_chart = _chart_series(result.facts, "Себестоимость")
    return {
        "months": MONTHS,
        "scenarios": SCENARIOS,
        "units": UNITS,
        "filters": _collect_filter_values(result.facts),
        "summary_rows": summary_rows,
        "contractor_details": contractor_details,
        "contractor_cards": contractor_cards,
        "revenue_by_month": revenue_chart,
        "cost_by_month": cost_chart,
        "cost_structure_total": sum(item["value"] for item in cost_chart),
        "meta": {
            "source": "upload",
            "parsed": bool(result.facts),
            "upload_files": upload_names,
            "warnings": result.warnings,
            "message": "Дашборд построен из загруженных выгрузок 1С.",
        },
    }


def load_almabi_dashboard_from_exports(paths: dict[str, Path], *, upload_names: dict[str, str]) -> dict[str, Any]:
    result = run_pipeline(paths)
    if not result.facts:
        from almabi_template_data import get_almabi_template_dashboard_data

        data = get_almabi_template_dashboard_data()
        data["meta"] = {
            **data.get("meta", {}),
            "source": "upload",
            "parsed": False,
            "upload_files": upload_names,
            "warnings": result.warnings,
            "message": "Файлы загружены, но не удалось собрать суммы по месяцам. Показан шаблон.",
        }
        return data
    return build_dashboard_from_pipeline(result, upload_names=upload_names)
