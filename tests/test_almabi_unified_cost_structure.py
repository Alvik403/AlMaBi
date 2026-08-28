"""Unified cost structure: reconciles to buh L1, PQ detail, no PQ-only rows."""
from __future__ import annotations

from almabi_dashboard_builder import build_unified_cost_structure_facts
from almabi_pipeline import Fact


def test_unified_uses_pq_splits_when_nomenclature_and_amount_match():
    buh = [
        Fact(
            kpi_l1="Себестоимость",
            month="Март",
            amount_buh=-60.0,
            amount_nu=-60.0,
            nomenclature="Болт М12",
            direction="ТХ",
            expense_article="Сырье и материалы",
            cost_account="20",
        ),
        Fact(
            kpi_l1="Себестоимость",
            month="Март",
            amount_buh=-40.0,
            amount_nu=-40.0,
            nomenclature="Болт М12",
            direction="ТХ",
            expense_article="Оплата труда",
            cost_account="20",
        ),
    ]
    pq_rows = [
        {
            "Документ": "Реализация товаров и услуг 00АМ-000001 от 31.03.2026 21:00:00",
            "Основной раздел": "Расходы",
            "Раздел": "Материальные затраты",
            "Номенклатура": "Болт М12",
            "Сумма": 60.0,
            "Направление": "ТХ",
            "Группа проектов": "G",
            "Проект": "P",
        },
        {
            "Документ": "Реализация товаров и услуг 00АМ-000001 от 31.03.2026 21:00:00",
            "Основной раздел": "Расходы",
            "Раздел": "ФОТ",
            "Номенклатура": "Болт М12",
            "Сумма": 40.0,
            "Направление": "ТХ",
            "Группа проектов": "G",
            "Проект": "P",
        },
    ]
    facts = build_unified_cost_structure_facts(buh, pq_rows)
    assert sum(f.amount_buh for f in facts) == -100.0
    assert {f.cost_section for f in facts} == {"Материальные затраты", "ФОТ"}


def test_unified_skips_pq_only_colored_scrap():
    buh = [
        Fact(
            kpi_l1="Себестоимость",
            month="Июнь",
            amount_buh=-50.0,
            amount_nu=-50.0,
            nomenclature="Деталь",
        )
    ]
    pq_rows = [
        {
            "Документ": "Реализация товаров и услуг 00АМ-000001 от 30.06.2026 21:00:00",
            "Основной раздел": "Расходы",
            "Раздел": "Материальные затраты",
            "Номенклатура": "Деталь",
            "Сумма": 50.0,
        },
        {
            "Документ": "Реализация товаров и услуг 00АМ-000002 от 30.06.2026 21:00:00",
            "Основной раздел": "Расходы",
            "Раздел": "Материальные затраты",
            "Номенклатура": "Алюминиевая стружка Лом цветных металлов.(кг)",
            "Сумма": 53_550.0,
        },
    ]
    facts = build_unified_cost_structure_facts(buh, pq_rows)
    assert sum(f.amount_buh for f in facts) == -50.0
    assert all("цветн" not in (f.nomenclature or "").casefold() for f in facts)


def test_unified_adds_buh_only_prochee_line():
    buh = [
        Fact(
            kpi_l1="Себестоимость",
            month="Март",
            amount_buh=-29_256.80,
            amount_nu=-29_256.80,
            nomenclature="Прочее",
            expense_article="Материальные расходы (20)",
        )
    ]
    facts = build_unified_cost_structure_facts(buh, [])
    assert len(facts) == 1
    assert facts[0].cost_section == "Прочие производственные расходы"
    assert facts[0].amount_buh == -29_256.80


def test_unified_merges_oez_pq_splits_with_buh_total():
    buh = [
        Fact(
            kpi_l1="Себестоимость",
            month="Март",
            amount_buh=-9_682_162.54,
            amount_nu=-9_682_162.54,
            nomenclature="ОЭЗ Работы по техническому обслуживанию",
            direction="Услуги",
        )
    ]
    pq_rows = [
        {
            "Документ": "Реализация товаров и услуг 00АМ-000001 от 31.03.2026 21:00:00",
            "Основной раздел": "Расходы",
            "Раздел": "Общепроизводственные затраты",
            "Номенклатура": "ОЭЗ (ппу) Работы по техническому обслуживанию, ремонту ппу",
            "Сумма": 6_970_870.10,
            "Направление": "Услуги",
        },
        {
            "Документ": "Реализация товаров и услуг 00АМ-000002 от 31.03.2026 21:00:00",
            "Основной раздел": "Расходы",
            "Раздел": "Общепроизводственные затраты",
            "Номенклатура": "ОЭЗ Работы по техническому обслуживанию",
            "Сумма": 2_711_292.44,
            "Направление": "Услуги",
        },
    ]
    facts = build_unified_cost_structure_facts(buh, pq_rows)
    assert abs(sum(f.amount_buh for f in facts) + 9_682_162.54) < 0.05
    assert len(facts) == 2


