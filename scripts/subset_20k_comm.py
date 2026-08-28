from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from almabi_pipeline import run_pipeline

facts = run_pipeline(
    {
        "buh": Path.home() / "Downloads" / "Выгрузка - бух.регистр (2).xlsx",
        "cost": Path.home() / "Downloads" / "Выгрузка - себестоимость (1).xlsx",
        "realization": Path.home() / "Downloads" / "Выгрузка - Реализации проекты (2).xlsx",
    }
).facts

jan = [fact for fact in facts if fact.month == "Январь"]


def subset_sum(items: list, target: float, tol: float = 0.02):
    items = [(round(abs(f.amount_buh), 2), f) for f in items if f.amount_buh < 0]
    items.sort(key=lambda pair: pair[0], reverse=True)

    def dfs(index: int, remaining: float, picked: list) -> list | None:
        if abs(remaining) <= tol:
            return picked
        if index >= len(items) or remaining < -tol:
            return None
        amount, fact = items[index]
        with_pick = dfs(index + 1, remaining - amount, picked + [fact])
        if with_pick is not None:
            return with_pick
        return dfs(index + 1, remaining, picked)

    return dfs(0, target, [])


for kpi in ["Коммерческие расходы", "Управленческие расходы"]:
    rows = [fact for fact in jan if fact.kpi_l1 == kpi]
    match = subset_sum(rows, 20_000)
    print(f"\n=== {kpi}: BU subset = 20,000 ===")
    if not match:
        print("  no exact subset found")
        continue
    total = sum(abs(f.amount_buh) for f in match)
    print(f"  picked {len(match)} lines, total={total:,.2f}")
    for fact in match:
        print(f"    BU={fact.amount_buh:,.2f} NU={fact.amount_nu:,.2f} article={fact.expense_article!r}")

# show all comm lines - maybe user excluded NU-only line when mixing
print("\n=== All January commercial facts ===")
for fact in sorted(jan, key=lambda f: f.amount_buh):
    if fact.kpi_l1 != "Коммерческие расходы":
        continue
    print(f"BU={fact.amount_buh:10.2f} NU={fact.amount_nu:10.2f} article={(fact.expense_article or '')[:50]!r}")

print("\ncomm without NU-only line (BU=0, NU!=0):")
nu_only = [f for f in jan if f.kpi_l1 == "Коммерческие расходы" and f.amount_buh == 0 and f.amount_nu != 0]
print("count", len(nu_only), "NU sum", sum(f.amount_nu for f in nu_only))
for f in nu_only:
    print(f"  NU={f.amount_nu:,.2f} article={f.expense_article!r}")
