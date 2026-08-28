from __future__ import annotations

import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from almabi_dashboard_builder import load_almabi_dashboard_from_exports
from almabi_excel_utils import tax_bucket
from almabi_pipeline import run_pipeline
from almabi_test_builder import load_test_dashboard_from_exports

MONTH = "Март"
REF = {
    "Прочие доходы": {
        "total": 131_578_005.87,
        "priv": 2_047_897.23,
        "non": 129_530_108.64,
    },
    "Прочие расходы": {
        "total": 2_511_699_405.38,
        "priv": 2_383_391_876.05,
        "non": 128_307_529.33,
    },
}
SCREENSHOT = {
    "Прочие доходы": {"priv": 736_420.78, "non": 130_841_585.09},
    "Прочие расходы": {"priv": 2_383_319_449.41, "non": 128_385_591.32},
}

paths = {
    "buh": Path.home() / "Downloads" / "Выгрузка - бух.регистр (2).xlsx",
    "cost": Path.home() / "Downloads" / "Выгрузка - себестоимость (1).xlsx",
    "realization": Path.home() / "Downloads" / "Выгрузка - Реализации проекты (2).xlsx",
}
upload_names = {k: p.name for k, p in paths.items()}

result = run_pipeline(paths)
dashboard_main = load_almabi_dashboard_from_exports(paths, upload_names=upload_names)
dashboard_test = load_test_dashboard_from_exports(
    paths,
    upload_names=upload_names,
    logs_dir=Path(__file__).resolve().parent.parent / "logs",
)

# Pipeline facts (March)
print("=== Pipeline facts (Март) ===")
for kpi in ("Прочие доходы", "Прочие расходы"):
    rows = [f for f in result.facts if f.kpi_l1 == kpi and f.month == "Март"]
    priv_bu = sum(f.amount_buh for f in rows if tax_bucket(f.tax_type) == "Льготные проекты")
    non_bu = sum(f.amount_buh for f in rows if tax_bucket(f.tax_type) == "Нельготные проекты")
    total_bu = sum(f.amount_buh for f in rows)
    print(f"{kpi}: total BU {total_bu:,.2f}")
    print(f"  priv BU {priv_bu:,.2f}  non BU {non_bu:,.2f}")

def month_fact_bu(row: dict) -> float | None:
    values = row.get("values") or {}
    scenario = values.get("Факт БУ") or {}
    val = scenario.get(MONTH)
    return None if val is None else float(val)


def print_dashboard(label: str, dashboard: dict) -> None:
    print(f"\n=== {label} (Март, Факт БУ) ===")
    for row in dashboard["summary_rows"]:
        name = row["name"]
        if name not in REF:
            continue
        parent = month_fact_bu(row)
        print(f"\n{name} parent: UI abs {abs(parent or 0):,.2f}")
        for child in row.get("children") or []:
            cname = child["name"]
            if cname not in ("Льготные проекты", "Нельготные проекты"):
                continue
            cbu = month_fact_bu(child)
            key = "priv" if cname == "Льготные проекты" else "non"
            ref_val = REF[name][key]
            shot = SCREENSHOT[name][key]
            print(f"  {cname}: UI abs {abs(cbu or 0):,.2f}  ref {ref_val:,.2f}  screenshot {shot:,.2f}")


print_dashboard("Main pipeline dashboard", dashboard_main)
print_dashboard("Test BI dashboard (app path)", dashboard_test)

dashboard = dashboard_test

# Write compact debug for logs
log_path = Path(__file__).resolve().parent.parent / "debug-a10d6d.log"
payload = {"sessionId": "a10d6d", "runId": "display-check", "hypothesisId": "H-display-path", "location": "scripts/check_dashboard_march_display.py", "message": "March dashboard vs facts", "data": {}, "timestamp": __import__("time").time() * 1000}
for row in dashboard["summary_rows"]:
    if row["name"] not in REF:
        continue
    kpi = row["name"]
    payload["data"][kpi] = {"parent": month_fact_bu(row)}
    for child in row.get("children") or []:
        if child["name"] in ("Льготные проекты", "Нельготные проекты"):
            payload["data"][kpi][child["name"]] = month_fact_bu(child)
with log_path.open("a", encoding="utf-8") as f:
    f.write(json.dumps(payload, ensure_ascii=False) + "\n")

print(f"\nDebug log appended to {log_path}")