def test_unified_distributes_buh_nu_across_pq_splits():
    buh = [
        Fact(
            kpi_l1="Себестоимость",
            month="Март",
            amount_buh=-100.0,
            amount_nu=-400.0,
            nomenclature="Болт М12",
            direction="ТХ",
        )
    ]
    pq_rows = [
        {
            "Документ": "Реализация товаров и услуг 00АМ-000001 от 31.03.2026 21:00:00",
            "Основной раздел": "Расходы",
            "Раздел": "Материальные затраты",
            "Номенклатура": "Болт М12",
            "Сумма": 60.0,
            "Направление": "ТХ",
            "Группа проектов": "G",
            "Проект": "P",
        },
        {
            "Документ": "Реализация товаров и услуг 00АМ-000001 от 31.03.2026 21:00:00",
            "Основной раздел": "Расходы",
            "Раздел": "ФОТ",
            "Номенклатура": "Болт М12",
            "Сумма": 40.0,
            "Направление": "ТХ",
            "Группа проектов": "G",
            "Проект": "P",
        },
    ]
    facts = build_unified_cost_structure_facts(buh, pq_rows)
    assert sum(f.amount_buh for f in facts) == -100.0
    assert sum(f.amount_nu for f in facts) == -400.0


def test_unified_keeps_source_nu_articles_separate_from_pq_buh_splits():
    """Вариант А: БУ следует PQ, НУ — счёту и статье исходного файла НУ."""
    buh = [
        Fact(
            kpi_l1="Себестоимость",
            month="Январь",
            amount_buh=-100.0,
            amount_nu=0.0,
            nomenclature="Работы",
            direction="Услуги",
        ),
        Fact(
            kpi_l1="Себестоимость",
            month="Январь",
            amount_buh=0.0,
            amount_nu=-80.0,
            nomenclature="Работы",
            direction="Услуги",
            cost_section="ФОТ",
            cost_account="20",
            expense_article="Оплата труда",
        ),
        Fact(
            kpi_l1="Себестоимость",
            month="Январь",
            amount_buh=0.0,
            amount_nu=10.0,
            nomenclature="Работы",
            direction="Услуги",
            cost_section="Прочие производственные расходы",
            cost_account="25",
            expense_article="Страховые взносы",
        ),
    ]
    pq_rows = [
        {
            "Документ": "Реализация товаров и услуг 001 от 31.01.2026",
            "Основной раздел": "Расходы",
            "Раздел": "Материальные затраты",
            "Номенклатура": "Работы",
            "Сумма": 60.0,
            "Направление": "Услуги",
        },
        {
            "Документ": "Реализация товаров и услуг 001 от 31.01.2026",
            "Основной раздел": "Расходы",
            "Раздел": "ФОТ",
            "Номенклатура": "Работы",
            "Сумма": 40.0,
            "Направление": "Услуги",
        },
    ]

    facts = build_unified_cost_structure_facts(buh, pq_rows)

    assert sum(f.amount_buh for f in facts) == -100.0
    assert sum(f.amount_nu for f in facts) == -70.0
    assert sum(f.amount_nu for f in facts if f.cost_section == "ФОТ") == -80.0
    assert (
        sum(f.amount_nu for f in facts if f.cost_section == "Прочие производственные расходы")
        == 10.0
    )
    assert sum(f.amount_nu for f in facts if f.cost_section == "Материальные затраты") == 0.0


def _sec_sum(facts, month: str, section: str) -> float:
    return sum(f.amount_buh for f in facts if f.month == month and f.cost_section == section)


def test_unified_uses_pq_splits_even_when_buh_section_tags_differ():
    """Статьи дерева = PQ (как pivot), если сумма buh совпала с PQ по номенклатуре."""
    buh = [
        Fact(
            kpi_l1="Себестоимость",
            month="Апрель",
            amount_buh=-1_000_000.0,
            amount_nu=-1_000_000.0,
            nomenclature="Комплект ЭПР",
            direction="ТХ",
            cost_section="ФОТ",
        )
    ]
    pq_rows = [
        {
            "Документ": "Реализация товаров и услуг 00АМ-000001 от 30.04.2026 21:00:00",
            "Основной раздел": "Расходы",
            "Раздел": "Материальные затраты",
            "Номенклатура": "Комплект ЭПР",
            "Сумма": 400_000.0,
            "Направление": "ТХ",
        },
        {
            "Документ": "Реализация товаров и услуг 00АМ-000001 от 30.04.2026 21:00:00",
            "Основной раздел": "Расходы",
            "Раздел": "Общепроизводственные затраты",
            "Номенклатура": "Комплект ЭПР",
            "Сумма": 600_000.0,
            "Направление": "ТХ",
        },
    ]
    facts = build_unified_cost_structure_facts(buh, pq_rows)
    assert sum(f.amount_buh for f in facts) == -1_000_000.0
    assert _sec_sum(facts, "Апрель", "Материальные затраты") == -400_000.0
    assert _sec_sum(facts, "Апрель", "Общепроизводственные затраты") == -600_000.0
    assert _sec_sum(facts, "Апрель", "ФОТ") == 0.0


