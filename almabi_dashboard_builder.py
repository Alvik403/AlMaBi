from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from pathlib import Path
from typing import Any

from almabi_excel_utils import month_name, normalize_text, parse_date_from_text, tax_bucket
from almabi_export_parsers import classify_cost_section_pq
from almabi_mock_data import MONTHS, SCENARIOS, UNITS, _MONTHS_SHORT
from almabi_pq_common import (
    build_davaltz_document_totals,
    davaltz_cost_tree_group,
    is_black_metal_scrap_nomenclature,
    is_davaltz_cost_document,
    should_include_in_cost_structure,
    should_include_in_cost_tree,
)
from almabi_taxes_report import compute_tax_with_loss_carryforward
from almabi_contractor_builder import build_contractor_cards, build_contractor_details
from almabi_pipeline import Fact, PipelineResult

_id_seq = 0

BENEFIT_SECTIONS = {
    "Коммерческие расходы",
    "Управленческие расходы",
    "Прочие доходы",
    "Прочие расходы",
    "Налоги",
}
ARTICLE_SECTIONS = {"Прочие доходы", "Прочие расходы"}
DRILLABLE_KPIS = frozenset(
    {
        "Выручка",
        "Себестоимость",
        "Коммерческие расходы",
        "Управленческие расходы",
        "Прочие доходы",
        "Прочие расходы",
    }
)
OTHER_PNL_KPIS = frozenset({"Прочие доходы", "Прочие расходы"})
CALCULATED_KPIS = [
    ("Операционная прибыль", ["Выручка", "Себестоимость", "Коммерческие расходы", "Управленческие расходы"]),
    ("Прибыль/убыток до налогообложения", ["Операционная прибыль", "Прочие доходы", "Прочие расходы"]),
    ("Налоги", []),
    ("Чистая прибыль", ["Прибыль/убыток до налогообложения", "Налоги"]),
]
PBT_TAX_BASE_KPIS = frozenset(
    {
        "Выручка",
        "Себестоимость",
        "Коммерческие расходы",
        "Управленческие расходы",
        "Прочие доходы",
        "Прочие расходы",
    }
)
CALCULATED_BENEFIT_ALWAYS_NU_KPIS = frozenset({"Выручка"})
BENEFIT_BUCKET_NAMES = ("Льготные проекты", "Нельготные проекты")
# Уровни как в «Уровни для дашборда»: L1 — KPI, далее вложенность до L5.
REVENUE_PATH = ["direction", "project_group", "project", "contract"]
COST_PATH = ["cost_section", "direction", "project_group", "project"]
# В расшифровке выручки группы раскрываются до предпоследнего уровня пути.
REVENUE_COST_GROUP_PATH = REVENUE_PATH[:-1]
COST_GROUP_PATH = COST_PATH[:-1]

COST_STRUCTURE_SECTIONS = (
    "Амортизация",
    "Аренда (прямые)",
    "Материальные затраты",
    "Общепроизводственные затраты",
    "Прочие производственные расходы",
    "ФОТ",
)

_COST_STRUCTURE_ALIASES = {
    "Аренда": "Аренда (прямые)",
    "ОПЗ": "Общепроизводственные затраты",
}


def _normalize_cost_structure_section(section: str) -> str | None:
    text = (section or "").strip()
    if not text:
        return None
    if text.casefold() == "себестоимость":
        return None
    text = _COST_STRUCTURE_ALIASES.get(text, text)
    if text in COST_STRUCTURE_SECTIONS:
        return text
    return None
ORG_PATH = ["direction", "project_group", "project"]
BENEFIT_PATH = ["contract"]
BENEFIT_ARTICLE_PATH = ["expense_article", "contract"]
PRIVILEGED_BUCKET = "Льготные проекты"
NON_PRIVILEGED_BUCKET = "Нельготные проекты"


def _empty_drill_bucket() -> dict[str, float]:
    return {"buh": 0.0, "nu": 0.0}


def _drill_article_abs_total(article: dict[str, Any]) -> float:
    privileged = article.get(PRIVILEGED_BUCKET) or {}
    non_privileged = article.get(NON_PRIVILEGED_BUCKET) or {}
    total = (
        float(privileged.get("buh") or 0)
        + float(privileged.get("nu") or 0)
        + float(non_privileged.get("buh") or 0)
        + float(non_privileged.get("nu") or 0)
    )
    return abs(total)


def _build_drill_data(items: list[Fact]) -> dict[str, Any]:
    """Детализация ячейки: статьи с разбивкой льгота / нельгота."""

    def _payload(facts_subset: list[Fact]) -> dict[str, Any]:
        grouped: dict[str, dict[str, dict[str, float]]] = defaultdict(
            lambda: {
                PRIVILEGED_BUCKET: _empty_drill_bucket(),
                NON_PRIVILEGED_BUCKET: _empty_drill_bucket(),
            }
        )
        for fact in facts_subset:
            article = (fact.expense_article or "").strip() or (fact.contract or "").strip() or "Прочее"
            bucket = tax_bucket(fact.tax_type)
            grouped[article][bucket]["buh"] += fact.amount_buh
            grouped[article][bucket]["nu"] += fact.amount_nu
        articles = [
            {
                "name": name,
                PRIVILEGED_BUCKET: buckets[PRIVILEGED_BUCKET],
                NON_PRIVILEGED_BUCKET: buckets[NON_PRIVILEGED_BUCKET],
            }
            for name, buckets in grouped.items()
        ]
        articles.sort(key=lambda item: (-_drill_article_abs_total(item), item["name"]))
        return {"type": "articles", "articles": articles}

    return {
        "type": "articles",
        "total": _payload(items),
        "months": {month: _payload([fact for fact in items if fact.month == month]) for month in MONTHS},
    }


def _revenue_cost_line_metrics(
    *,
    name: str,
    revenue_buh: float,
    revenue_nu: float,
    cost_buh: float,
    cost_nu: float,
    quantity: float,
) -> dict[str, Any]:
    profit_buh = revenue_buh - cost_buh
    profit_nu = revenue_nu - cost_nu
    return {
        "name": name,
        "quantity": float(quantity or 0),
        "revenue": {"buh": revenue_buh, "nu": revenue_nu},
        "cost": {"buh": cost_buh, "nu": cost_nu},
        "profit": {"buh": profit_buh, "nu": profit_nu},
        "margin": {
            "buh": (profit_buh / revenue_buh * 100) if revenue_buh else 0.0,
            "nu": (profit_nu / revenue_nu * 100) if revenue_nu else 0.0,
        },
    }


def _aggregate_revenue_cost_metrics(nodes: list[dict[str, Any]], *, name: str) -> dict[str, Any]:
    revenue_buh = sum(float(node["revenue"]["buh"]) for node in nodes)
    revenue_nu = sum(float(node["revenue"]["nu"]) for node in nodes)
    cost_buh = sum(float(node["cost"]["buh"]) for node in nodes)
    cost_nu = sum(float(node["cost"]["nu"]) for node in nodes)
    quantity = sum(float(node.get("quantity") or 0) for node in nodes)
    return _revenue_cost_line_metrics(
        name=name,
        revenue_buh=revenue_buh,
        revenue_nu=revenue_nu,
        cost_buh=cost_buh,
        cost_nu=cost_nu,
        quantity=quantity,
    )


