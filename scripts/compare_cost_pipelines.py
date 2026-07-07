from __future__ import annotations

from pathlib import Path

from almabi_cost_report import build_cost_report
from almabi_export_parsers import parse_exports
from almabi_pq_buh_register import build_pq_buh_register_table
from almabi_test_pipeline import build_test_facts


def compare(label: str, buh: Path, cost: Path, rev: Path) -> None:
    paths = {"buh": buh, "cost": cost, "realization": rev}
    pq = build_pq_buh_register_table(
        buh,
        cost_path=cost,
        revenue_path=rev,
        projects_path=rev,
    )
    pq_cost = [row for row in pq if row.get("Раздел") == "Себестоимость"]
    pq_sum = sum(float(row.get("Сумма БУ") or 0) for row in pq_cost)

    facts = build_test_facts(
        parse_exports(paths),
        cost_path=cost,
        projects_path=rev,
    ).facts
    test_cost = [fact for fact in facts if fact.kpi_l1 == "Себестоимость"]
    test_sum = sum(fact.amount_buh for fact in test_cost)

    report = build_cost_report(
        buh_path=buh,
        cost_path=cost,
        revenue_path=rev,
        projects_path=rev,
    )
    report_rows = report.get("rows", [])
    report_sum = sum(float(row.get("Сумма БУ") or 0) for row in report_rows)

    print(f"=== {label} ===")
    print(f"PQ rows={len(pq_cost)} sum={pq_sum:,.2f}")
    print(f"Test facts={len(test_cost)} sum={test_sum:,.2f}")
    print(f"Report rows={len(report_rows)} sum={report_sum:,.2f}")
    print()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Compare cost totals across PQ, Test BI, and report.")
    parser.add_argument("--label", required=True)
    parser.add_argument("--buh", type=Path, required=True)
    parser.add_argument("--cost", type=Path, required=True)
    parser.add_argument("--revenue", type=Path, required=True)
    args = parser.parse_args()
    compare(args.label, args.buh, args.cost, args.revenue)
