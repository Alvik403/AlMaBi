from __future__ import annotations

from copy import deepcopy
from typing import Any


MONTHS = [
    "Январь",
    "Февраль",
    "Март",
    "Апрель",
    "Май",
    "Июнь",
    "Июль",
    "Август",
    "Сентябрь",
    "Октябрь",
    "Ноябрь",
    "Декабрь",
]

_MONTHS_SHORT = [
    "Янв.",
    "Фев.",
    "Мар.",
    "Апр.",
    "Май",
    "Июн.",
    "Июл.",
    "Авг.",
    "Сен.",
    "Окт.",
    "Ноя.",
    "Дек.",
]
SCENARIOS = ["Факт БУХ", "Факт НУ", "План", "Прогноз"]
QUARTERS = ["Q1", "Q2", "Q3", "Q4"]
QUARTER_MONTHS = {
    "Q1": ["Январь", "Февраль", "Март"],
    "Q2": ["Апрель", "Май", "Июнь"],
    "Q3": ["Июль", "Август", "Сентябрь"],
    "Q4": ["Октябрь", "Ноябрь", "Декабрь"],
}
UNITS = [
    {"key": "rub", "label": "руб", "divisor": 1},
    {"key": "thousands", "label": "тыс. руб", "divisor": 1000},
    {"key": "millions", "label": "млн. руб", "divisor": 1000000},
    {"key": "billions", "label": "млрд. руб", "divisor": 1000000000},
]

_NOMENCLATURE = [
    ("Лицензия ПО", 0.42),
    ("Услуги внедрения", 0.33),
    ("Техническая поддержка", 0.25),
]

_BENEFIT_SECTIONS = {"Прочие доходы", "Прочие расходы", "Налоги"}

_ORG = {
    "directions": [
        ("Цифровые продукты", 0.42),
        ("Интеграция", 0.33),
        ("Поддержка", 0.25),
    ],
    "groups": {
        "Цифровые продукты": [("BI", 0.55), ("Аналитика", 0.45)],
        "Интеграция": [("ERP", 0.6), ("Инфраструктура", 0.4)],
        "Поддержка": [("Сопровождение", 0.7), ("Сервис", 0.3)],
    },
    "projects": {
        "BI": [("AlMaBi R&D", 0.65), ("Витрина KPI", 0.35)],
        "Аналитика": [("Прогноз P&L", 1.0)],
        "ERP": [("Платформа данных", 0.55), ("Учёт затрат", 0.45)],
        "Инфраструктура": [("Облако", 1.0)],
        "Сопровождение": [("L1 поддержка", 1.0)],
        "Сервис": [("Аутсорс", 1.0)],
    },
    "contracts": {
        "AlMaBi R&D": [("Д-001", 0.58), ("Д-014", 0.42)],
        "Витрина KPI": [("Д-027", 1.0)],
        "Прогноз P&L": [("Д-031", 1.0)],
        "Платформа данных": [("Д-044", 0.62), ("Д-052", 0.38)],
        "Учёт затрат": [("Д-061", 1.0)],
        "Облако": [("Д-070", 1.0)],
        "L1 поддержка": [("Д-081", 1.0)],
        "Аутсорс": [("Д-090", 1.0)],
    },
}

_COST_TYPES = [
    ("Материальные затраты", 0.34, "org_short"),
    ("ФОТ", 0.28, "org_deep"),
    ("Аренда (прямые)", 0.14, "org_deep"),
    ("Амортизация", 0.12, "org_deep"),
    ("Общепроизводственные затраты", 0.12, "org_deep"),
]

_BENEFIT_SPLIT = [("Льготные проекты", 0.38), ("Нельготные проекты", 0.62)]

_OTHER_ARTICLES = [
    ("Проценты полученные", 0.35),
    ("Курсовые разницы", 0.25),
    ("Штрафы и пени", 0.2),
    ("Прочее", 0.2),
]

_id_seq = 0


def _next_id(prefix: str) -> str:
    global _id_seq
    _id_seq += 1
    return f"{prefix}-{_id_seq}"


def _expand_quarterly_values(quarter_totals: list[int]) -> list[int]:
    """Раскладывает 4 квартальных суммы по 3 месяцам в каждом квартале."""
    months: list[int] = []
    for total in quarter_totals:
        base = total // 3
        remainder = total - base * 3
        for index in range(3):
            months.append(base + (1 if index < remainder else 0))
    return months