def _build_revenue_cost_leaf_lines(rev_subset: list[Fact], cost_subset: list[Fact]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, float]] = defaultdict(
        lambda: {
            "revenue_buh": 0.0,
            "revenue_nu": 0.0,
            "cost_buh": 0.0,
            "cost_nu": 0.0,
            "rev_quantity": 0.0,
            "cost_quantity": 0.0,
        }
    )
    for fact in rev_subset:
        name = (fact.nomenclature or "").strip() or (fact.contract or "").strip() or "Без наименования"
        grouped[name]["revenue_buh"] += float(fact.amount_buh or 0)
        grouped[name]["revenue_nu"] += float(fact.amount_nu or 0)
        grouped[name]["rev_quantity"] += float(fact.quantity or 0)
    for fact in cost_subset:
        name = (fact.nomenclature or "").strip() or (fact.contract or "").strip() or "Без наименования"
        grouped[name]["cost_buh"] += abs(float(fact.amount_buh or 0))
        grouped[name]["cost_nu"] += abs(float(fact.amount_nu or 0))
        # Количество продаж часто дублируется на нескольких статьях калькуляции — берём max.
        if fact.quantity:
            grouped[name]["cost_quantity"] = max(grouped[name]["cost_quantity"], float(fact.quantity))

    lines = [
        _revenue_cost_line_metrics(
            name=name,
            revenue_buh=float(values["revenue_buh"]),
            revenue_nu=float(values["revenue_nu"]),
            cost_buh=float(values["cost_buh"]),
            cost_nu=float(values["cost_nu"]),
            quantity=max(float(values["rev_quantity"]), float(values["cost_quantity"])),
        )
        for name, values in grouped.items()
    ]
    lines.sort(
        key=lambda item: (
            -max(abs(float(item["revenue"]["buh"])), abs(float(item["revenue"]["nu"]))),
            item["name"],
        )
    )
    return lines


def _build_revenue_cost_tree(
    rev_subset: list[Fact],
    cost_subset: list[Fact],
    path: list[str],
    *,
    level: int = 1,
) -> list[dict[str, Any]]:
    if not path:
        return [
            {
                **line,
                "level": level,
                "expandable": False,
                "children": [],
            }
            for line in _build_revenue_cost_leaf_lines(rev_subset, cost_subset)
        ]

    current_key = path[0]
    rev_grouped = _group_facts_by_dimension(rev_subset, current_key)
    cost_grouped = _group_facts_by_dimension(cost_subset, current_key)
    names = sorted(set(rev_grouped) | set(cost_grouped))
    nodes: list[dict[str, Any]] = []
    for name in names:
        children = _build_revenue_cost_tree(
            rev_grouped.get(name, []),
            cost_grouped.get(name, []),
            path[1:],
            level=level + 1,
        )
        if not children:
            continue
        metrics = _aggregate_revenue_cost_metrics(children, name=name)
        nodes.append(
            {
                **metrics,
                "level": level,
                "expandable": True,
                "children": children,
            }
        )
    nodes.sort(
        key=lambda item: (
            -max(abs(float(item["revenue"]["buh"])), abs(float(item["revenue"]["nu"]))),
            item["name"],
        )
    )
    return nodes


def _build_revenue_cost_drill(
    revenue_facts: list[Fact],
    cost_facts: list[Fact],
    *,
    group_path: list[str] | None = None,
) -> dict[str, Any]:
    """Расшифровка выручки/себестоимости с раскрытием по уровням до предпоследнего."""
    path = list(REVENUE_COST_GROUP_PATH if group_path is None else group_path)

    def _payload(rev_subset: list[Fact], cost_subset: list[Fact]) -> dict[str, Any]:
        tree = _build_revenue_cost_tree(rev_subset, cost_subset, list(path))
        return {
            "type": "revenue_cost",
            "path": list(path),
            "tree": tree,
            "lines": _build_revenue_cost_leaf_lines(rev_subset, cost_subset),
        }

    return {
        "type": "revenue_cost",
        "total": _payload(revenue_facts, cost_facts),
        "months": {
            month: _payload(
                [fact for fact in revenue_facts if fact.month == month],
                [fact for fact in cost_facts if fact.month == month],
            )
            for month in MONTHS
        },
    }


def _revenue_matching_cost_scope(revenue_facts: list[Fact], cost_facts: list[Fact]) -> list[Fact]:
    if not cost_facts:
        return []
    keys = {
        (
            _dimension_value(fact, "direction"),
            _dimension_value(fact, "project_group"),
            _dimension_value(fact, "project"),
            (fact.nomenclature or "").strip().casefold(),
        )
        for fact in cost_facts
    }
    return [
        fact
        for fact in revenue_facts
        if (
            _dimension_value(fact, "direction"),
            _dimension_value(fact, "project_group"),
            _dimension_value(fact, "project"),
            (fact.nomenclature or "").strip().casefold(),
        )
        in keys
    ]


def _scope_revenue_cost_facts(
    revenue_facts: list[Fact],
    cost_facts: list[Fact],
    filters: list[tuple[str, str]],
) -> tuple[list[Fact], list[Fact]]:
    rev = list(revenue_facts)
    cost = list(cost_facts)
    for key, name in filters:
        if key == "cost_section":
            cost = [fact for fact in cost if _dimension_value(fact, key) == name]
            rev = _revenue_matching_cost_scope(rev, cost)
        else:
            rev = [fact for fact in rev if _dimension_value(fact, key) == name]
            cost = [fact for fact in cost if _dimension_value(fact, key) == name]
    return rev, cost


def _remaining_revenue_cost_group_path(
    filters: list[tuple[str, str]],
    *,
    group_path_keys: list[str] | None = None,
) -> list[str]:
    fixed = {key for key, _ in filters}
    keys = group_path_keys if group_path_keys is not None else REVENUE_COST_GROUP_PATH
    return [key for key in keys if key not in fixed]


def _attach_revenue_cost_level_drills(
    node: dict[str, Any],
    revenue_facts: list[Fact],
    cost_facts: list[Fact],
    *,
    child_path: list[str],
    group_path_keys: list[str] | None = None,
    filters: list[tuple[str, str]] | None = None,
) -> None:
    """Вешает расшифровку на узел и всех потомков в рамках текущего среза."""
    active_filters = list(filters or [])
    scoped_rev, scoped_cost = _scope_revenue_cost_facts(revenue_facts, cost_facts, active_filters)
    node["drill"] = _build_revenue_cost_drill(
        scoped_rev,
        scoped_cost,
        group_path=_remaining_revenue_cost_group_path(
            active_filters,
            group_path_keys=group_path_keys,
        ),
    )
    if not child_path:
        return
    key = child_path[0]
    for child in node.get("children") or []:
        _attach_revenue_cost_level_drills(
            child,
            revenue_facts,
            cost_facts,
            child_path=child_path[1:],
            group_path_keys=group_path_keys,
            filters=[*active_filters, (key, child["name"])],
        )


