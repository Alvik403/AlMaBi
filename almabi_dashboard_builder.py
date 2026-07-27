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
# Уровни как в «Уровни для дашборда»: L1 — KPI, далее вложенность до L5.
REVENUE_PATH = ["direction", "project_group", "project", "contract"]
COST_PATH = list(REVENUE_PATH)
# В расшифровке выручки/себестоимости группы раскрываются до предпоследнего уровня пути выручки.
REVENUE_COST_GROUP_PATH = REVENUE_PATH[:-1]

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


def _remaining_revenue_cost_group_path(filters: list[tuple[str, str]]) -> list[str]:
    fixed = {key for key, _ in filters}
    return [key for key in REVENUE_COST_GROUP_PATH if key not in fixed]


def _attach_revenue_cost_level_drills(
    node: dict[str, Any],
    revenue_facts: list[Fact],
    cost_facts: list[Fact],
    *,
    child_path: list[str],
    filters: list[tuple[str, str]] | None = None,
) -> None:
    """Вешает расшифровку на узел и всех потомков в рамках текущего среза."""
    active_filters = list(filters or [])
    scoped_rev, scoped_cost = _scope_revenue_cost_facts(revenue_facts, cost_facts, active_filters)
    node["drill"] = _build_revenue_cost_drill(
        scoped_rev,
        scoped_cost,
        group_path=_remaining_revenue_cost_group_path(active_filters),
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


def _scenario_amounts(items: list[Fact] | None, *, always_nu: bool = False) -> dict[str, float] | None:
    if not items:
        return None
    aggregated = _aggregate_months(items)
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


def _attach_metrics(node: dict[str, Any]) -> dict[str, Any]:
    children = node.get("children") or []
    if children:
        for child in children:
            _attach_metrics(child)
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
    return mapping[key]


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
        node = _attach_metrics(
            {
                "id": _next_id("benefit"),
                "name": benefit_name,
                "level": 2,
                "plan_forecast_from_file": plan_forecast_from_file,
                "values": _month_values(
                    _aggregate_months(benefit_items),
                    plan_amounts=_scenario_amounts(plan_grouped.get(benefit_name, [])),
                    forecast_amounts=_scenario_amounts(forecast_grouped.get(benefit_name, [])),
                    from_file=plan_forecast_from_file,
                ),
                "children": children,
            }
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


def _build_tax_facts(component_nodes: list[dict[str, Any]], source_facts: list[Fact]) -> list[Fact]:
    """Налог по льготным/нельготным базам НУ: ставка × база, только если база > 0."""
    grouped: dict[tuple[str, str], float] = defaultdict(float)
    for fact in source_facts:
        if fact.kpi_l1 not in PBT_TAX_BASE_KPIS:
            continue
        grouped[(fact.month, fact.tax_type)] += fact.amount_nu

    if not grouped:
        pbt = _sum_nodes_by_name(component_nodes, ["Прибыль/убыток до налогообложения"], "Факт НУ")
        tax_facts: list[Fact] = []
        for month in MONTHS:
            base = pbt.get(month, 0)
            if base <= 0:
                continue
            tax_value = -base * 0.25
            tax_facts.append(
                Fact(
                    kpi_l1="Налоги",
                    month=month,
                    amount_buh=tax_value,
                    amount_nu=tax_value,
                    tax_type="Общие условия налогообложения",
                )
            )
        return tax_facts

    tax_facts: list[Fact] = []
    for (month, tax_type), amount in grouped.items():
        if amount <= 0:
            continue
        tax_value = -amount * _tax_rate_for_type(tax_type)
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


def _build_calculated_node(
    name: str,
    month_totals: dict[str, dict[str, float]],
    *,
    children: list[dict[str, Any]] | None = None,
    benefit_facts: list[Fact] | None = None,
    plan_forecast_from_file: bool = False,
) -> dict[str, Any]:
    benefit_children = children
    if benefit_children is None and benefit_facts is not None:
        benefit_children = _build_benefit_children(
            benefit_facts,
            with_articles=False,
            plan_forecast_from_file=plan_forecast_from_file,
        )
    plan_amounts = {month: float(month_totals[month].get("plan", 0) or 0) for month in MONTHS}
    forecast_amounts = {month: float(month_totals[month].get("forecast", 0) or 0) for month in MONTHS}
    node = _attach_metrics(
        {
            "id": _next_id(f"calc-{name}"),
            "name": name,
            "level": 1,
            "plan_forecast_from_file": plan_forecast_from_file,
            "values": _month_values(
                month_totals,
                plan_amounts=plan_amounts if plan_forecast_from_file or any(plan_amounts.values()) else None,
                forecast_amounts=forecast_amounts if plan_forecast_from_file or any(forecast_amounts.values()) else None,
                from_file=plan_forecast_from_file,
            ),
            "children": benefit_children or [],
        }
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
            )

    operating_totals = _month_totals_from_nodes(
        nodes,
        ["Выручка", "Себестоимость", "Коммерческие расходы", "Управленческие расходы"],
    )
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
            benefit_facts=operating_facts,
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

    pbt_totals = _month_totals_from_nodes(
        nodes,
        ["Операционная прибыль", "Прочие доходы", "Прочие расходы"],
    )
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
            benefit_facts=pbt_facts,
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

    net_totals = _month_totals_from_nodes(nodes, ["Прибыль/убыток до налогообложения", "Налоги"])
    net_facts = _merge_signed_fact_groups(
        [
            (pbt_facts, 1),
            (tax_facts, 1),
        ]
    )
    nodes.append(
        _build_calculated_node(
            "Чистая прибыль",
            net_totals,
            benefit_facts=net_facts,
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


def _chart_cost_structure(facts: list[Fact]) -> dict[str, Any]:
    """Себестоимость: только стандартные статьи затрат (как в дереве P&L)."""

    monthly_sections: dict[str, dict[str, float]] = {
        month: {section: 0.0 for section in COST_STRUCTURE_SECTIONS} for month in MONTHS
    }

    for fact in facts:
        if fact.kpi_l1 != "Себестоимость":
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


def load_almabi_dashboard_from_exports(
    paths: dict[str, Path],
    *,
    upload_names: dict[str, str],
    plan_forecast_path: Path | None = None,
) -> dict[str, Any]:
    result = run_pipeline(paths)
    plan_facts: list[Fact] = []
    forecast_facts: list[Fact] = []
    plan_warnings: list[str] = []
    if plan_forecast_path and plan_forecast_path.exists():
        from almabi_plan_forecast_parser import parse_plan_forecast_workbook

        parsed = parse_plan_forecast_workbook(plan_forecast_path)
        plan_facts = parsed.plan_facts
        forecast_facts = parsed.forecast_facts
        plan_warnings = parsed.warnings
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
    dashboard = build_dashboard_from_pipeline(
        result,
        upload_names=upload_names,
        plan_facts=plan_facts,
        forecast_facts=forecast_facts,
    )
    if plan_warnings:
        dashboard.setdefault("meta", {})["plan_forecast_warnings"] = plan_warnings
    if plan_forecast_path:
        dashboard.setdefault("meta", {})["plan_forecast_loaded"] = bool(plan_facts or forecast_facts)
    return dashboard
