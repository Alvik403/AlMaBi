"""Tests for cost tree structure from PQ rows."""
from __future__ import annotations

from almabi_dashboard_builder import build_cost_structure_facts_from_pq_rows


def test_cost_tree_includes_large_davaltz_under_fot_without_direction():
    facts = build_cost_structure_facts_from_pq_rows(
        [
            {
                "Документ": "Отчет давальцу 00АМ-000003 от 31.03.2026 9:17:22",
                "Основной раздел": "Расходы",
                "Раздел": "ФОТ",
                "Сумма": 11_846_050.24,
                "Номенклатура": "Складской комплекс. Технологическое оборудование",
                "Направление": "ТХ",
                "Группа проектов": "ТХ-7",
                "Проект": "Проект",
            }
        ]
    )
    assert len(facts) == 1
    fact = facts[0]
    assert fact.cost_section == "ФОТ"
    assert fact.direction == ""
    assert fact.project_group == "Отчет давальцу"
    assert fact.amount_buh == -11_846_050.24


def test_cost_tree_excludes_black_metal_scrap():
    facts = build_cost_structure_facts_from_pq_rows(
        [
            {
                "Документ": "Реализация товаров и услуг 00АМ-000001 от 31.03.2026 21:00:00",
                "Основной раздел": "Расходы",
                "Раздел": "Материальные затраты",
                "Номенклатура": "Лом черных металлов. Лом черных м/л 12А (кг)",
                "Сумма": 45_626.0,
            },
            {
                "Документ": "Реализация товаров и услуг 00АМ-000002 от 31.03.2026 21:00:00",
                "Основной раздел": "Расходы",
                "Раздел": "Материальные затраты",
                "Номенклатура": "Алюминиевая стружка Лом цветных металлов.(кг)",
                "Сумма": 53_550.0,
            },
        ]
    )
    assert len(facts) == 1
    assert "цветных" in facts[0].nomenclature.casefold()


def test_cost_tree_skips_invalid_cost_section_name():
    facts = build_cost_structure_facts_from_pq_rows(
        [
            {
                "Документ": "Реализация товаров и услуг 00АМ-000001 от 31.03.2026 21:00:00",
                "Основной раздел": "Расходы",
                "Раздел": "Себестоимость",
                "Сумма": 100.0,
            }
        ]
    )
    assert facts == []
