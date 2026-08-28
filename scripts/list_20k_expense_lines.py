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

jan_comm = [fact for fact in facts if fact.month == "Январь" and fact.kpi_l1 == "Коммерческие расходы"]
jan_admin = [fact for fact in facts if fact.month == "Январь" and fact.kpi_l1 == "Управленческие расходы"]

print("comm BU total", sum(fact.amount_buh for fact in jan_comm))
print("admin BU total", sum(fact.amount_buh for fact in jan_admin))
print()

for title, rows in ("COMM", jan_comm), ("ADMIN", jan_admin):
    print(f"=== {title}: lines with |BU| between 15k and 25k ===")
    for fact in sorted(rows, key=lambda item: item.amount_buh):
        if 15_000 <= abs(fact.amount_buh) <= 25_000 or abs(abs(fact.amount_buh) - 20_000) <= 100:
            article = (fact.expense_article or "")[:80]
            print(f"  BU={fact.amount_buh:,.2f} NU={fact.amount_nu:,.2f} article={article!r}")

print()
print("If user omitted comm BU lines summing to 20,000:")
target = 20_000
negatives = [fact for fact in jan_comm if fact.amount_buh < 0]
# single line
for fact in negatives:
    if abs(abs(fact.amount_buh) - target) < 0.02:
        print(f"  exact single line: BU={fact.amount_buh:,.2f} article={fact.expense_article!r}")

# check admin single 20k
for fact in jan_admin:
    if abs(abs(fact.amount_buh) - target) < 0.02:
        print(f"  exact admin line: BU={fact.amount_buh:,.2f} article={fact.expense_article!r}")
