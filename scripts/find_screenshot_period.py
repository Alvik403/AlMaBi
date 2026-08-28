from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from almabi_dashboard_builder import _build_summary_rows
from almabi_export_parsers import parse_exports
from almabi_pipeline import run_pipeline
from almabi_test_pipeline import build_test_facts

TARGETS = {
    "Выручка": 46_719_878.72,
    "Себестоимость": -40_442_360.16,
    "Коммерческие расходы": -315_338.84,
    "Управленческие расходы": -73_147_369.93,
    "Операционная прибыль": -67_185_190.21,
}
COMPONENTS = list(TARGETS.keys())[:-1]
NU = "Факт НУ"
BU = "Факт БУ"


def scan(label: str, facts) -> None:
    rows = {row["name"]: row for row in _build_summary_rows(facts)}
    op = rows["Операционная прибыль"]
    for month in rows["Выручка"]["values"][NU]:
        for scenario in (NU, BU):
            vals = {name: float(rows[name]["values"][scenario].get(month, 0) or 0) for name in COMPONENTS}
            op_value = float(op["values"][scenario].get(month, 0) or 0)
            comp_sum = sum(vals.values())
            matches = sum(1 for name in COMPONENTS if abs(vals[name] - TARGETS[name]) < 1.0)
            if matches >= 3 or abs(op_value - TARGETS["Операционная прибыль"]) < 1.0:
                print(f"{label} {month} {scenario}: matches={matches}/4")
                for name in COMPONENTS:
                    print(f"  {name}: {vals[name]:,.2f} target {TARGETS[name]:,.2f}")
                print(f"  op={op_value:,.2f} target={TARGETS['Операционная прибыль']:,.2f} comp_sum={comp_sum:,.2f} delta={op_value-comp_sum:,.2f}")
    # year totals
    for scenario in (NU, BU):
        vals = {name: sum(float(rows[name]["values"][scenario].get(m, 0) or 0) for m in rows[name]["values"][scenario]) for name in COMPONENTS}
        op_value = sum(float(op["values"][scenario].get(m, 0) or 0) for m in op["values"][scenario])
        matches = sum(1 for name in COMPONENTS if abs(vals[name] - TARGETS[name]) < 1000.0)
        if matches >= 2:
            print(f"{label} YEAR {scenario}: matches={matches}/4")
            for name in COMPONENTS:
                print(f"  {name}: {vals[name]:,.2f}")
            print(f"  op={op_value:,.2f} comp_sum={sum(vals.values()):,.2f}")


downloads = Path.home() / "Downloads"
bundles = [
    ("v1-main", run_pipeline, {
        "buh": downloads / "Выгрузка - бух.регистр (1).xlsx",
        "cost": downloads / "Апрель себестоимость (1).xlsx",
        "realization": downloads / "Выгрузка - Реализации проекты (1).xlsx",
    }),
    ("v2-main", run_pipeline, {
        "buh": downloads / "Выгрузка - бух.регистр (2).xlsx",
        "cost": downloads / "Выгрузка - себестоимость (1).xlsx",
        "realization": downloads / "Выгрузка - Реализации проекты (2).xlsx",
    }),
]

for label, runner, paths in bundles:
    if not all(p.exists() for p in paths.values()):
        continue
    if runner is run_pipeline:
        scan(label, runner(paths).facts)
    else:
        scan(label, build_test_facts(parse_exports(paths)).facts)

# also test pipeline for v2
paths = bundles[1][2]
scan("v2-test", build_test_facts(parse_exports(paths)).facts)