def _month_values(
    values: list[int],
    plan_multiplier: float = 1.08,
    *,
    revenue_aligned: bool = False,
) -> dict[str, dict[str, int]]:
    fact_buh = dict(zip(MONTHS, values, strict=True))
    return {
        "Факт БУХ": fact_buh,
        "Факт НУ": fact_buh if revenue_aligned else dict(zip(MONTHS, [round(value * 0.96) for value in values], strict=True)),
        "План": dict(zip(MONTHS, [round(value * plan_multiplier) for value in values], strict=True)),
        "Прогноз": dict(zip(MONTHS, [round(value * 1.12) for value in values], strict=True)),
    }


def _sum_months(rows: list[dict[str, Any]], scenario: str) -> dict[str, int]:
    totals = {month: 0 for month in MONTHS}
    for row in rows:
        month_map = row["values"][scenario]
        for month in MONTHS:
            totals[month] += int(month_map.get(month, 0))
    return totals


def _scale_months(values: list[int], factor: float, *, sign: int = 1) -> list[int]:
    return [round(value * factor) * sign for value in values]


def _attach_metrics(node: dict[str, Any]) -> dict[str, Any]:
    children = node.get("children") or []
    if children:
        for child in children:
            _attach_metrics(child)
        for scenario in SCENARIOS:
            node["values"][scenario] = _sum_months(children, scenario)

    fact = node["values"]["Факт БУХ"]
    plan = node["values"]["План"]
    total_fact = sum(fact.values())
    total_plan = sum(plan.values())
    node["total_fact"] = total_fact
    node["total_plan"] = total_plan
    node["percent"] = (total_fact / total_plan * 100) if total_plan else 0.0
    node["expandable"] = bool(children)
    return node


def _leaf(
    name: str,
    level: int,
    month_values: list[int],
    *,
    sign: int = 1,
    id_prefix: str = "leaf",
    revenue_aligned: bool = False,
) -> dict[str, Any]:
    return {
        "id": _next_id(id_prefix),
        "name": name,
        "level": level,
        "values": _month_values(_scale_months(month_values, 1, sign=sign), revenue_aligned=revenue_aligned),
        "children": [],
    }


def _split_values(
    month_values: list[int],
    weights: list[tuple[str, float]],
    level: int,
    *,
    sign: int = 1,
    id_prefix: str = "split",
    revenue_aligned: bool = False,
    merge_duplicates: bool = False,
) -> list[dict[str, Any]]:
    merged: dict[str, float] = {}
    for name, weight in weights:
        merged[name] = merged.get(name, 0.0) + weight

    items = list(merged.items()) if merge_duplicates else weights
    if merge_duplicates:
        total = sum(merged.values()) or 1.0
        items = [(name, weight / total) for name, weight in merged.items()]

    return [
        _leaf(
            name,
            level,
            _scale_months(month_values, weight),
            sign=sign,
            id_prefix=id_prefix,
            revenue_aligned=revenue_aligned,
        )
        for name, weight in items
    ]


def _build_org_tree(
    month_values: list[int],
    start_level: int,
    *,
    sign: int = 1,
    include_contract: bool,
    include_nomenclature: bool = False,
    revenue_aligned: bool = False,
) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    for direction, direction_weight in _ORG["directions"]:
        direction_values = _scale_months(month_values, direction_weight)
        group_children: list[dict[str, Any]] = []
        for group, group_weight in _ORG["groups"][direction]:
            group_values = _scale_months(direction_values, group_weight)
            project_children: list[dict[str, Any]] = []
            for project, project_weight in _ORG["projects"][group]:
                project_values = _scale_months(group_values, project_weight)
                contract_children: list[dict[str, Any]] = []
                if include_contract:
                    for contract, contract_weight in _ORG["contracts"][project]:
                        contract_values = _scale_months(project_values, contract_weight)
                        nomenclature_children: list[dict[str, Any]] = []
                        if include_nomenclature:
                            nomenclature_children = _split_values(
                                contract_values,
                                _NOMENCLATURE,
                                start_level + 5,
                                sign=sign,
                                id_prefix="nomenclature",
                                revenue_aligned=revenue_aligned,
                            )
                        contract_children.append(
                            {
                                "id": _next_id(f"contract-{contract}"),
                                "name": contract,
                                "level": start_level + 4,
                                "values": _month_values(
                                    _scale_months(project_values, contract_weight, sign=sign),
                                    revenue_aligned=revenue_aligned,
                                ),
                                "children": nomenclature_children,
                            }
                        )
                project_children.append(
                    {
                        "id": _next_id(f"project-{project}"),
                        "name": project,
                        "level": start_level + 3,
                        "values": _month_values(
                            _scale_months(group_values, project_weight, sign=sign),
                            revenue_aligned=revenue_aligned,
                        ),
                        "children": contract_children,
                    }
                )
            group_children.append(
                {
                    "id": _next_id(f"group-{group}"),
                    "name": group,
                    "level": start_level + 2,
                    "values": _month_values(
                        _scale_months(direction_values, group_weight, sign=sign),
                        revenue_aligned=revenue_aligned,
                    ),
                    "children": project_children,
                }
            )
        nodes.append(
            {
                "id": _next_id(f"direction-{direction}"),
                "name": direction,
                "level": start_level + 1,
                "values": _month_values(
                    _scale_months(month_values, direction_weight, sign=sign),
                    revenue_aligned=revenue_aligned,
                ),
                "children": group_children,
            }
        )
    return nodes


