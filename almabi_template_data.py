from __future__ import annotations

from copy import deepcopy
from typing import Any

from almabi_mock_data import (
    MONTHS,
    SCENARIOS,
    UNITS,
    _chart_series,
    _expand_quarterly_values,
    _kpi_node,
)


_TEMPLATE_FILTERS = {
    "taxType": ["Все виды", "Льготные проекты", "Нельготные проекты"],
    "project": ["Все проекты", "П-101 «Универсальный отчёт»", "П-204 «Витрина БДР»", "П-318 «Интеграция 1С»"],
    "direction": ["Все направления", "Основное производство", "Административный блок", "Коммерция"],
    "projectGroup": ["Все группы", "БДР", "Реализации", "Амортизация"],
    "contract": ["Все договоры", "ДГ-2026/01", "ДГ-2026/14", "ДГ-2026/27"],
    "contractor": ["Все контрагенты", "ООО Универсал Сервис", "АО Северный контур"],
    "quarter": ["Все кварталы", "Q1", "Q2", "Q3", "Q4"],
    "month": ["Все месяцы", *MONTHS],
}

_TEMPLATE_CONTRACTORS = [
    {
        "title": "Реализация льгота",
        "accent": "blue",
        "total": 248_500_000,
        "rows": [
            {"name": "ООО Универсал Сервис", "value": 142_300_000, "color": "green"},
            {"name": "АО Северный контур", "value": 78_900_000, "color": "green"},
            {"name": "ИП Лаборатория BI", "value": 18_400_000, "color": "green"},
            {"name": "ООО Пилот БДР", "value": 8_900_000, "color": "green"},
        ],
    },
    {
        "title": "Реализация нельгота",
        "accent": "rose",
        "total": 412_750_000,
        "rows": [
            {"name": "ООО Магистраль Данных", "value": 198_400_000, "color": "rose"},
            {"name": "АО Промышленный контур", "value": 121_600_000, "color": "rose"},
            {"name": "ООО Восток сервис", "value": 62_350_000, "color": "rose"},
            {"name": "ГК Инфраструктура", "value": 30_400_000, "color": "rose"},
        ],
    },
]


def _build_template_summary_rows() -> list[dict[str, Any]]:
    revenue = _expand_quarterly_values([88_400_000, 31_200_000, 136_800_000, 178_500_000])
    cost = _expand_quarterly_values([79_900_000, 19_800_000, 98_400_000, 118_200_000])
    commercial = _expand_quarterly_values([54_000, 78_000, 102_000, 0])
    admin = _expand_quarterly_values([34_800_000, 33_600_000, 36_400_000, 142_000_000])
    operating = _expand_quarterly_values([178_000, 28_100_000, 31_800_000, 124_600_000])
    other_income = _expand_quarterly_values([10_500_000, 29_700_000, 62_100_000, 102_200_000])
    other_expense = _expand_quarterly_values([7_100_000, 29_600_000, 63_200_000, 376_400_000])
    pbt = _expand_quarterly_values([27_300_000, 28_000_000, 32_900_000, 968_400_000])
    taxes = _expand_quarterly_values([7_700_000, 11_600_000, 43_200_000, 126_500_000])
    net = _expand_quarterly_values([35_000_000, 39_600_000, 76_100_000, 1_094_900_000])

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


def get_almabi_template_dashboard_data() -> dict[str, Any]:
    summary_rows = _build_template_summary_rows()
    revenue_chart = _chart_series([88_400_000, 31_200_000, 136_800_000, 178_500_000])
    cost_chart = _chart_series([79_900_000, 19_800_000, 98_400_000, 118_200_000])
    return {
        "months": MONTHS,
        "scenarios": SCENARIOS,
        "units": UNITS,
        "filters": deepcopy(_TEMPLATE_FILTERS),
        "summary_rows": deepcopy(summary_rows),
        "contractor_cards": deepcopy(_TEMPLATE_CONTRACTORS),
        "revenue_by_month": deepcopy(revenue_chart),
        "cost_by_month": deepcopy(cost_chart),
        "cost_structure_total": sum(item["value"] for item in cost_chart),
        "meta": {
            "source": "template",
            "title": "Шаблон БДР (тестовое заполнение)",
            "description": "Данные по структуре «Универсальный отчёт для БДР» и маппингу полей BI.",
            "template_file": "fixtures/bdr_template_empty.xlsx",
            "field_mapping_file": "fixtures/bi_field_names.xlsx",
        },
    }
