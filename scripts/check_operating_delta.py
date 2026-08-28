from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from almabi_dashboard_builder import _build_summary_rows
from almabi_export_parsers import parse_exports
from almabi_pipeline import run_pipeline

paths = {
    "buh": Path.home() / "Downloads" / "Выгрузка - бух.регистр (1).xlsx",
    "cost": Path.home() / "Downloads" / "Апрель себестоимость (1).xlsx",
    "realization": Path.home() / "Downloads" / "Выгрузка - Реализации проекты (1).xlsx",
}
result = run_pipeline(paths)
rows = {row["name"]: row for row in _build_summary_rows(result.facts)}
comps = ["Выручка", "Себестоимость", "Коммерческие расходы", "Управленческие расходы"]
op = rows["Операционная прибыль"]
NU = "Факт НУ"


def check_period(label: str, months: list[str]) -> None:
    vals = {
        name: sum(float(rows[name]["values"][NU].get(month, 0) or 0) for month in months)
        for name in comps
    }
    op_value = sum(float(op["values"][NU].get(month, 0) or 0) for month in months)
    comp_sum = sum(vals.values())
    admin = rows["Управленческие расходы"]
    admin_children = sum(
        sum(float(child["values"][NU].get(month, 0) or 0) for month in months)
        for child in admin.get("children", [])
    )
    print(label)
    for name in comps:
        print(f"  {name}: {vals[name]:,.2f}")
    print(f"  SUM: {comp_sum:,.2f}  OP: {op_value:,.2f}  delta: {op_value - comp_sum:,.2f}")
    print(f"  admin row vs children: {vals['Управленческие расходы']:,.2f} vs {admin_children:,.2f}")
    print(
        "  manual if admin -20k:",
        f"{vals['Выручка'] - vals['Себестоимость'] - vals['Коммерческие расходы'] - (vals['Управленческие расходы'] - 20000):,.2f}",
    )


months = list(rows["Выручка"]["values"][NU].keys())
check_period("YEAR", months)
for month in months:
    revenue = float(rows["Выручка"]["values"][NU].get(month, 0) or 0)
    if revenue <= 0:
        continue
    op_value = float(op["values"][NU].get(month, 0) or 0)
    if abs(op_value + 67_185_190.21) < 50_000 or abs(revenue - 46_719_878.72) < 1_000:
        check_period(f"MONTH {month}", [month])
