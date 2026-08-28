from __future__ import annotations

import json
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from almabi_dashboard_builder import _build_summary_rows, _group_facts, _merge_signed_fact_groups
from almabi_excel_utils import tax_bucket
from almabi_export_parsers import parse_exports
from almabi_pipeline import Fact, run_pipeline
from almabi_test_pipeline import TestPipelineResult, build_test_facts
from almabi_test_builder import build_test_dashboard_from_pipeline
from almabi_pipeline_audit import PipelineAuditLog

LOG_PATH = Path(__file__).resolve().parent.parent / "debug-a10d6d.log"
TARGET_REV_NU = 46_719_878.72
TARGET_OP_NU = -67_185_190.21
TARGET_USER_SUM = -67_165_190.21
COMPONENTS = ["Выручка", "Себестоимость", "Коммерческие расходы", "Управленческие расходы"]
NU = "Факт НУ"


def log(message: str, data: dict, hypothesis_id: str = "20k-gap") -> None:
    payload = {
        "sessionId": "a10d6d",
        "runId": "find-20k",
        "hypothesisId": hypothesis_id,
        "location": "scripts/find_20k_gap.py",
        "message": message,
        "data": data,
        "timestamp": int(time.time() * 1000),
    }
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def analyze_facts(facts: list[Fact], label: str) -> None:
    rows = {row["name"]: row for row in _build_summary_rows(facts)}
    op = rows["Операционная прибыль"]

    for month in rows["Выручка"]["values"][NU]:
        revenue = float(rows["Выручка"]["values"][NU].get(month, 0) or 0)
        if abs(revenue - TARGET_REV_NU) > 5000 and abs(float(op["values"][NU].get(month, 0) or 0) - TARGET_OP_NU) > 5000:
            continue

        vals = {name: float(rows[name]["values"][NU].get(month, 0) or 0) for name in COMPONENTS}
        op_value = float(op["values"][NU].get(month, 0) or 0)
        comp_sum = sum(vals.values())
        delta = op_value - comp_sum

        child_breakdown = {
            child["name"]: float(child["values"][NU].get(month, 0) or 0)
            for child in op.get("children", [])
        }

        print(f"\n=== {label} / {month} ===")
        for name in COMPONENTS:
            row = rows[name]
            child_sum = sum(float(ch["values"][NU].get(month, 0) or 0) for ch in row.get("children", []))
            print(f"  {name}: row={vals[name]:,.2f} children_sum={child_sum:,.2f}")
        print(f"  operating={op_value:,.2f} comp_sum={comp_sum:,.2f} delta={delta:,.2f}")
        print(f"  operating children: {child_breakdown}")
        print(f"  user-style sum with exact screenshot nums: {TARGET_REV_NU - 40442360.16 - 315338.84 - 73147369.93:,.2f}")
        print(f"  user reported sum: {TARGET_USER_SUM:,.2f}")

        log(
            "matched period summary",
            {
                "label": label,
                "month": month,
                "vals": vals,
                "op_value": op_value,
                "comp_sum": comp_sum,
                "delta": delta,
                "child_breakdown": child_breakdown,
            },
        )

        # Compare KPI facts vs operating merged facts by tax bucket
        operating_facts = _merge_signed_fact_groups(
            [
                (_group_facts(facts, kpi_l1="Выручка"), 1),
                (_group_facts(facts, kpi_l1="Себестоимость"), 1),
                (_group_facts(facts, kpi_l1="Коммерческие расходы"), 1),
                (_group_facts(facts, kpi_l1="Управленческие расходы"), 1),
            ]
        )
        month_facts = [fact for fact in operating_facts if fact.month == month]
        by_kpi: dict[str, float] = defaultdict(float)
        by_bucket: dict[str, float] = defaultdict(float)
        for fact in month_facts:
            by_kpi[fact.kpi_l1] += fact.amount_nu
            by_bucket[tax_bucket(fact.tax_type)] += fact.amount_nu
        print("  facts by kpi:", {k: round(v, 2) for k, v in by_kpi.items()})
        print("  facts by bucket:", {k: round(v, 2) for k, v in by_bucket.items()})

        # Find ~20k facts in admin/commercial
        suspects = []
        for fact in month_facts:
            if fact.kpi_l1 not in {"Коммерческие расходы", "Управленческие расходы"}:
                continue
            if abs(abs(fact.amount_nu) - 20_000) < 500 or abs(abs(fact.amount_buh) - 20_000) < 500:
                suspects.append(
                    {
                        "kpi": fact.kpi_l1,
                        "buh": fact.amount_buh,
                        "nu": fact.amount_nu,
                        "tax": fact.tax_type,
                        "article": fact.expense_article,
                        "contract": fact.contract,
                    }
                )
        if suspects:
            print("  ~20k expense facts:", suspects)
            log("20k suspect facts", {"suspects": suspects})

        # Check if displayed-style rounding could explain user sum
        rounded_manual = vals["Выручка"] - vals["Себестоимость"] - vals["Коммерческие расходы"] - vals["Управленческие расходы"]
        alt_comm = vals["Коммерческие расходы"] + 20_000
        alt_admin = vals["Управленческие расходы"] + 20_000
        print(f"  if comm 20k lower than row: {vals['Выручка'] - vals['Себестоимость'] - (vals['Коммерческие расходы'] - 20000) - vals['Управленческие расходы']:,.2f}")
        print(f"  if admin 20k lower than row: {vals['Выручка'] - vals['Себестоимость'] - vals['Коммерческие расходы'] - (vals['Управленческие расходы'] - 20000):,.2f}")