def _build_cost_branch(month_values: list[int], revenue_values: list[int], *, sign: int = -1) -> list[dict[str, Any]]:
    branches: list[dict[str, Any]] = []
    revenue_node = {
        "id": _next_id("cost-revenue"),
        "name": "Выручка",
        "level": 2,
        "values": _month_values(_scale_months(revenue_values, 1, sign=1), revenue_aligned=True),
        "children": _build_org_tree(
            revenue_values,
            start_level=3,
            sign=1,
            include_contract=False,
            include_nomenclature=False,
            revenue_aligned=True,
        ),
    }
    branches.append(revenue_node)

    for cost_name, weight, drill_mode in _COST_TYPES:
        branch_values = _scale_months(month_values, weight)
        if drill_mode == "org_short":
            children = _build_org_tree(
                branch_values,
                start_level=3,
                sign=sign,
                include_contract=False,
                include_nomenclature=True,
            )
        else:
            children = [
                {
                    "id": _next_id(f"cost-dir-{cost_name}"),
                    "name": name,
                    "level": 3,
                    "values": _month_values(_scale_months(branch_values, sub_weight, sign=sign)),
                    "children": _build_org_tree(
                        _scale_months(branch_values, sub_weight),
                        start_level=4,
                        sign=sign,
                        include_contract=False,
                        include_nomenclature=True,
                    ),
                }
                for name, sub_weight in _ORG["directions"]
            ]
        branches.append(
            {
                "id": _next_id(f"cost-{cost_name}"),
                "name": cost_name,
                "level": 2,
                "values": _month_values(_scale_months(month_values, weight, sign=sign)),
                "children": children,
            }
        )
    return branches


def _build_benefit_branch(month_values: list[int], *, sign: int = 1, with_articles: bool = False) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    for benefit_name, weight in _BENEFIT_SPLIT:
        benefit_values = _scale_months(month_values, weight)
        children: list[dict[str, Any]] = []
        if with_articles:
            # Дублирующиеся статьи объединяются в одну строку.
            article_weights = _OTHER_ARTICLES + [("Прочее", 0.12)]
            children = _split_values(
                benefit_values,
                article_weights,
                level=3,
                sign=sign,
                id_prefix="article",
                merge_duplicates=True,
            )
        nodes.append(
            {
                "id": _next_id(f"benefit-{benefit_name}"),
                "name": benefit_name,
                "level": 2,
                "values": _month_values(_scale_months(month_values, weight, sign=sign)),
                "children": children,
            }
        )
    return nodes


def _section_children(
    section_name: str,
    month_values: list[int],
    *,
    sign: int = 1,
    revenue_values: list[int] | None = None,
) -> list[dict[str, Any]]:
    if section_name in _BENEFIT_SECTIONS:
        return _build_benefit_branch(
            month_values,
            sign=sign,
            with_articles=section_name in {"Прочие доходы", "Прочие расходы"},
        )
    if section_name == "Себестоимость" and revenue_values is not None:
        return _build_cost_branch(month_values, revenue_values, sign=sign)
    if section_name == "Выручка":
        return _build_org_tree(
            month_values,
            start_level=2,
            include_contract=True,
            include_nomenclature=True,
            revenue_aligned=True,
        )
    return _build_org_tree(month_values, start_level=2, sign=sign, include_contract=False)


def _kpi_node(
    name: str,
    month_values: list[int],
    *,
    sign: int = 1,
    children: list[dict[str, Any]] | None = None,
    revenue_values: list[int] | None = None,
) -> dict[str, Any]:
    revenue_aligned = name == "Выручка"
    return _attach_metrics(
        {
            "id": _next_id(f"kpi-{name}"),
            "name": name,
            "level": 1,
            "values": _month_values(_scale_months(month_values, 1, sign=sign), revenue_aligned=revenue_aligned),
            "children": children if children is not None else _section_children(name, month_values, sign=sign, revenue_values=revenue_values),
        }
    )