def test_buh_only_pairs_pq_only_by_amount_and_uses_pq_sections():
    """buh-only и PQ-only с одной суммой, но разной номенклатурой → статьи из PQ."""
    buh = [
        Fact(
            kpi_l1="Себестоимость",
            month="Апрель",
            amount_buh=-6_037_576.36,
            amount_nu=-6_037_576.36,
            nomenclature="Пусковая установка длиной 36 метров",
            direction="Услуги",
        )
    ]
    pq_rows = [
        {
            "Документ": "Реализация товаров и услуг 00АМ-000077 от 30.04.2026 21:00:00",
            "Основной раздел": "Расходы",
            "Раздел": "ФОТ",
            "Номенклатура": "(ОЭЗ) Пуско-наладочные работы",
            "Сумма": 6_034_079.78,
            "Направление": "Услуги",
        },
        {
            "Документ": "Реализация товаров и услуг 00АМ-000077 от 30.04.2026 21:00:00",
            "Основной раздел": "Расходы",
            "Раздел": "Амортизация",
            "Номенклатура": "(ОЭЗ) Пуско-наладочные работы",
            "Сумма": 2_964.85,
            "Направление": "Услуги",
        },
        {
            "Документ": "Реализация товаров и услуг 00АМ-000077 от 30.04.2026 21:00:00",
            "Основной раздел": "Расходы",
            "Раздел": "Материальные затраты",
            "Номенклатура": "(ОЭЗ) Пуско-наладочные работы",
            "Сумма": 180.33,
            "Направление": "Услуги",
        },
        {
            "Документ": "Реализация товаров и услуг 00АМ-000077 от 30.04.2026 21:00:00",
            "Основной раздел": "Расходы",
            "Раздел": "Прочие производственные расходы",
            "Номенклатура": "(ОЭЗ) Пуско-наладочные работы",
            "Сумма": 351.40,
            "Направление": "Услуги",
        },
    ]
    facts = build_unified_cost_structure_facts(buh, pq_rows)
    assert abs(sum(f.amount_buh for f in facts) + 6_037_576.36) < 0.05
    assert abs(_sec_sum(facts, "Апрель", "ФОТ") + 6_034_079.78) < 1.0
    assert abs(_sec_sum(facts, "Апрель", "Общепроизводственные затраты")) < 0.01
    assert facts[0].nomenclature.startswith("Пусковая установка")


def test_buh_only_pairs_combined_pq_only_by_amount():
    """Несколько PQ-only строк = одна buh-only сумма → объединённая PQ-структура."""
    buh = [
        Fact(
            kpi_l1="Себестоимость",
            month="Июнь",
            amount_buh=-1_621_390.03,
            amount_nu=-1_621_390.03,
            nomenclature="Складской комплекс. Технологическое оборудование",
            direction="Производство",
        )
    ]
    pq_rows = [
        {
            "Документ": "Реализация товаров и услуг 00АМ-000001 от 30.06.2026 21:00:00",
            "Основной раздел": "Расходы",
            "Раздел": "ФОТ",
            "Номенклатура": "За выполненные строительно-монтажные работы",
            "Сумма": 1_577_538.33,
            "Направление": "Производство",
        },
        {
            "Документ": "Реализация товаров и услуг 00АМ-000002 от 30.06.2026 21:00:00",
            "Основной раздел": "Расходы",
            "Раздел": "ФОТ",
            "Номенклатура": "СМР Синергия",
            "Сумма": 43_851.70,
            "Направление": "Производство",
        },
    ]
    facts = build_unified_cost_structure_facts(buh, pq_rows)
    assert abs(sum(f.amount_buh for f in facts) + 1_621_390.03) < 0.05
    assert abs(_sec_sum(facts, "Июнь", "ФОТ") + 1_621_390.03) < 1.0
    assert abs(_sec_sum(facts, "Июнь", "Общепроизводственные затраты")) < 0.01