def _other_section_articles(facts_subset: list[Fact]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, dict[str, float]]] = defaultdict(
        lambda: {
            PRIVILEGED_BUCKET: _empty_drill_bucket(),
            NON_PRIVILEGED_BUCKET: _empty_drill_bucket(),
        }
    )
    for fact in facts_subset:
        article = (fact.expense_article or "").strip() or (fact.contract or "").strip() or "Прочее"
        bucket = tax_bucket(fact.tax_type)
        grouped[article][bucket]["buh"] += fact.amount_buh
        grouped[article][bucket]["nu"] += fact.amount_nu
    articles = [
        {
            "name": name,
            PRIVILEGED_BUCKET: buckets[PRIVILEGED_BUCKET],
            NON_PRIVILEGED_BUCKET: buckets[NON_PRIVILEGED_BUCKET],
        }
        for name, buckets in grouped.items()
    ]
    articles.sort(key=lambda item: (-_drill_article_abs_total(item), item["name"]))
    return articles


def _build_other_pnl_drill(income_facts: list[Fact], expense_facts: list[Fact]) -> dict[str, Any]:
    """Единая расшифровка прочих доходов и прочих расходов: статья × льгота / нельгота."""

    def _payload(income_subset: list[Fact], expense_subset: list[Fact]) -> dict[str, Any]:
        return {
            "type": "other_pnl",
            "sections": [
                {"name": "Прочие доходы", "articles": _other_section_articles(income_subset)},
                {"name": "Прочие расходы", "articles": _other_section_articles(expense_subset)},
            ],
        }

    return {
        "type": "other_pnl",
        "total": _payload(income_facts, expense_facts),
        "months": {
            month: _payload(
                [fact for fact in income_facts if fact.month == month],
                [fact for fact in expense_facts if fact.month == month],
            )
            for month in MONTHS
        },
    }


def _attach_drill(node: dict[str, Any], items: list[Fact], *, enabled: bool = True) -> None:
    if enabled:
        node["drill"] = _build_drill_data(items)
    else:
        node.pop("drill", None)

def _next_id(prefix: str) -> str:
    global _id_seq
    _id_seq += 1
    return f"{prefix}-{_id_seq}"


def _aggregate_months_for_display(
    items: list[Fact],
    *,
    always_nu_kpis: frozenset[str] = frozenset(),
) -> dict[str, dict[str, float]]:
    totals: dict[str, dict[str, float]] = defaultdict(lambda: {"buh": 0.0, "nu": 0.0})
    for fact in items:
        bucket = totals[fact.month]
        bucket["buh"] += fact.amount_nu if fact.kpi_l1 in always_nu_kpis else fact.amount_buh
        bucket["nu"] += fact.amount_nu
    return totals


def _scenario_amounts(
    items: list[Fact] | None,
    *,
    always_nu: bool = False,
    always_nu_kpis: frozenset[str] = frozenset(),
) -> dict[str, float] | None:
    if not items:
        return None
    aggregated = (
        _aggregate_months_for_display(items, always_nu_kpis=always_nu_kpis)
        if always_nu_kpis
        else _aggregate_months(items)
    )
    return {
        month: float(aggregated[month]["nu"] if always_nu else aggregated[month]["buh"])
        for month in MONTHS
    }


def _month_values(
    month_amounts: dict[str, dict[str, float]],
    *,
    always_nu: bool = False,
    plan_amounts: dict[str, float] | None = None,
    forecast_amounts: dict[str, float] | None = None,
    from_file: bool = False,
) -> dict[str, dict[str, float]]:
    result: dict[str, dict[str, float]] = {}
    for scenario in SCENARIOS:
        scenario_map: dict[str, float] = {}
        for month in MONTHS:
            buh = float(month_amounts.get(month, {}).get("buh", 0) or 0)
            nu = float(month_amounts.get(month, {}).get("nu", 0) or 0)
            fact_buh = nu if always_nu else buh
            fact_nu = nu
            if scenario == "Факт БУ":
                scenario_map[month] = fact_buh
            elif scenario == "Факт НУ":
                scenario_map[month] = fact_nu
            elif scenario == "План":
                if from_file or plan_amounts is not None:
                    scenario_map[month] = float((plan_amounts or {}).get(month, 0) or 0)
                else:
                    scenario_map[month] = fact_buh * 1.08
            else:
                if from_file or forecast_amounts is not None:
                    scenario_map[month] = float((forecast_amounts or {}).get(month, 0) or 0)
                else:
                    scenario_map[month] = fact_buh * 1.12
        result[scenario] = scenario_map
    return result


def _attach_metrics(node: dict[str, Any], *, preserve_parent_totals: bool = False) -> dict[str, Any]:
    preserve = preserve_parent_totals or bool(node.get("preserve_parent_totals"))
    if preserve:
        node["preserve_parent_totals"] = True
    children = node.get("children") or []
    if children:
        for child in children:
            _attach_metrics(child)
        if not preserve:
            for scenario in SCENARIOS:
                totals = {month: 0.0 for month in MONTHS}
                for child in children:
                    for month in MONTHS:
                        totals[month] += float(child["values"][scenario].get(month, 0) or 0)
                if scenario in {"План", "Прогноз"} and node.get("plan_forecast_from_file"):
                    continue
                if scenario in {"План", "Прогноз"} and not any(totals.values()):
                    continue
                node["values"][scenario] = totals

    fact = node["values"]["Факт БУ"]
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
        "cost_section": fact.cost_section or "Общепроизводственные затраты",
        "tax_bucket": tax_bucket(fact.tax_type),
        "expense_article": fact.expense_article or "Прочее",
    }
    value = mapping[key]
    if key == "cost_section" and value.casefold() == "себестоимость":
        return "Общепроизводственные затраты"
    return value


def _node_is_effectively_empty(node: dict[str, Any]) -> bool:
    if abs(float(node.get("total_fact") or 0)) > 0.005:
        return False
    if abs(float(node.get("total_plan") or 0)) > 0.005:
        return False
    if abs(float(node.get("total_forecast") or 0)) > 0.005:
        return False
    for scenario in SCENARIOS:
        month_values = (node.get("values") or {}).get(scenario) or {}
        if any(abs(float(value or 0)) > 0.005 for value in month_values.values()):
            return False
    children = node.get("children") or []
    return not children or all(_node_is_effectively_empty(child) for child in children)


def _filter_group_facts(items: list[Fact] | None, key: str, name: str) -> list[Fact]:
    if not items:
        return []
    return [fact for fact in items if _dimension_value(fact, key) == name]


def _group_facts_by_dimension(items: list[Fact] | None, key: str) -> dict[str, list[Fact]]:
    grouped: dict[str, list[Fact]] = defaultdict(list)
    for fact in items or []:
        grouped[_dimension_value(fact, key)].append(fact)
    return grouped


