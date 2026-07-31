from __future__ import annotations

from pathlib import Path

from almabi_export_parsers import classify_cost_section_pq, parse_exports
from almabi_test_dashboard_builder import build_test_summary_rows_from_facts
from almabi_test_pipeline import build_test_facts
from tests.test_almabi_exports import (
    create_buh_workbook,
    create_cost_workbook,
    create_realization_workbook,
)


def _child_names(node: dict) -> list[str]:
    return [child["name"] for child in node.get("children") or []]


def _max_level(node: dict) -> int:
    children = node.get("children") or []
    if not children:
        return int(node["level"])
    return max(_max_level(child) for child in children)


def test_classify_cost_section_pq_matches_excel_rules():
    assert classify_cost_section_pq("Сырье и материалы", "20") == "Материальные затраты"
    assert classify_cost_section_pq("Прочие производственные расходы", "20") == "Общепроизводственные затраты"
    assert classify_cost_section_pq("Оплата труда", "20") == "ФОТ"
    assert classify_cost_section_pq("Страховые взносы", "20") == "ФОТ"
    assert classify_cost_section_pq("Аренда", "20") == "Аренда (прямые)"
    assert classify_cost_section_pq("Амортизация", "20") == "Амортизация"
    assert classify_cost_section_pq("Возвратные отходы", "20") == "Материальные затраты"
    assert classify_cost_section_pq("Полуфабрикаты производимые в процессе", "20") == "Материальные затраты"
    assert classify_cost_section_pq("Работы Субподрядчика", "20") == "Прочие производственные расходы"
    assert classify_cost_section_pq("Прочее", "20") == "Прочие производственные расходы"
    assert classify_cost_section_pq("Сырье и материалы", "10") == "Прочие производственные расходы"


def test_test_dashboard_grouping(tmp_path: Path):
    paths = {
        "buh": tmp_path / "buh.xlsx",
        "realization": tmp_path / "realization.xlsx",
        "cost": tmp_path / "cost.xlsx",
    }
    create_buh_workbook(paths["buh"])
    create_realization_workbook(paths["realization"])
    create_cost_workbook(paths["cost"])

    result = build_test_facts(parse_exports(paths))
    rows = {row["name"]: row for row in build_test_summary_rows_from_facts(result.facts)}

    assert _max_level(rows["Выручка"]) == 5
    revenue_direction = rows["Выручка"]["children"][0]
    revenue_project = revenue_direction["children"][0]["children"][0]
    assert "Д-001" in _child_names(revenue_project)

    cost = rows["Себестоимость"]
    cost_section = cost["children"][0]
    assert cost_section["name"] == "Материальные затраты"
    assert cost_section["children"][0]["name"] == "Услуги"
    assert _max_level(cost) == 5

    commercial = rows["Коммерческие расходы"]
    assert _child_names(commercial) == ["Льготные проекты", "Нельготные проекты"]
    nelf_commercial = next(child for child in commercial["children"] if "Нельгот" in child["name"])
    assert _child_names(nelf_commercial) == ["Д-001"]

    other = rows["Прочие доходы"]
    assert _child_names(other) == ["Льготные проекты", "Нельготные проекты"]

    assert _child_names(rows["Операционная прибыль"]) == ["Льготные проекты", "Нельготные проекты"]
    assert _child_names(rows["Прибыль/убыток до налогообложения"]) == ["Льготные проекты", "Нельготные проекты"]
    assert _child_names(rows["Чистая прибыль"]) == ["Льготные проекты", "Нельготные проекты"]
    operating = rows["Операционная прибыль"]
    nelf_operating = next(child for child in operating["children"] if "Нельгот" in child["name"])
    assert _child_names(nelf_operating)

    operating = rows["Операционная прибыль"]
    privileged = next(child for child in operating["children"] if "Льгот" in child["name"] and "Нельгот" not in child["name"])
    assert privileged["total_fact"] > 0
