from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from almabi_dashboard_builder import _build_summary_rows
from almabi_export_parsers import parse_exports
from almabi_pipeline import run_pipeline

paths = {
    "buh": Path.home() / "Downloads" / "Выгрузка - бух.регистр (2).xlsx",
    "cost": Path.home() / "Downloads" / "Выгрузка - себестоимость (1).xlsx",
    "realization": Path.home() / "Downloads" / "Выгрузка - Реализации проекты (2).xlsx",
}
rows = {row["name"]: row for row in _build_summary_rows(run_pipeline(paths).facts)}
comps = ["Выручка", "Себестоимость", "Коммерческие расходы", "Управленческие расходы"]
op = rows["Операционная прибыль"]
month = "Январь"

for scenario in ("Факт БУ", "Факт НУ"):
    vals = {name: float(rows[name]["values"][scenario][month]) for name in comps}
    op_value = float(op["values"][scenario][month])
    child_sum = sum(float(ch["values"][scenario][month]) for ch in op["children"])
    print(scenario, "components", vals)
    print("  sum", sum(vals.values()), "op", op_value, "children", child_sum, "delta", op_value - sum(vals.values()))