def _build_group_tree(
    items: list[Fact],
    path: list[str],
    *,
    level: int,
    always_nu: bool = False,
    plan_items: list[Fact] | None = None,
    forecast_items: list[Fact] | None = None,
    plan_forecast_from_file: bool = False,
) -> list[dict[str, Any]]:
    if not path:
        return []

    current_key = path[0]
    fact_grouped = _group_facts_by_dimension(items, current_key)
    if plan_forecast_from_file:
        plan_grouped = _group_facts_by_dimension(plan_items, current_key)
        forecast_grouped = _group_facts_by_dimension(forecast_items, current_key)
        names = sorted(set(fact_grouped) | set(plan_grouped) | set(forecast_grouped))
    else:
        plan_grouped = {}
        forecast_grouped = {}
        names = sorted(fact_grouped)

    nodes: list[dict[str, Any]] = []
    for name in names:
        group_items = fact_grouped.get(name, [])
        plan_group = plan_grouped.get(name, [])
        forecast_group = forecast_grouped.get(name, [])
        children = _build_group_tree(
            group_items,
            path[1:],
            level=level + 1,
            always_nu=always_nu,
            plan_items=plan_group,
            forecast_items=forecast_group,
            plan_forecast_from_file=plan_forecast_from_file,
        )
        node = _attach_metrics(
            {
                "id": _next_id(f"node-{current_key}"),
                "name": name,
                "level": level,
                "plan_forecast_from_file": plan_forecast_from_file,
                "values": _month_values(
                    _aggregate_months(group_items),
                    always_nu=always_nu,
                    plan_amounts=_scenario_amounts(plan_group, always_nu=always_nu),
                    forecast_amounts=_scenario_amounts(forecast_group, always_nu=always_nu),
                    from_file=plan_forecast_from_file,
                ),
                "children": children,
            }
        )
        if _node_is_effectively_empty(node):
            continue
        nodes.append(node)
    nodes.sort(key=lambda item: (-abs(float(item.get("total_fact") or 0)), item["name"]))
    return nodes


