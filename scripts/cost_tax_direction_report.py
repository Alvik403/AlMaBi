"""Report: cost by tax bucket + direction per month (unified structure)."""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from almabi_dashboard_builder import build_unified_cost_structure_facts
from almabi_excel_utils import tax_bucket
from almabi_mock_data import MONTHS
from almabi_pq_common import is_black_metal_scrap_nomenclature
from almabi_test_builder import filter_facts_by_tax_bucket, load_almabi_dashboard_from_exports
from almabi_test_pipeline import run_test_pipeline

TAX_BUCKETS = ("Льготные проекты", "Нельготные проекты")


def _latest(prefix: str) -> Path:
    return sorted(Path("uploads/almabi").glob(f"{prefix}-*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True)[0]


def _money(v: float) -> str:
    return f"{abs(v):,.2f}".replace(",", " ")


def _direction_label(fact) -> str:
    d = (fact.direction or "").strip()
    return d if d else "Без направления"


def main() -> None:
    paths = {"buh": _latest("buh"), "cost": _latest("cost"), "realization": _latest("realization")}
    pipeline = run_test_pipeline(paths, logs_dir=None, write_audit=False)
    pq = pipeline.pq_cost_rows or []
    all_facts = pipeline.result.facts
    cost_buh = [
        f
        for f in all_facts
        if f.kpi_l1 == "Себестоимость" and not is_black_metal_scrap_nomenclature(f.nomenclature)
    ]
    unified = build_unified_cost_structure_facts(cost_buh, pq)

    dashboard = load_almabi_dashboard_from_exports(
        paths, upload_names={k: v.name for k, v in paths.items()}, logs_dir=None
    )
    summary_by_tax = dashboard.get("summary_by_tax") or {}

    print("=" * 80)
    print("1. ЛЬГОТНЫЕ / НЕЛЬГОТНЫЕ / ОБЩЕЕ (Факт БУ, L1 «Себестоимость» из buh)")
    print("=" * 80)
    print(f"{'Месяц':<10} {'Льготные':>18} {'Нельготные':>18} {'Общее':>18} {'Л+Н':>18} {'Δ':>8}")
    grand = {b: 0.0 for b in TAX_BUCKETS}
    grand_all = 0.0
    for month in MONTHS:
        priv = sum(f.amount_buh for f in cost_buh if f.month == month and tax_bucket(f.tax_type) == TAX_BUCKETS[0])
        nonp = sum(f.amount_buh for f in cost_buh if f.month == month and tax_bucket(f.tax_type) == TAX_BUCKETS[1])
        total = sum(f.amount_buh for f in cost_buh if f.month == month)
        if abs(total) < 0.01:
            continue
        grand[TAX_BUCKETS[0]] += priv
        grand[TAX_BUCKETS[1]] += nonp
        grand_all += total
        print(
            f"{month:<10} {_money(priv):>18} {_money(nonp):>18} {_money(total):>18} "
            f"{_money(priv + nonp):>18} {total - (priv + nonp):>8.2f}"
        )
    print(
        f"{'ИТОГО':<10} {_money(grand[TAX_BUCKETS[0]]):>18} {_money(grand[TAX_BUCKETS[1]]):>18} "
        f"{_money(grand_all):>18} {_money(grand[TAX_BUCKETS[0]] + grand[TAX_BUCKETS[1]]):>18} "
        f"{grand_all - (grand[TAX_BUCKETS[0]] + grand[TAX_BUCKETS[1]]):>8.2f}"
    )

    print("\n" + "=" * 80)
    print("2. СВЕРКА с дашбордом (summary_by_tax L1)")
    print("=" * 80)
    for bucket in TAX_BUCKETS:
        rows = summary_by_tax.get(bucket, [])
        cost_node = next((r for r in rows if r["name"] == "Себестоимость"), None)
        if not cost_node:
            print(f"{bucket}: нет данных")
            continue
        dash_total = sum(cost_node["values"]["Факт БУ"].values())
        buh_total = sum(
            f.amount_buh
            for f in filter_facts_by_tax_bucket(cost_buh, bucket)
        )
        print(f"{bucket}: buh={_money(buh_total)} dashboard={_money(dash_total)} Δ={buh_total - dash_total:.2f}")

    all_rows = summary_by_tax.get("all", dashboard.get("summary_rows", []))
    cost_all = next(r for r in all_rows if r["name"] == "Себестоимость")
    print(
        f"Общее: buh={_money(grand_all)} dashboard={_money(sum(cost_all['values']['Факт БУ'].values()))} "
        f"Δ={grand_all - sum(cost_all['values']['Факт БУ'].values()):.2f}"
    )

    print("\n" + "=" * 80)
    print("3. РАСПРЕДЕЛЕНИЕ ПО НАПРАВЛЕНИЯМ (unified structure, Факт БУ)")
    print("=" * 80)
    for month in MONTHS:
        month_facts = [f for f in unified if f.month == month]
        l1 = sum(f.amount_buh for f in cost_buh if f.month == month)
        if abs(l1) < 0.01:
            continue
        by_dir: dict[str, float] = defaultdict(float)
        for f in month_facts:
            by_dir[_direction_label(f)] += f.amount_buh
        dir_sum = sum(by_dir.values())
        gap = l1 - dir_sum
        print(f"\n--- {month} | L1={_money(l1)} | Σ направлений={_money(dir_sum)} | Δ={gap:.2f} ---")
        for direction, amount in sorted(by_dir.items(), key=lambda x: abs(x[1]), reverse=True):
            pct = abs(amount) / abs(l1) * 100 if l1 else 0
            print(f"  {direction:<40} {_money(amount):>18}  ({pct:5.1f}%)")

    print("\n" + "=" * 80)
    print("4. ЛЬГОТНЫЕ: направления по месяцам (buh facts, без PQ merge)")
    print("=" * 80)
    priv_facts = [f for f in cost_buh if tax_bucket(f.tax_type) == TAX_BUCKETS[0]]
    for month in MONTHS:
        mf = [f for f in priv_facts if f.month == month]
        if not mf:
            continue
        total = sum(f.amount_buh for f in mf)
        by_dir: dict[str, float] = defaultdict(float)
        for f in mf:
            by_dir[_direction_label(f)] += f.amount_buh
        print(f"\n--- {month} | ИТОГО={_money(total)} ---")
        for direction, amount in sorted(by_dir.items(), key=lambda x: abs(x[1]), reverse=True):
            print(f"  {direction:<40} {_money(amount):>18}")

    print("\n" + "=" * 80)
    print("5. НЕЛЬГОТНЫЕ: направления по месяцам (buh facts)")
    print("=" * 80)
    nonp_facts = [f for f in cost_buh if tax_bucket(f.tax_type) == TAX_BUCKETS[1]]
    for month in MONTHS:
        mf = [f for f in nonp_facts if f.month == month]
        if not mf:
            continue
        total = sum(f.amount_buh for f in mf)
        by_dir: dict[str, float] = defaultdict(float)
        for f in mf:
            by_dir[_direction_label(f)] += f.amount_buh
        print(f"\n--- {month} | ИТОГО={_money(total)} ---")
        for direction, amount in sorted(by_dir.items(), key=lambda x: abs(x[1]), reverse=True):
            print(f"  {direction:<40} {_money(amount):>18}")

    print("\n" + "=" * 80)
    print("6. tax_type breakdown (top types per bucket, all months)")
    print("=" * 80)
    for bucket in TAX_BUCKETS:
        by_type: dict[str, float] = defaultdict(float)
        for f in cost_buh:
            if tax_bucket(f.tax_type) == bucket:
                by_type[f.tax_type or "(пусто)"] += f.amount_buh
        print(f"\n{bucket}:")
        for tt, amount in sorted(by_type.items(), key=lambda x: abs(x[1]), reverse=True)[:15]:
            print(f"  {tt[:60]:<60} {_money(amount):>18}")


if __name__ == "__main__":
    main()
