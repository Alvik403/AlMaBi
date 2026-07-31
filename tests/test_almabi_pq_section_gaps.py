"""PQ vs unified section gaps: risks of PQ-only inclusion and FOT/OPZ/materials patterns.

Логику merge не меняем — только документируем расхождения тестами.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import pytest

from almabi_dashboard_builder import (
    _group_cost_structure_facts,
    build_cost_structure_facts_from_pq_rows,
    build_unified_cost_structure_facts,
)
from almabi_pq_common import is_black_metal_scrap_nomenclature
from almabi_pipeline import Fact
from almabi_test_pipeline import run_test_pipeline

SECTIONS = (
    "Амортизация",
    "ФОТ",
    "Общепроизводственные затраты",
    "Материальные затраты",
)

APRIL_PQ_ONLY_PNR_AMORT = 2_964.85
APRIL_PQ_AMORT = 7_207_283.17
APRIL_UNIFIED_AMORT = 7_204_318.32


def _sec_sum(facts, month: str, section: str) -> float:
    return sum(f.amount_buh for f in facts if f.month == month and f.cost_section == section)


def _pq_only_by_section(pq_groups, buh_groups, month: str) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    for key, items in pq_groups.items():
        if key[0] != month or key in buh_groups:
            continue
        for fact in items:
            if fact.cost_section in SECTIONS:
                totals[fact.cost_section] += fact.amount_buh
    return totals


def test_including_pq_only_amortization_would_break_l1_reconciliation():
    """PQ-only амортизация без buh увеличивает дерево, но не L1 → появится gap «Прочее»."""
    buh = [
        Fact(
            kpi_l1="Себестоимость",
            month="Апрель",
            amount_buh=-100.0,
            amount_nu=-100.0,
            nomenclature="Изделие А",
        )
    ]
    pq_rows = [
        {
            "Документ": "Реализация товаров и услуг 00АМ-000001 от 30.04.2026 21:00:00",
            "Основной раздел": "Расходы",
            "Раздел": "Материальные затраты",
            "Номенклатура": "Изделие А",
            "Сумма": 100.0,
        },
        {
            "Документ": "Реализация товаров и услуг 00АМ-000002 от 30.04.2026 21:00:00",
            "Основной раздел": "Расходы",
            "Раздел": "Амортизация",
            "Номенклатура": "(ОЭЗ) Пуско-наладочные работы",
            "Сумма": APRIL_PQ_ONLY_PNR_AMORT,
        },
    ]
    unified = build_unified_cost_structure_facts(buh, pq_rows)
    pq_facts = build_cost_structure_facts_from_pq_rows(pq_rows)

    l1 = sum(f.amount_buh for f in buh)
    structure = sum(f.amount_buh for f in unified)
    pq_amort = _sec_sum(pq_facts, "Апрель", "Амортизация")
    uni_amort = _sec_sum(unified, "Апрель", "Амортизация")

    assert structure == l1
    assert uni_amort == 0.0
    assert abs(pq_amort + APRIL_PQ_ONLY_PNR_AMORT) < 0.01

    # Гипотетическое включение PQ-only: структура > L1 на сумму PQ-only.
    hypothetical_structure = structure + pq_amort
    assert abs(hypothetical_structure - l1 + APRIL_PQ_ONLY_PNR_AMORT) < 0.01


def test_pq_only_pnr_splits_across_amort_fot_and_materials():
    """Один PQ-only документ ПНР ОЭЗ разнесён по нескольким статьям — частичное включение исказит картину."""
    pnr_rows = [
        {
            "Документ": "Реализация товаров и услуг 00АМ-000077 от 30.04.2026 21:00:00",
            "Основной раздел": "Расходы",
            "Раздел": "Амортизация",
            "Номенклатура": "(ОЭЗ) Пуско-наладочные работы",
            "Сумма": APRIL_PQ_ONLY_PNR_AMORT,
            "Направление": "Услуги",
        },
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
            "Раздел": "Материальные затраты",
            "Номенклатура": "(ОЭЗ) Пуско-наладочные работы",
            "Сумма": 180.33,
            "Направление": "Услуги",
        },
    ]
    pq_rows = [
        {
            "Документ": "Реализация товаров и услуг 00АМ-000001 от 30.04.2026 21:00:00",
            "Основной раздел": "Расходы",
            "Раздел": "Материальные затраты",
            "Номенклатура": "Другая позиция",
            "Сумма": 1.0,
        },
        *pnr_rows,
    ]
    buh_facts = [
        Fact(
            kpi_l1="Себестоимость",
            month="Апрель",
            amount_buh=-1.0,
            amount_nu=-1.0,
            nomenclature="Другая позиция",
        )
    ]
    unified = build_unified_cost_structure_facts(buh_facts, pq_rows)
    pq_facts = build_cost_structure_facts_from_pq_rows(pq_rows)
    pq_groups = _group_cost_structure_facts(pq_facts)
    buh_groups = _group_cost_structure_facts(buh_facts)
    pq_only = _pq_only_by_section(pq_groups, buh_groups, "Апрель")

    assert abs(pq_only["Амортизация"] + APRIL_PQ_ONLY_PNR_AMORT) < 0.01
    assert abs(pq_only["ФОТ"] + 6_034_079.78) < 0.01
    assert abs(pq_only["Материальные затраты"] + 180.33) < 0.01
    assert _sec_sum(unified, "Апрель", "Амортизация") == 0.0
    assert _sec_sum(unified, "Апрель", "ФОТ") == 0.0

    total_pq_only_pnr = APRIL_PQ_ONLY_PNR_AMORT + 6_034_079.78 + 180.33
    assert abs(sum(pq_only.values()) + total_pq_only_pnr) < 0.01


def test_section_mismatch_when_buh_and_pq_match_uses_pq_splits():
    """buh помечен как амортизация, PQ — аморт+ФОТ: дерево следует PQ (pivot)."""
    buh = [
        Fact(
            kpi_l1="Себестоимость",
            month="Апрель",
            amount_buh=-100.0,
            amount_nu=-100.0,
            nomenclature="Комплект замков тары (20.9801.050.00.00)",
            expense_article="Амортизация",
            cost_account="20",
            direction="Производство (Оснастка/стапеля)",
        )
    ]
    pq_rows = [
        {
            "Документ": "Реализация товаров и услуг 00АМ-000001 от 30.04.2026 21:00:00",
            "Основной раздел": "Расходы",
            "Раздел": "Амортизация",
            "Номенклатура": "Комплект замков тары (20.9801.050.00.00)",
            "Сумма": 10.0,
            "Направление": "Производство (Оснастка/стапеля)",
        },
        {
            "Документ": "Реализация товаров и услуг 00АМ-000001 от 30.04.2026 21:00:00",
            "Основной раздел": "Расходы",
            "Раздел": "ФОТ",
            "Номенклатура": "Комплект замков тары (20.9801.050.00.00)",
            "Сумма": 90.0,
            "Направление": "Производство (Оснастка/стапеля)",
        },
    ]
    unified = build_unified_cost_structure_facts(buh, pq_rows)
    assert _sec_sum(unified, "Апрель", "Амортизация") == -10.0
    assert _sec_sum(unified, "Апрель", "ФОТ") == -90.0
    assert sum(f.amount_buh for f in unified) == -100.0


def _export_paths() -> dict[str, Path] | None:
    uploads = Path("uploads/almabi")
    if not uploads.is_dir():
        return None
    paths = {}
    for prefix in ("buh", "cost", "realization"):
        matches = sorted(uploads.glob(f"{prefix}-*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not matches:
            return None
        paths[prefix] = matches[0]
    return paths


@pytest.fixture(scope="function")
def live_cost_pipeline():
    paths = _export_paths()
    if not paths:
        pytest.skip("uploads/almabi exports not available")
    return run_test_pipeline(paths, logs_dir=None, write_audit=False), paths


@pytest.fixture(scope="function")
def live_cost_facts(live_cost_pipeline):
    pipeline, _paths = live_cost_pipeline
    buh = [
        f
        for f in pipeline.result.facts
        if f.kpi_l1 == "Себестоимость" and not is_black_metal_scrap_nomenclature(f.nomenclature)
    ]
    pq = pipeline.pq_cost_rows or []
    unified = build_unified_cost_structure_facts(buh, pq)
    pq_facts = build_cost_structure_facts_from_pq_rows(pq)
    pq_groups = _group_cost_structure_facts(pq_facts)
    buh_groups = _group_cost_structure_facts(buh)
    return buh, unified, pq_facts, pq_groups, buh_groups


def test_live_fot_opz_match_pq_after_buh_only_pairing(live_cost_facts):
    """После buh-only↔PQ-only по сумме ФОТ/ОПZ unified = PQ (≈ pivot)."""
    _buh, unified, pq_facts, _pq_groups, _buh_groups = live_cost_facts
    for month in ("Апрель", "Май", "Июнь"):
        for section in ("ФОТ", "Общепроизводственные затраты"):
            pq_sec = _sec_sum(pq_facts, month, section)
            uni_sec = _sec_sum(unified, month, section)
            assert abs(uni_sec - pq_sec) < 2.0, f"{month} {section}"


def test_april_fot_matches_pq_after_buh_only_pairing(live_cost_facts):
    _buh, unified, pq_facts, _pq_groups, _buh_groups = live_cost_facts
    month = "Апрель"
    pq_fot = _sec_sum(pq_facts, month, "ФОТ")
    uni_fot = _sec_sum(unified, month, "ФОТ")
    assert abs(uni_fot - pq_fot) < 5000.0


def test_may_june_fot_matches_pq_after_buh_only_pairing(live_cost_facts):
    _buh, unified, pq_facts, _pq_groups, _buh_groups = live_cost_facts
    for month in ("Май", "Июнь"):
        pq_fot = _sec_sum(pq_facts, month, "ФОТ")
        uni_fot = _sec_sum(unified, month, "ФОТ")
        assert abs(uni_fot - pq_fot) < 1.0, month
