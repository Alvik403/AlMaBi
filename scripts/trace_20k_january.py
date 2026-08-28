from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from almabi_export_parsers import parse_exports
from almabi_pipeline import run_pipeline

LOG = Path(__file__).resolve().parent.parent / "debug-a10d6d.log"
paths = {
    "buh": Path.home() / "Downloads" / "Выгрузка - бух.регистр (2).xlsx",
    "cost": Path.home() / "Downloads" / "Выгрузка - себестоимость (1).xlsx",
    "realization": Path.home() / "Downloads" / "Выгрузка - Реализации проекты (2).xlsx",
}
facts = run_pipeline(paths).facts
jan = [f for f in facts if f.month == "Январь"]

print("=== January v2: BU vs NU component diffs ===")
for kpi in ["Выручка", "Себестоимость", "Коммерческие расходы", "Управленческие расходы"]:
    rows = [f for f in jan if f.kpi_l1 == kpi]
    bu = sum(f.amount_buh for f in rows)
    nu = sum(f.amount_nu for f in rows)
    print(f"{kpi}: BU={bu:,.2f} NU={nu:,.2f} NU-BU={nu-bu:,.2f}")

print("\nBU operating check:", 46719878.72 - 40442360.16 - 315338.84 - 73147369.93)
print("NU operating check:", 46719878.72 - 37154611.79 - 123808.58 - 79848285.42)
print("User sum target:", -67165190.21)
print("Gap vs BU operating:", -67185190.21 - (-67165190.21))

for kpi in ["Коммерческие расходы", "Управленческие расходы"]:
    print(f"\n=== {kpi}: BU facts near 20,000 ===")
    rows = sorted(
        [f for f in jan if f.kpi_l1 == kpi],
        key=lambda f: abs(f.amount_buh),
        reverse=True,
    )
    total = 0.0
    for fact in rows:
        total += fact.amount_buh
        if abs(abs(fact.amount_buh) - 20_000) <= 5000 or abs(abs(fact.amount_nu) - 20_000) <= 5000:
            print(
                f"  BU={fact.amount_buh:,.2f} NU={fact.amount_nu:,.2f} "
                f"article={fact.expense_article!r} tax={fact.tax_type!r} contract={fact.contract!r}"
            )
    # subset that sums to 20000 BU
    target = 20_000
    rows_bu = [f for f in rows if f.amount_buh]
    for fact in rows_bu:
        if abs(abs(fact.amount_buh) - target) < 0.01:
            print(f"EXACT 20k line: BU={fact.amount_buh} NU={fact.amount_nu} article={fact.expense_article} tax={fact.tax_type}")
    # greedy subset search for 20k sum
    candidates = [(abs(f.amount_buh), f) for f in rows_bu if f.amount_buh < 0]
    candidates.sort(reverse=True)
    acc = 0.0
    picked = []
    for amount, fact in candidates:
        if acc + amount <= target + 0.01:
            picked.append(fact)
            acc += amount
            if abs(acc - target) < 0.02:
                print(f"Subset summing to ~20k BU ({acc:,.2f}):")
                for p in picked:
                    print(
                        f"  BU={p.amount_buh:,.2f} NU={p.amount_nu:,.2f} "
                        f"article={p.expense_article!r} tax={p.tax_type!r}"
                    )
                break

payload = {
    "sessionId": "a10d6d",
    "runId": "find-20k",
    "hypothesisId": "bu-nu-mix",
    "location": "scripts/trace_20k_january.py",
    "message": "January v2 BU/NU breakdown",
    "data": {
        "bu_operating": -67185190.21,
        "nu_operating": -70406827.07,
        "user_manual_sum": -67165190.21,
        "gap_bu_vs_user": -20000.0,
        "screenshot_matches_scenario": "Факт БУ",
        "screenshot_month": "Январь",
    },
    "timestamp": int(time.time() * 1000),
}
with LOG.open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
