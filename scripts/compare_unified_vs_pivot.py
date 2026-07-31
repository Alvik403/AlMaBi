"""Compare unified (hybrid) sections vs user pivot screenshots Jan-Jun."""
from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from almabi_dashboard_builder import COST_STRUCTURE_SECTIONS, build_unified_cost_structure_facts
from almabi_export_parsers import classify_cost_section_pq
from almabi_mock_data import MONTHS
from almabi_pq_common import is_black_metal_scrap_nomenclature
from almabi_test_pipeline import run_test_pipeline

# Pivot totals from user screenshots (buh регл. учёт)
PIVOT_TOTAL = {
    "Январь": 40_442_360.16,
    "Февраль": 52_919_986.22,
    "Март": 233_552_972.07,
    "Апрель": 13_960_811_516.05,
    "Май": 15_973_246_787.68,
    "Июнь": 723_601_869.11,
}

# Key pivot-derived section expectations (buh calc articles → BI sections)
PIVOT_SECTIONS = {
    "Январь": {
        "ФОТ": 15_991_186.39,
        "Материальные затраты": 18_654_880.30,
        "Общепроизводственные затраты": 1_357_752.27,
        "Прочие производственные расходы": 4_072_331.42,
        "Амортизация": 366_209.78,
    },
    "Февраль": {
        "ФОТ": 24_900_734.68,
        "Материальные затраты": 19_525_750.66,
        "Общепроизводственные затраты": 2_599_982.92,
        "Прочие производственные расходы": 5_436_460.20,
        "Амортизация": 457_057.76,
    },
    "Март": {
        "ФОТ": 35_735_569.03,
        "Материальные затраты": 188_537_518.23,
        "Общепроизводственные затраты": 4_425_347.44,
        "Прочие производственные расходы": 4_419_998.02,
        "Амортизация": 431_444.29,
        "Аренда (прямые)": 3_095.06,
    },
    "Апрель": {
        "ФОТ": 104_547_207.84,
        "Материальные затраты": 278_323_345.68,
        "Общепроизводственные затраты": 13_559_931_226.60,
        "Прочие производственные расходы": 10_713_583.75,
        "Амортизация": 7_204_318.32,
        "Аренда (прямые)": 88_337.28,
    },
    "Май": {
        "ФОТ": 108_495_739.46,
        "Материальные затраты": 1_326_340_207.02,
        "Общепроизводственные затраты": 14_497_682_585.92,
        "Прочие производственные расходы": 15_243_818.67,
        "Амортизация": 20_996_408.89,
        "Аренда (прямые)": 4_488_027.73,
    },
    "Июнь": {
        "ФОТ": 59_194_341.89,
        "Материальные затраты": 647_894_817.50,
        "Общепроизводственные затраты": 3_614_435.29,
        "Прочие производственные расходы": 6_328_397.44,
        "Амортизация": 4_753_260.24,
        "Аренда (прямые)": 1_816_616.75,
    },
}


def _latest(prefix: str) -> Path:
    return sorted(Path("uploads/almabi").glob(f"{prefix}-*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True)[0]


def _money(v: float) -> str:
    return f"{abs(v):,.2f}".replace(",", " ")


def _sec_sum(facts, month: str, section: str) -> float:
    return sum(f.amount_buh for f in facts if f.month == month and f.cost_section == section)


def _buh_pivot_sections(buh_facts, month: str) -> dict[str, float]:
    from almabi_dashboard_builder import _map_buh_cost_section

    totals: dict[str, float] = {}
    for fact in buh_facts:
        if fact.month != month:
            continue
        section = _map_buh_cost_section(fact)
        totals[section] = totals.get(section, 0.0) + fact.amount_buh
    return totals


def main() -> None:
    paths = {"buh": _latest("buh"), "cost": _latest("cost"), "realization": _latest("realization")}
    pipeline = run_test_pipeline(paths, logs_dir=None, write_audit=False)
    pq = pipeline.pq_cost_rows or []
    buh = [
        f
        for f in pipeline.result.facts
        if f.kpi_l1 == "Себестоимость" and not is_black_metal_scrap_nomenclature(f.nomenclature)
    ]
    unified = build_unified_cost_structure_facts(buh, pq)

    print("=== Hybrid unified vs pivot (скрины) ===\n")
    print(f"{'Месяц':<8} {'L1 BI':>18} {'Pivot total':>18} {'Δ total':>12}")
    for month in MONTHS:
        l1 = sum(f.amount_buh for f in buh if f.month == month)
        if abs(l1) < 0.01:
            continue
        pivot_t = PIVOT_TOTAL.get(month, 0)
        print(f"{month:<8} {_money(l1):>18} {_money(pivot_t):>18} {l1 - (-pivot_t) if pivot_t else 0:>12,.2f}")

    print("\n=== Статьи: unified vs buh-pivot mapping ===\n")
    for month in MONTHS:
        l1 = sum(f.amount_buh for f in buh if f.month == month)
        if abs(l1) < 0.01:
            continue
        buh_secs = _buh_pivot_sections(buh, month)
        expected = PIVOT_SECTIONS.get(month, {})
        print(f"--- {month} ---")
        print(f"{'Статья':<35} {'Unified':>16} {'Buh map':>16} {'Pivot ref':>16} {'Δ uni-ref':>12}")
        all_secs = list(COST_STRUCTURE_SECTIONS)
        for section in all_secs:
            uni = _sec_sum(unified, month, section)
            bm = buh_secs.get(section, 0.0)
            ref = -expected.get(section, 0.0) if section in expected else 0.0
            if abs(uni) < 0.01 and abs(bm) < 0.01 and abs(ref) < 0.01:
                continue
            delta = uni - ref if ref else uni - bm
            print(f"{section:<35} {_money(uni):>16} {_money(bm):>16} {_money(ref):>16} {delta:>12,.2f}")
        uni_sum = sum(_sec_sum(unified, month, s) for s in COST_STRUCTURE_SECTIONS)
        print(f"{'Σ статей':<35} {_money(uni_sum):>16} {_money(l1):>16} {'':>16} {uni_sum - l1:>12,.2f}\n")


if __name__ == "__main__":
    main()