def try_paths(label: str, paths: dict[str, Path]) -> None:
    try:
        main = run_pipeline(paths)
        analyze_facts(main.facts, f"{label}/main")
    except Exception as exc:
        print(f"{label}/main failed: {exc}")
    try:
        test = build_test_facts(parse_exports(paths))
        analyze_facts(test.facts, f"{label}/test")
        dash = build_test_dashboard_from_pipeline(
            TestPipelineResult(result=test, audit=PipelineAuditLog()),
            upload_names={},
        )
        rows = {row["name"]: row for row in dash["summary_rows"]}
        op = rows["Операционная прибыль"]
        for month in rows["Выручка"]["values"][NU]:
            revenue = float(rows["Выручка"]["values"][NU].get(month, 0) or 0)
            if abs(revenue - TARGET_REV_NU) > 5000:
                continue
            vals = {name: float(rows[name]["values"][NU].get(month, 0) or 0) for name in COMPONENTS}
            op_value = float(op["values"][NU].get(month, 0) or 0)
            print(f"\n=== {label}/test-dashboard / {month} ===")
            print("  vals", {k: round(v, 2) for k, v in vals.items()})
            print(f"  op={op_value:,.2f} comp_sum={sum(vals.values()):,.2f}")
    except Exception as exc:
        print(f"{label}/test failed: {exc}")


def main() -> None:
    downloads = Path.home() / "Downloads"
    bundles = [
        ("v1", {
            "buh": downloads / "Выгрузка - бух.регистр (1).xlsx",
            "cost": downloads / "Апрель себестоимость (1).xlsx",
            "realization": downloads / "Выгрузка - Реализации проекты (1).xlsx",
        }),
        ("v2", {
            "buh": downloads / "Выгрузка - бух.регистр (2).xlsx",
            "cost": downloads / "Выгрузка - себестоимость (1).xlsx",
            "realization": downloads / "Выгрузка - Реализации проекты (2).xlsx",
        }),
    ]
    for label, paths in bundles:
        if all(path.exists() for path in paths.values()):
            try_paths(label, paths)
        else:
            missing = [str(p) for p in paths.values() if not p.exists()]
            print(f"{label} missing: {missing}")


if __name__ == "__main__":
    main()
