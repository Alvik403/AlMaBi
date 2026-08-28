"""PQ vs unified section gaps — amortization, FOT, OPZ, materials."""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from almabi_dashboard_builder import (
    COST_STRUCTURE_SECTIONS,
    _group_cost_structure_facts,
    _map_buh_cost_section,
    build_cost_structure_facts_from_pq_rows,
    build_unified_cost_structure_facts,
)
from almabi_mock_data import MONTHS
from almabi_pq_common import is_black_metal_scrap_nomenclature
from almabi_test_pipeline import run_test_pipeline

SECTIONS = (
    "Амортизация",
    "ФОТ",
    "Общепроизводственные затраты",
    "Материальные затраты",
)


def _latest(prefix: str) -> Path:
    return sorted(Path("uploads/almabi").glob(f"{prefix}-*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True)[0]


def _sec_sum(facts, month: str, section: str) -> float:
    return sum(f.amount_buh for f in facts if f.month == month and f.cost_section == section)


def main() -> None:
    paths = {"buh": _latest("buh"), "cost": _latest("cost"), "realization": _latest("realization")}
    pipeline = run_test_pipeline(paths, logs_dir=None, write_audit=False)
    pq = pipeline.pq_cost_rows or []
    cost_buh = [
        f
        for f in pipeline.result.facts
        if f.kpi_l1 == "Себестоимость" and not is_black_metal_scrap_nomenclature(f.nomenclature)
    ]
    unified = build_unified_cost_structure_facts(cost_buh, pq)
    pq_facts = build_cost_structure_facts_from_pq_rows(pq)
    pq_groups = _group_cost_structure_facts(pq_facts)
    buh_groups = _group_cost_structure_facts(cost_buh)

    print("=" * 90)
    print("АПРЕЛЬ: PQ vs Unified по статьям")
    print("=" * 90)
    month = "Апрель"
    l1 = sum(f.amount_buh for f in cost_buh if f.month == month)
    print(f"L1 buh: {abs(l1):,.2f}\n")
    print(f"{'Статья':<35} {'PQ':>16} {'Unified':>16} {'PQ-Uni':>12} {'PQ-only':>12}")
    pq_only_by_sec: dict[str, float] = defaultdict(float)
    pq_only_items: dict[str, list[tuple[str, float, str]]] = defaultdict(list)
    for key, items in pq_groups.items():
        if key[0] != month or key in buh_groups:
            continue
        for fact in items:
            if fact.cost_section not in SECTIONS:
                continue
            pq_only_by_sec[fact.cost_section] += fact.amount_buh
            pq_only_items[fact.cost_section].append((fact.nomenclature or "—", fact.amount_buh, fact.direction or ""))

    for section in SECTIONS:
        pq_val = _sec_sum(pq_facts, month, section)
        uni_val = _sec_sum(unified, month, section)
        pq_only = pq_only_by_sec[section]
        print(
            f"{section:<35} {abs(pq_val):>16,.2f} {abs(uni_val):>16,.2f} "
            f"{abs(pq_val - uni_val):>12,.2f} {abs(pq_only):>12,.2f}"
        )

    for section in SECTIONS:
        if not pq_only_items[section]:
            continue
        print(f"\n--- PQ-only {section}: {abs(pq_only_by_sec[section]):,.2f} ---")
        for nom, amt, direction in sorted(pq_only_items[section], key=lambda x: abs(x[1]), reverse=True):
            print(f"  {amt:>12,.2f} | {direction} | {nom[:75]}")

    unified_total = sum(f.amount_buh for f in unified if f.month == month)
    pq_only_total = sum(pq_only_by_sec.values())
    print("\n=== Риск: Unified + PQ-only (апрель, только 4 статьи) ===")
    print(f"L1 buh:               {l1:>18,.2f}")
    print(f"Unified сейчас:       {unified_total:>18,.2f}")
    print(f"PQ-only (4 статьи):   {pq_only_total:>18,.2f}")
    print(f"Unified + PQ-only:    {unified_total + pq_only_total:>18,.2f}")
    print(f"Разрыв с L1 (delta):  {l1 - (unified_total + pq_only_total):>18,.2f}")

    print("\n" + "=" * 90)
    print("ВСЕ МЕСЯЦЫ: |PQ - Unified| и PQ-only по 4 статьям")
    print("=" * 90)
    for month in MONTHS:
        l1m = sum(f.amount_buh for f in cost_buh if f.month == month)
        if abs(l1m) < 0.01:
            continue
        pq_only_m = 0.0
        for key, items in pq_groups.items():
            if key[0] != month or key in buh_groups:
                continue
            pq_only_m += sum(f.amount_buh for f in items if f.cost_section in SECTIONS)
        diffs = []
        for section in SECTIONS:
            d = _sec_sum(pq_facts, month, section) - _sec_sum(unified, month, section)
            if abs(d) > 0.5:
                short = section.split()[0][:4]
                diffs.append(f"{short}={abs(d):,.0f}")
        diff_txt = " | ".join(diffs) if diffs else "—"
        print(f"{month:<8} PQ-only={abs(pq_only_m):>12,.0f}  section_gaps: {diff_txt}")

    print("\n" + "=" * 90)
    print("Причина gap != PQ-only: section mismatch при buh+PQ match (PQ wins section split)")
    print("=" * 90)
    for month in ("Апрель", "Март", "Июнь"):
        l1m = sum(f.amount_buh for f in cost_buh if f.month == month)
        if abs(l1m) < 0.01:
            continue
        print(f"\n{month}:")
        for section in SECTIONS:
            pq_val = _sec_sum(pq_facts, month, section)
            uni_val = _sec_sum(unified, month, section)
            gap = pq_val - uni_val
            pq_only = pq_only_by_sec if month == "Апрель" else None
            if month != "Апрель":
                pq_only_sec = 0.0
                for key, items in pq_groups.items():
                    if key[0] != month or key in buh_groups:
                        continue
                    pq_only_sec += sum(
                        f.amount_buh for f in items if f.cost_section == section
                    )
            else:
                pq_only_sec = pq_only_by_sec[section]
            reclass = gap - pq_only_sec  # rest is reclassification buh vs PQ section split
            if abs(gap) > 0.5:
                print(
                    f"  {section}: gap={abs(gap):,.2f}  из них PQ-only={abs(pq_only_sec):,.2f}  "
                    f"переклассификация={abs(reclass):,.2f}"
                )


if __name__ == "__main__":
    main()
