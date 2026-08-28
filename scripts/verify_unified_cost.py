"""Verify unified cost tree vs L1 after implementation."""
from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from almabi_dashboard_builder import COST_STRUCTURE_SECTIONS, build_unified_cost_structure_facts
from almabi_mock_data import MONTHS
from almabi_pq_common import is_black_metal_scrap_nomenclature
from almabi_pq_cost import build_pq_cost_table
from almabi_test_builder import load_almabi_dashboard_from_exports
from almabi_test_pipeline import run_test_pipeline


def _latest(prefix: str) -> Path:
    return sorted(Path("uploads/almabi").glob(f"{prefix}-*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True)[0]


def _money(v: float) -> str:
    return f"{abs(v):,.2f}".replace(",", " ")


def main() -> None:
    paths = {"buh": _latest("buh"), "cost": _latest("cost"), "realization": _latest("realization")}
    pipeline = run_test_pipeline(paths, logs_dir=None, write_audit=False)
    pq = pipeline.pq_cost_rows or build_pq_cost_table(paths["cost"], projects_path=paths["realization"])
    buh = [
        f
        for f in pipeline.result.facts
        if f.kpi_l1 == "Себестоимость" and not is_black_metal_scrap_nomenclature(f.nomenclature)
    ]
    unified = build_unified_cost_structure_facts(buh, pq)
    dashboard = load_almabi_dashboard_from_exports(
        paths, upload_names={k: v.name for k, v in paths.items()}, logs_dir=None
    )
    cost = next(r for r in dashboard["summary_rows"] if r["name"] == "Себестоимость")
    prochee = next((c for c in cost["children"] if c["name"] == "Прочее"), None)

    print("=== Гипотеза: unified(buh+PQ) = L1, gap=0, лом чёрн. исключён ===\n")
    print(f"{'Месяц':<10} {'L1 buh':>16} {'Unified':>16} {'Δ':>10} {'Gap UI':>10}")
    for month in MONTHS:
        l1 = float(cost["values"]["Факт БУ"].get(month, 0) or 0)
        u = sum(f.amount_buh for f in unified if f.month == month)
        gap = float(prochee["values"]["Факт БУ"].get(month, 0) or 0) if prochee else 0.0
        if abs(l1) < 0.01:
            continue
        print(f"{month:<10} {_money(l1):>16} {_money(u):>16} {l1-u:>10,.2f} {gap:>10,.2f}")

    print("\n=== Статьи (unified, без gap) — Март ===")
    month = "Март"
    for sec in COST_STRUCTURE_SECTIONS:
        val = sum(f.amount_buh for f in unified if f.month == month and f.cost_section == sec)
        if abs(val) > 0.005:
            print(f"  {sec}: {_money(val)}")

    print("\n=== Статьи — Июнь ===")
    month = "Июнь"
    for sec in COST_STRUCTURE_SECTIONS:
        val = sum(f.amount_buh for f in unified if f.month == month and f.cost_section == sec)
        if abs(val) > 0.005:
            print(f"  {sec}: {_money(val)}")

    print("\n=== Все месяцы: L1 = unified, gap=0, статьи ===")
    for month in MONTHS:
        l1 = float(cost["values"]["Факт БУ"].get(month, 0) or 0)
        if abs(l1) < 0.01:
            continue
        ut = sum(f.amount_buh for f in unified if f.month == month)
        gap = float(prochee["values"]["Факт БУ"].get(month, 0) or 0) if prochee else 0.0
        print(f"\n{month}: L1={_money(l1)} unified={_money(ut)} gap={gap:,.2f}")
        for sec in COST_STRUCTURE_SECTIONS:
            val = sum(f.amount_buh for f in unified if f.month == month and f.cost_section == sec)
            if abs(val) > 0.005:
                print(f"  {sec}: {_money(val)}")


if __name__ == "__main__":
    main()