def build_summary_rows() -> list[dict[str, Any]]:
    global _id_seq
    _id_seq = 0
    revenue = _expand_quarterly_values([202_498_000, 70_156_000, 318_497_000, 415_264_000])
    cost = _expand_quarterly_values([183_300_000, 44_496_000, 225_764_000, 274_509_000])
    commercial = _expand_quarterly_values([124_000, 177_000, 245_995, 0])
    admin = _expand_quarterly_values([79_848_000, 77_209_000, 83_589_000, 333_300_000])
    operating = _expand_quarterly_values([407_000, 64_378_000, 72_885_000, 287_423_000])
    other_income = _expand_quarterly_values([24_030_000, 67_957_000, 142_010_000, 233_860_000])
    other_expense = _expand_quarterly_values([16_155_000, 67_770_000, 144_535_000, 860_235_000])
    pbt = _expand_quarterly_values([62_532_000, 64_191_000, 75_411_000, 2_216_654_000])
    taxes = _expand_quarterly_values([17_594_000, 26_606_000, 98_975_000, 289_574_000])
    net = _expand_quarterly_values([80_126_000, 90_797_000, 174_385_000, 2_508_228_000])

    return [
        _kpi_node("Выручка", revenue),
        _kpi_node("Себестоимость", cost, sign=-1, revenue_values=revenue),
        _kpi_node("Коммерческие расходы", commercial, sign=-1),
        _kpi_node("Управленческие расходы", admin, sign=-1),
        _kpi_node("Операционная прибыль", operating),
        _kpi_node("Прочие доходы", other_income),
        _kpi_node("Прочие расходы", other_expense, sign=-1),
        _kpi_node("Прибыль/убыток до налогообложения", pbt, sign=-1),
        _kpi_node("Налоги", taxes, sign=-1),
        _kpi_node("Чистая прибыль", net, sign=-1),
    ]


def _bar_row(name: str, value: int, color: str = "green") -> dict:
    return {"name": name, "value": value, "color": color}


CONTRACTOR_CARDS = [
    {
        "title": "Реализация льгота",
        "accent": "blue",
        "total": 598_826_200,
        "rows": [
            _bar_row("ООО Альфа Проект", 434_451_150),
            _bar_row("АО Северное направление", 145_984_470),
            _bar_row("ИП Группа Интеграция", 11_338_620),
            _bar_row("ООО Лаборатория данных", 3_965_610),
            _bar_row("ЗАО Пилотный договор", 3_086_350),
        ],
    },
    {
        "title": "Реализация нельгота",
        "accent": "rose",
        "total": 10_070_835_550,
        "rows": [
            _bar_row("ООО Магистраль", 4_699_744_080, "rose"),
            _bar_row("АО Промышленный контур", 2_838_189_110, "rose"),
            _bar_row("ООО Восток сервис", 1_597_604_080, "rose"),
            _bar_row("ГК Инфраструктура", 860_672_410, "rose"),
            _bar_row("ИП Технический заказчик", 74_625_860, "rose"),
        ],
    },
]

def _chart_series(quarter_totals: list[int]) -> list[dict[str, Any]]:
    return [
        {"month": label, "value": value}
        for label, value in zip(
            _MONTHS_SHORT,
            _expand_quarterly_values(quarter_totals),
            strict=True,
        )
    ]


REVENUE_BY_MONTH = _chart_series([202_498_000, 70_156_000, 318_497_000, 415_264_000])
COST_BY_MONTH = _chart_series([183_300_000, 44_496_000, 225_764_000, 274_509_000])
COST_STRUCTURE_TOTAL = sum(item["value"] for item in COST_BY_MONTH)

FILTERS = {
    "taxType": ["Все виды", "Льготные проекты", "Нельготные проекты"],
    "project": ["Все проекты", "AlMaBi R&D", "Платформа данных", "Витрина KPI", "Облако"],
    "direction": ["Все направления", "Цифровые продукты", "Интеграция", "Поддержка"],
    "projectGroup": ["Все группы", "BI", "ERP", "Аналитика", "Инфраструктура"],
    "contract": ["Все договоры", "Д-001", "Д-014", "Д-027", "Д-044"],
    "contractor": ["Все контрагенты", "ООО Альфа Проект", "АО Промышленный контур"],
    "quarter": ["Все кварталы", *QUARTERS],
    "month": ["Все месяцы", *MONTHS],
}


def get_almabi_dashboard_data() -> dict:
    summary_rows = build_summary_rows()
    return {
        "months": MONTHS,
        "scenarios": SCENARIOS,
        "units": UNITS,
        "filters": deepcopy(FILTERS),
        "summary_rows": deepcopy(summary_rows),
        "contractor_cards": deepcopy(CONTRACTOR_CARDS),
        "revenue_by_month": deepcopy(REVENUE_BY_MONTH),
        "cost_by_month": deepcopy(COST_BY_MONTH),
        "cost_structure_total": COST_STRUCTURE_TOTAL,
    }