def _scale_facts(items: list[Fact], sign: int) -> list[Fact]:
    if sign == 1:
        return items
    return [
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


def _merge_signed_fact_groups(groups: list[tuple[list[Fact], int]]) -> list[Fact]:
    merged: list[Fact] = []
    for items, sign in groups:
        merged.extend(_scale_facts(items, sign))
    return merged


def _build_benefit_children(
    items: list[Fact],
    *,
    with_articles: bool,
    plan_items: list[Fact] | None = None,
    forecast_items: list[Fact] | None = None,
    plan_forecast_from_file: bool = False,
    always_nu_kpis: frozenset[str] = frozenset(),
) -> list[dict[str, Any]]:
    grouped: dict[str, list[Fact]] = defaultdict(list)
    for fact in items:
        grouped[_dimension_value(fact, "tax_bucket")].append(fact)

    plan_grouped: dict[str, list[Fact]] = defaultdict(list)
    for fact in plan_items or []:
        plan_grouped[_dimension_value(fact, "tax_bucket")].append(fact)
    forecast_grouped: dict[str, list[Fact]] = defaultdict(list)
    for fact in forecast_items or []:
        forecast_grouped[_dimension_value(fact, "tax_bucket")].append(fact)

    nodes: list[dict[str, Any]] = []
    for benefit_name in ("Льготные проекты", "Нельготные проекты"):
        benefit_items = grouped.get(benefit_name, [])
        plan_for_benefit = plan_grouped.get(benefit_name, [])
        forecast_for_benefit = forecast_grouped.get(benefit_name, [])
        children: list[dict[str, Any]] = []
        if benefit_items or (
            plan_forecast_from_file and (plan_for_benefit or forecast_for_benefit)
        ):
            path = BENEFIT_ARTICLE_PATH if with_articles else BENEFIT_PATH
            children = _build_group_tree(
                benefit_items,
                path,
                level=3,
                plan_items=plan_for_benefit,
                forecast_items=forecast_for_benefit,
                plan_forecast_from_file=plan_forecast_from_file,
            )
        aggregate_months = (
            _aggregate_months_for_display(benefit_items, always_nu_kpis=always_nu_kpis)
            if always_nu_kpis
            else _aggregate_months(benefit_items)
        )
        node = _attach_metrics(
            {
                "id": _next_id("benefit"),
                "name": benefit_name,
                "level": 2,
                "plan_forecast_from_file": plan_forecast_from_file,
                "preserve_parent_totals": bool(always_nu_kpis),
                "values": _month_values(
                    aggregate_months,
                    plan_amounts=_scenario_amounts(
                        plan_grouped.get(benefit_name, []),
                        always_nu_kpis=always_nu_kpis,
                    ),
                    forecast_amounts=_scenario_amounts(
                        forecast_grouped.get(benefit_name, []),
                        always_nu_kpis=always_nu_kpis,
                    ),
                    from_file=plan_forecast_from_file,
                ),
                "children": children,
            },
            preserve_parent_totals=bool(always_nu_kpis),
        )
        nodes.append(node)
    return nodes


def _build_section_children(
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
            REVENUE_PATH,
            level=2,
            always_nu=True,
            plan_items=plan_items,
            forecast_items=forecast_items,
            plan_forecast_from_file=plan_forecast_from_file,
        )
    if kpi_l1 == "Себестоимость":
        return _build_group_tree(
            items,
            COST_PATH,
            level=2,
            plan_items=plan_items,
            forecast_items=forecast_items,
            plan_forecast_from_file=plan_forecast_from_file,
        )
    if kpi_l1 in BENEFIT_SECTIONS:
        return _build_benefit_children(
            items,
            with_articles=kpi_l1 in ARTICLE_SECTIONS,
            plan_items=plan_items,
            forecast_items=forecast_items,
            plan_forecast_from_file=plan_forecast_from_file,
        )
    return _build_group_tree(
        items,
        ORG_PATH,
        level=2,
        plan_items=plan_items,
        forecast_items=forecast_items,
        plan_forecast_from_file=plan_forecast_from_file,
    )


def _build_kpi_node(
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
    scaled_plan = _scale_facts(plan_items or [], sign)
    scaled_forecast = _scale_facts(forecast_items or [], sign)
    node = _attach_metrics(
        {
            "id": _next_id(f"kpi-{name}"),
            "name": name,
            "level": 1,
            "plan_forecast_from_file": plan_forecast_from_file,
            "values": _month_values(
                _aggregate_months(scaled_items),
                always_nu=always_nu,
                plan_amounts=_scenario_amounts(scaled_plan, always_nu=always_nu),
                forecast_amounts=_scenario_amounts(scaled_forecast, always_nu=always_nu),
                from_file=plan_forecast_from_file,
            ),
            "children": _build_section_children(
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


def _sum_nodes_by_name(nodes: list[dict[str, Any]], names: list[str], scenario: str) -> dict[str, float]:
    totals = {month: 0.0 for month in MONTHS}
    lookup = {node["name"]: node for node in nodes}
    for name in names:
        node = lookup.get(name)
        if not node:
            continue
        for month in MONTHS:
            totals[month] += float(node["values"][scenario].get(month, 0) or 0)
    return totals


def _tax_rate_for_type(tax_type: str) -> float:
    return 0.02 if "льгот" in tax_type.casefold() else 0.25


def _bucket_tax_type(bucket_name: str) -> str:
    if bucket_name == PRIVILEGED_BUCKET:
        return "Доходы по льготируемым видам деятельности"
    return "Общие условия налогообложения"


def _pbt_by_bucket_from_nodes(component_nodes: list[dict[str, Any]]) -> dict[str, dict[str, dict[str, float]]]:
    pbt_node = next(
        (node for node in component_nodes if node.get("name") == "Прибыль/убыток до налогообложения"),
        None,
    )
    if pbt_node is None:
        return {}
    by_bucket: dict[str, dict[str, dict[str, float]]] = {}
    for bucket_name in BENEFIT_BUCKET_NAMES:
        child = _find_named_child(pbt_node, bucket_name)
        if child is None:
            by_bucket[bucket_name] = {
                scenario: {month: 0.0 for month in MONTHS} for scenario in ("Факт БУ", "Факт НУ")
            }
            continue
        values = child.get("values", {})
        by_bucket[bucket_name] = {
            scenario: {
                month: float(values.get(scenario, {}).get(month, 0) or 0) for month in MONTHS
            }
            for scenario in ("Факт БУ", "Факт НУ")
        }
    return by_bucket


def _build_tax_facts(component_nodes: list[dict[str, Any]], source_facts: list[Fact]) -> list[Fact]:
    """Налог от PBT по льготным/нельготным корзинам с переносом убытков (БУ и НУ отдельно)."""
    pbt_by_bucket = _pbt_by_bucket_from_nodes(component_nodes)
    tax_facts: list[Fact] = []

    if not pbt_by_bucket:
        pbt_bu = _sum_nodes_by_name(component_nodes, ["Прибыль/убыток до налогообложения"], "Факт БУ")
        pbt_nu = _sum_nodes_by_name(component_nodes, ["Прибыль/убыток до налогообложения"], "Факт НУ")
        taxes_bu, _ = compute_tax_with_loss_carryforward(pbt_bu, rate=0.25, months=tuple(MONTHS))
        taxes_nu, _ = compute_tax_with_loss_carryforward(pbt_nu, rate=0.25, months=tuple(MONTHS))
        for month in MONTHS:
            amount_buh = taxes_bu.get(month, 0.0)
            amount_nu = taxes_nu.get(month, 0.0)
            if amount_buh == 0 and amount_nu == 0:
                continue
            tax_facts.append(
                Fact(
                    kpi_l1="Налоги",
                    month=month,
                    amount_buh=amount_buh,
                    amount_nu=amount_nu,
                    tax_type="Общие условия налогообложения",
                )
            )
        return tax_facts

    for bucket_name in BENEFIT_BUCKET_NAMES:
        bucket_pbt = pbt_by_bucket.get(bucket_name, {})
        monthly_bu = bucket_pbt.get("Факт БУ", {})
        monthly_nu = bucket_pbt.get("Факт НУ", {})
        tax_type = _bucket_tax_type(bucket_name)
        rate = _tax_rate_for_type(tax_type)
        taxes_bu, _ = compute_tax_with_loss_carryforward(
            monthly_bu,
            rate=rate,
            months=tuple(MONTHS),
        )
        taxes_nu, _ = compute_tax_with_loss_carryforward(
            monthly_nu,
            rate=rate,
            months=tuple(MONTHS),
        )
        for month in MONTHS:
            amount_buh = taxes_bu.get(month, 0.0)
            amount_nu = taxes_nu.get(month, 0.0)
            if amount_buh == 0 and amount_nu == 0:
                continue
            tax_facts.append(
                Fact(
                    kpi_l1="Налоги",
                    month=month,
                    amount_buh=amount_buh,
                    amount_nu=amount_nu,
                    tax_type=tax_type,
                )
            )
    return tax_facts


def _find_named_child(node: dict[str, Any], name: str) -> dict[str, Any] | None:
    return next((child for child in node.get("children") or [] if child.get("name") == name), None)


def _empty_scenario_values() -> dict[str, dict[str, float]]:
    return {scenario: {month: 0.0 for month in MONTHS} for scenario in SCENARIOS}


def _sum_scenario_values(items: list[dict[str, dict[str, float]]]) -> dict[str, dict[str, float]]:
    totals = _empty_scenario_values()
    for values in items:
        for scenario in SCENARIOS:
            for month in MONTHS:
                totals[scenario][month] += float(values.get(scenario, {}).get(month, 0) or 0)
    return totals


def _facts_benefit_bucket_values(
    facts: list[Fact],
    bucket_name: str,
    *,
    always_nu_kpis: frozenset[str] = frozenset(),
) -> dict[str, dict[str, float]]:
    filtered = [fact for fact in facts if _dimension_value(fact, "tax_bucket") == bucket_name]
    aggregated = _aggregate_months_for_display(filtered, always_nu_kpis=always_nu_kpis)
    return _month_values(aggregated)


def _component_benefit_bucket_values(
    component_node: dict[str, Any],
    component_facts: list[Fact] | None,
) -> dict[str, dict[str, dict[str, float]]]:
    by_bucket: dict[str, dict[str, dict[str, float]]] = {}
    always_nu_kpis = (
        CALCULATED_BENEFIT_ALWAYS_NU_KPIS
        if component_node["name"] == "Выручка"
        else frozenset()
    )
    for bucket_name in BENEFIT_BUCKET_NAMES:
        bucket_child = _find_named_child(component_node, bucket_name)
        if bucket_child is not None:
            by_bucket[bucket_name] = bucket_child["values"]
        elif component_facts:
            by_bucket[bucket_name] = _facts_benefit_bucket_values(
                component_facts,
                bucket_name,
                always_nu_kpis=always_nu_kpis,
            )
        else:
            by_bucket[bucket_name] = _empty_scenario_values()
    return by_bucket


def _build_formula_benefit_children(
    component_nodes: list[dict[str, Any]],
    *,
    component_facts: dict[str, list[Fact]] | None = None,
    drill_facts: list[Fact] | None = None,
    plan_forecast_from_file: bool = False,
    with_articles: bool = False,
) -> list[dict[str, Any]]:
    component_facts = component_facts or {}
    drill_grouped: dict[str, list[Fact]] = defaultdict(list)
    for fact in drill_facts or []:
        drill_grouped[_dimension_value(fact, "tax_bucket")].append(fact)

    nodes: list[dict[str, Any]] = []
    for bucket_name in BENEFIT_BUCKET_NAMES:
        bucket_parts = [
            _component_benefit_bucket_values(
                component,
                component_facts.get(component["name"]),
            )[bucket_name]
            for component in component_nodes
        ]
        children: list[dict[str, Any]] = []
        bucket_drill_facts = drill_grouped.get(bucket_name, [])
        if bucket_drill_facts:
            path = BENEFIT_ARTICLE_PATH if with_articles else BENEFIT_PATH
            children = _build_group_tree(
                bucket_drill_facts,
                path,
                level=3,
                plan_forecast_from_file=plan_forecast_from_file,
            )
        values = _sum_scenario_values(bucket_parts)
        node = _attach_metrics(
            {
                "id": _next_id("benefit"),
                "name": bucket_name,
                "level": 2,
                "plan_forecast_from_file": plan_forecast_from_file,
                "preserve_parent_totals": True,
                "signed_amounts": True,
                "values": values,
                "children": children,
            },
            preserve_parent_totals=True,
        )
        nodes.append(node)
    return nodes


def _build_calculated_node(
    name: str,
    month_totals: dict[str, dict[str, float]],
    *,
    component_nodes: list[dict[str, Any]] | None = None,
    component_facts: dict[str, list[Fact]] | None = None,
    drill_facts: list[Fact] | None = None,
    children: list[dict[str, Any]] | None = None,
    plan_forecast_from_file: bool = False,
    with_articles: bool = False,
) -> dict[str, Any]:
    benefit_children = children
    if benefit_children is None and component_nodes is not None:
        benefit_children = _build_formula_benefit_children(
            component_nodes,
            component_facts=component_facts,
            drill_facts=drill_facts,
            plan_forecast_from_file=plan_forecast_from_file,
            with_articles=with_articles,
        )
    for child in benefit_children or []:
        child["signed_amounts"] = True
    plan_amounts = {month: float(month_totals[month].get("plan", 0) or 0) for month in MONTHS}
    forecast_amounts = {month: float(month_totals[month].get("forecast", 0) or 0) for month in MONTHS}
    node = _attach_metrics(
        {
            "id": _next_id(f"calc-{name}"),
            "name": name,
            "level": 1,
            "plan_forecast_from_file": plan_forecast_from_file,
            "preserve_parent_totals": True,
            "values": _month_values(
                month_totals,
                plan_amounts=plan_amounts if plan_forecast_from_file or any(plan_amounts.values()) else None,
                forecast_amounts=forecast_amounts if plan_forecast_from_file or any(forecast_amounts.values()) else None,
                from_file=plan_forecast_from_file,
            ),
            "children": benefit_children or [],
        },
        preserve_parent_totals=True,
    )
    return node


def _month_totals_from_nodes(nodes: list[dict[str, Any]], names: list[str]) -> dict[str, dict[str, float]]:
    totals: dict[str, dict[str, float]] = defaultdict(lambda: {"buh": 0.0, "nu": 0.0, "plan": 0.0, "forecast": 0.0})
    lookup = {node["name"]: node for node in nodes}
    for name in names:
        node = lookup.get(name)
        if not node:
            continue
        for month in MONTHS:
            totals[month]["buh"] += float(node["values"]["Факт БУ"].get(month, 0))
            totals[month]["nu"] += float(node["values"]["Факт НУ"].get(month, 0))
            totals[month]["plan"] += float(node["values"]["План"].get(month, 0))
            totals[month]["forecast"] += float(node["values"]["Прогноз"].get(month, 0))
    return totals


def _build_summary_rows(
    facts: list[Fact],
    *,
    plan_facts: list[Fact] | None = None,
    forecast_facts: list[Fact] | None = None,
) -> list[dict[str, Any]]:
    global _id_seq
    _id_seq = 0

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
            _build_kpi_node(
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
            _attach_revenue_cost_level_drills(
                node,
                revenue_facts,
                cost_facts,
                child_path=list(REVENUE_PATH),
            )
        elif node["name"] == "Себестоимость":
            _attach_revenue_cost_level_drills(
                node,
                revenue_facts,
                cost_facts,
                child_path=list(COST_PATH),
                group_path_keys=list(COST_GROUP_PATH),
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
            _build_kpi_node(
                name,
                _group_facts(facts, kpi_l1=name),
                sign=sign,
                always_nu=always_nu,
                plan_items=_group_facts(plan_facts, kpi_l1=name),
                forecast_items=_group_facts(forecast_facts, kpi_l1=name),
                plan_forecast_from_file=plan_forecast_from_file,
            )
        )

    other_pnl_drill = _build_other_pnl_drill(
        _group_facts(facts, kpi_l1="Прочие доходы"),
        _group_facts(facts, kpi_l1="Прочие расходы"),
    )
    for node in nodes:
        if node["name"] in OTHER_PNL_KPIS:
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
        _build_kpi_node(
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


def _collect_filter_values(
    facts: list[Fact],
    *,
    plan_facts: list[Fact] | None = None,
    forecast_facts: list[Fact] | None = None,
) -> dict[str, list[str]]:
    dimension_facts = list(facts)
    if plan_facts or forecast_facts:
        dimension_facts.extend(plan_facts or [])
        dimension_facts.extend(forecast_facts or [])
    directions = sorted({fact.direction for fact in dimension_facts if fact.direction})
    groups = sorted({fact.project_group for fact in dimension_facts if fact.project_group})
    projects = sorted({fact.project for fact in dimension_facts if fact.project})
    contracts = sorted({fact.contract for fact in dimension_facts if fact.contract})
    contractors = sorted({fact.contractor for fact in dimension_facts if fact.contractor})
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
        {"month": short, "value": totals[full]}
        for full, short in zip(MONTHS, _MONTHS_SHORT, strict=True)
    ]


def _month_from_cost_document(document: object) -> str | None:
    return month_name(parse_date_from_text(document))


def build_cost_structure_facts_from_pq_rows(pq_rows: list[dict[str, object]]) -> list[Fact]:
    """Факты для дерева «Себестоимость» (раздел → направление → …) из PQ cost, без изменения KPI L1."""
    facts: list[Fact] = []
    for row in pq_rows:
        if normalize_text(row.get("Основной раздел")) != "Расходы":
            continue
        if not should_include_in_cost_tree(
            document=row.get("Документ"),
            nomenclature=row.get("Номенклатура"),
        ):
            continue
        month = _month_from_cost_document(row.get("Документ"))
        if month not in MONTHS:
            continue
        section = _normalize_cost_structure_section(str(row.get("Раздел") or ""))
        if not section:
            continue
        amount = float(row.get("Сумма") or 0)
        if not amount:
            continue
        if is_davaltz_cost_document(row.get("Документ")):
            direction = ""
            project_group = davaltz_cost_tree_group(row.get("Документ"))
            project = ""
        else:
            direction = normalize_text(row.get("Направление"))
            project_group = normalize_text(row.get("Группа проектов"))
            project = normalize_text(row.get("Проект"))
        facts.append(
            Fact(
                kpi_l1="Себестоимость",
                month=month,
                amount_buh=-amount,
                amount_nu=-amount,
                direction=direction,
                project_group=project_group,
                project=project,
                nomenclature=normalize_text(row.get("Номенклатура")),
                cost_section=section,
            )
        )
    return facts


_COST_MERGE_OEZ_KEY = "__оэз__"


def _cost_nomenclature_merge_key(nomenclature: object) -> str:
    text = normalize_text(nomenclature).casefold()
    if not text:
        return ""
    if text.startswith("оэз"):
        return _COST_MERGE_OEZ_KEY
    return text


def _map_buh_cost_section(fact: Fact) -> str:
    article = normalize_text(fact.expense_article)
    account = normalize_text(fact.cost_account) or "20"
    if article:
        mapped = _normalize_cost_structure_section(classify_cost_section_pq(article, account))
        if mapped:
            return mapped
    section = _normalize_cost_structure_section(fact.cost_section)
    if section:
        return section
    if normalize_text(fact.nomenclature).casefold() == "прочее":
        return "Прочие производственные расходы"
    return "Общепроизводственные затраты"


def _buh_fact_to_structure(fact: Fact) -> Fact:
    return Fact(
        kpi_l1="Себестоимость",
        month=fact.month,
        amount_buh=fact.amount_buh,
        amount_nu=fact.amount_nu,
        direction=fact.direction,
        project_group=fact.project_group,
        project=fact.project,
        nomenclature=fact.nomenclature,
        cost_section=_map_buh_cost_section(fact),
    )


_COST_SECTION_MATCH_TOLERANCE = 0.05


def _amount_match_tolerance(amount: float) -> float:
    return max(1.0, abs(amount) * 1e-8)


def _build_pq_only_amount_pool(
    pq_groups: dict[tuple[str, str], list[Fact]],
    buh_groups: dict[tuple[str, str], list[Fact]],
) -> dict[str, list[dict[str, Any]]]:
    """PQ-only группы по месяцам для сопоставления с buh-only по сумме."""
    pool: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for key, items in pq_groups.items():
        if key in buh_groups:
            continue
        month, _merge_key = key
        total = sum(fact.amount_buh for fact in items)
        if abs(total) < 1e-9:
            continue
        pool[month].append({"items": items, "total": total, "used": False})
    for month in pool:
        pool[month].sort(key=lambda entry: abs(entry["total"]), reverse=True)
    return pool


def _take_pq_only_amount_match(
    month: str,
    buh_total: float,
    pool: dict[str, list[dict[str, Any]]],
) -> list[Fact] | None:
    """buh-only и PQ-only с той же суммой — одна операция, разные ключи номенклатуры."""
    tolerance = _amount_match_tolerance(buh_total)
    entries = pool.get(month, [])
    best_entry: dict[str, Any] | None = None
    best_delta = tolerance + 1.0
    for entry in entries:
        if entry["used"]:
            continue
        delta = abs(entry["total"] - buh_total)
        if delta <= tolerance and delta < best_delta:
            best_entry = entry
            best_delta = delta
    if best_entry is not None:
        best_entry["used"] = True
        return best_entry["items"]

    unused = [entry for entry in entries if not entry["used"]]
    if len(unused) >= 2:
        from itertools import combinations

        for size in range(2, min(len(unused) + 1, 6)):
            best_combo: tuple[dict[str, Any], ...] | None = None
            best_combo_delta = tolerance + 1.0
            for combo in combinations(unused, size):
                combo_total = sum(entry["total"] for entry in combo)
                delta = abs(combo_total - buh_total)
                if delta <= tolerance and delta < best_combo_delta:
                    best_combo = combo
                    best_combo_delta = delta
            if best_combo is not None:
                merged: list[Fact] = []
                for entry in best_combo:
                    entry["used"] = True
                    merged.extend(entry["items"])
                return merged
    return None


def _scale_pq_splits_to_buh_amount(pq_items: list[Fact], buh_total: float) -> list[Fact]:
    pq_total = sum(fact.amount_buh for fact in pq_items)
    if abs(pq_total) < 1e-9:
        return list(pq_items)
    scaled: list[Fact] = []
    for pq_fact in pq_items:
        share = pq_fact.amount_buh / pq_total
        scaled.append(
            Fact(
                kpi_l1=pq_fact.kpi_l1,
                month=pq_fact.month,
                amount_buh=buh_total * share,
                amount_nu=buh_total * share,
                direction=pq_fact.direction,
                project_group=pq_fact.project_group,
                project=pq_fact.project,
                nomenclature=pq_fact.nomenclature,
                cost_section=pq_fact.cost_section,
                expense_article=pq_fact.expense_article,
                tax_type=pq_fact.tax_type,
                contractor=pq_fact.contractor,
                quantity=pq_fact.quantity,
            )
        )
    return scaled


def _buh_only_with_pq_hint(
    buh_items: list[Fact],
    pq_hint_items: list[Fact],
) -> list[Fact]:
    """Статьи из PQ-only подсказки (та же сумма), аналитика buh сохраняется где возможно."""
    buh_total = sum(fact.amount_buh for fact in buh_items)
    lead = buh_items[0] if buh_items else None
    scaled_pq = _scale_pq_splits_to_buh_amount(pq_hint_items, buh_total)
    adjusted = _apply_buh_nu_to_pq_splits(scaled_pq, buh_items)
    if not lead:
        return adjusted
    return [
        Fact(
            kpi_l1=fact.kpi_l1,
            month=fact.month,
            amount_buh=fact.amount_buh,
            amount_nu=fact.amount_nu,
            direction=lead.direction or fact.direction,
            project_group=lead.project_group or fact.project_group,
            project=lead.project or fact.project,
            nomenclature=lead.nomenclature or fact.nomenclature,
            cost_section=fact.cost_section,
            expense_article=fact.expense_article,
            tax_type=fact.tax_type,
            contractor=fact.contractor,
            quantity=fact.quantity,
        )
        for fact in adjusted
    ]


def _cost_section_totals(
    items: list[Fact],
    section_for: Any,
) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    for fact in items:
        section = section_for(fact)
        if section:
            totals[section] += fact.amount_buh
    return dict(totals)


def _apply_buh_nu_to_pq_splits(pq_items: list[Fact], buh_items: list[Fact]) -> list[Fact]:
    """PQ даёт структуру по БУ; НУ берём из buh и распределяем пропорционально суммам БУ."""
    buh_bu_total = sum(fact.amount_buh for fact in buh_items)
    buh_nu_total = sum(fact.amount_nu for fact in buh_items)
    pq_bu_total = sum(fact.amount_buh for fact in pq_items)
    if abs(pq_bu_total) < 1e-9:
        return [_buh_fact_to_structure(fact) for fact in buh_items]

    adjusted: list[Fact] = []
    nu_assigned = 0.0
    for index, pq_fact in enumerate(pq_items):
        if index == len(pq_items) - 1:
            amount_nu = buh_nu_total - nu_assigned
        else:
            share = pq_fact.amount_buh / pq_bu_total
            amount_nu = buh_nu_total * share
            nu_assigned += amount_nu
        adjusted.append(
            Fact(
                kpi_l1=pq_fact.kpi_l1,
                month=pq_fact.month,
                amount_buh=pq_fact.amount_buh,
                amount_nu=amount_nu,
                direction=pq_fact.direction,
                project_group=pq_fact.project_group,
                project=pq_fact.project,
                nomenclature=pq_fact.nomenclature,
                cost_section=pq_fact.cost_section,
                expense_article=pq_fact.expense_article,
                tax_type=pq_fact.tax_type,
                contractor=pq_fact.contractor,
                quantity=pq_fact.quantity,
            )
        )
    return adjusted


def _group_cost_structure_facts(facts: list[Fact]) -> dict[tuple[str, str], list[Fact]]:
    groups: dict[tuple[str, str], list[Fact]] = defaultdict(list)
    for fact in facts:
        merge_key = _cost_nomenclature_merge_key(fact.nomenclature)
        if not merge_key:
            merge_key = normalize_text(fact.nomenclature).casefold() or "—"
        groups[(fact.month, merge_key)].append(fact)
    return groups


def build_unified_cost_structure_facts(
    buh_cost_facts: list[Fact],
    pq_rows: list[dict[str, object]] | None,
) -> list[Fact]:
    """Единое дерево себестoимости: buh — сумма (L1), PQ — детализация статей/направлений без PQ-only строк."""
    buh_facts = [
        fact
        for fact in buh_cost_facts
        if fact.kpi_l1 == "Себестоимость" and not is_black_metal_scrap_nomenclature(fact.nomenclature)
    ]
    if not buh_facts:
        return []
    if not pq_rows:
        return [_buh_fact_to_structure(fact) for fact in buh_facts]

    pq_facts = build_cost_structure_facts_from_pq_rows(pq_rows)
    pq_groups = _group_cost_structure_facts(pq_facts)
    buh_groups = _group_cost_structure_facts(buh_facts)
    pq_only_pool = _build_pq_only_amount_pool(pq_groups, buh_groups)
    unified: list[Fact] = []

    for key in set(pq_groups) | set(buh_groups):
        pq_items = pq_groups.get(key, [])
        buh_items = buh_groups.get(key, [])
        pq_total = sum(fact.amount_buh for fact in pq_items)
        buh_total = sum(fact.amount_buh for fact in buh_items)

        if buh_items and pq_items and abs(pq_total - buh_total) <= max(1.0, abs(buh_total) * 1e-9):
            unified.extend(_apply_buh_nu_to_pq_splits(pq_items, buh_items))
        elif buh_items:
            pq_hint = _take_pq_only_amount_match(key[0], buh_total, pq_only_pool)
            if pq_hint:
                unified.extend(_buh_only_with_pq_hint(buh_items, pq_hint))
            else:
                unified.extend(_buh_fact_to_structure(fact) for fact in buh_items)

    for month in MONTHS:
        buh_total = sum(fact.amount_buh for fact in buh_facts if fact.month == month)
        if abs(buh_total) < 0.005:
            continue
        unified_total = sum(fact.amount_buh for fact in unified if fact.month == month)
        if abs(unified_total - buh_total) > 0.05:
            unified = [fact for fact in unified if fact.month != month]
            unified.extend(_buh_fact_to_structure(fact) for fact in buh_facts if fact.month == month)

    return unified


COST_STRUCTURE_GAP_PATH = ["cost_section", "nomenclature"]


def build_cost_structure_gap_facts_from_pq_rows(pq_rows: list[dict[str, object]]) -> list[Fact]:
    """Не используется для детализации «Прочее» — gap только buh vs PQ (округление)."""
    del pq_rows
    return []


def _chart_cost_structure_from_pq_rows(pq_rows: list[dict[str, object]]) -> dict[str, Any]:
    """Структура себестоимости из PQ-таблицы (как этalon), месяц — из даты документа отгрузки."""
    monthly_sections: dict[str, dict[str, float]] = {
        month: {section: 0.0 for section in COST_STRUCTURE_SECTIONS} for month in MONTHS
    }
    davaltz_totals = build_davaltz_document_totals(pq_rows)

    for row in pq_rows:
        if normalize_text(row.get("Основной раздел")) != "Расходы":
            continue
        if not should_include_in_cost_structure(
            document=row.get("Документ"),
            nomenclature=row.get("Номенклатура"),
            davaltz_totals=davaltz_totals,
        ):
            continue
        month = _month_from_cost_document(row.get("Документ"))
        if month not in monthly_sections:
            continue
        section = _normalize_cost_structure_section(str(row.get("Раздел") or ""))
        if not section:
            continue
        monthly_sections[month][section] += float(row.get("Сумма") or 0)

    by_month: list[dict[str, Any]] = []
    for full, short in zip(MONTHS, _MONTHS_SHORT, strict=True):
        section_values = {
            name: abs(float(monthly_sections[full].get(name, 0) or 0)) for name in COST_STRUCTURE_SECTIONS
        }
        by_month.append(
            {
                "month": short,
                "total": sum(section_values.values()),
                "sections": section_values,
            }
        )

    return {
        "sections": list(COST_STRUCTURE_SECTIONS),
        "by_month": by_month,
    }


def _chart_cost_structure(facts: list[Fact]) -> dict[str, Any]:
    """Себестоимость: только стандартные статьи затрат (как в дереве P&L)."""

    monthly_sections: dict[str, dict[str, float]] = {
        month: {section: 0.0 for section in COST_STRUCTURE_SECTIONS} for month in MONTHS
    }

    for fact in facts:
        if fact.kpi_l1 != "Себестоимость":
            continue
        if is_black_metal_scrap_nomenclature(fact.nomenclature):
            continue
        section = _normalize_cost_structure_section(fact.cost_section)
        if not section:
            continue
        monthly_sections[fact.month][section] += abs(fact.amount_buh)

    by_month: list[dict[str, Any]] = []
    for full, short in zip(MONTHS, _MONTHS_SHORT, strict=True):
        section_values = {
            name: float(monthly_sections[full].get(name, 0) or 0) for name in COST_STRUCTURE_SECTIONS
        }
        by_month.append(
            {
                "month": short,
                "total": sum(section_values.values()),
                "sections": section_values,
            }
        )

    return {
        "sections": list(COST_STRUCTURE_SECTIONS),
        "by_month": by_month,
    }


def _empty_cost_structure() -> dict[str, Any]:
    empty_sections = {section: 0.0 for section in COST_STRUCTURE_SECTIONS}
    return {
        "sections": list(COST_STRUCTURE_SECTIONS),
        "by_month": [
            {"month": short, "total": 0.0, "sections": dict(empty_sections)}
            for short in _MONTHS_SHORT
        ],
    }


def build_dashboard_from_pipeline(
    result: PipelineResult,
    *,
    upload_names: dict[str, str],
    plan_facts: list[Fact] | None = None,
    forecast_facts: list[Fact] | None = None,
) -> dict[str, Any]:
    summary_rows = _build_summary_rows(
        result.facts,
        plan_facts=plan_facts,
        forecast_facts=forecast_facts,
    )
    contractor_details = build_contractor_details(result.facts)
    contractor_cards = build_contractor_cards(contractor_details)
    revenue_chart = _chart_series(result.facts, "Выручка")
    cost_chart = _chart_series(result.facts, "Себестоимость")
    cost_structure = _chart_cost_structure(result.facts)
    return {
        "months": MONTHS,
        "scenarios": SCENARIOS,
        "units": UNITS,
        "filters": _collect_filter_values(
            result.facts,
            plan_facts=plan_facts,
            forecast_facts=forecast_facts,
        ),
        "summary_rows": summary_rows,
        "contractor_details": contractor_details,
        "contractor_cards": contractor_cards,
        "revenue_by_month": revenue_chart,
        "cost_by_month": cost_chart,
        "cost_structure_by_month": cost_structure,
        "cost_structure_total": sum(item["value"] for item in cost_chart),
        "meta": {
            "source": "upload",
            "parsed": bool(result.facts),
            "upload_files": upload_names,
            "warnings": result.warnings,
            "message": "Дашборд построен из загруженных выгрузок 1С.",
        },
    }
