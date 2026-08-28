"""Analyze buh quality warnings and audit duplicates."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from almabi_export_parsers import classify_buh_section, parse_exports
from almabi_test_pipeline import run_test_pipeline


def _export_paths() -> dict[str, Path]:
    uploads = ROOT / "uploads" / "almabi"
    paths: dict[str, Path] = {}
    for export_type, prefix in (
        ("buh", "buh-"),
        ("realization", "realization-"),
        ("cost", "cost-"),
    ):
        matches = sorted(uploads.glob(f"{prefix}*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True)
        if matches:
            paths[export_type] = matches[0]
    cost_nu = Path(r"c:\Users\Flirp\Downloads\Выгрузка - Себестоимость НУ.xlsx")
    if cost_nu.exists():
        paths["cost_nu"] = cost_nu
    return paths


def main() -> None:
    paths = _export_paths()
    exports = parse_exports(paths)
    pipeline = run_test_pipeline(paths, logs_dir=ROOT / "logs")
    audit = pipeline.audit
    facts = pipeline.result.facts

    print("=== LARGE BUH ROWS (>= 1B) ===")
    for row in exports.buh:
        if not row.month or row.amount_buh < 1_000_000_000:
            continue
        section = classify_buh_section(row.account_dt, row.account_kt)
        same_doc_month = sum(
            1 for candidate in exports.buh if candidate.document == row.document and candidate.month == row.month
        )
        print(
            f"{row.month} | {section} | rows_same_doc_month={same_doc_month} | "
            f"amount={row.amount_buh:,.2f} | {row.document[:70]}"
        )

    print("\n=== AUDIT SUMMARY ===")
    print(json.dumps(audit.to_dict()["summary"], ensure_ascii=False, indent=2))

    print("\n=== TOP 10 DUPLICATE FACT GROUPS ===")
    for item in sorted(audit.duplicate_facts, key=lambda entry: -entry["count"])[:10]:
        fp = item["fingerprint"]
        nom = str(fp.get("nomenclature") or "")[:45]
        print(
            f"count={item['count']} | {fp['kpi_l1']} | {fp['month']} | "
            f"amount={fp['amount_buh']:,.2f} | nom={nom}"
        )

    print("\n=== CROSS-SECTION OVERLAPS ===")
    for item in audit.cross_section_overlaps:
        print(json.dumps(item, ensure_ascii=False, default=str))

    by_kpi: dict[str, int] = {}
    for item in audit.duplicate_facts:
        kpi = item["fingerprint"]["kpi_l1"]
        by_kpi[kpi] = by_kpi.get(kpi, 0) + 1
    print("\n=== DUPLICATE GROUPS BY KPI ===")
    for kpi, count in sorted(by_kpi.items(), key=lambda pair: -pair[1]):
        print(f"{kpi}: {count}")

    for month in ("Апрель", "Май"):
        rev = sum(f.amount_buh for f in facts if f.kpi_l1 == "Выручка" and f.month == month)
        cost = sum(f.amount_buh for f in facts if f.kpi_l1 == "Себестоимость" and f.month == month)
        print(f"\n{month} fact totals: revenue={rev:,.2f}, cost={cost:,.2f}")


if __name__ == "__main__":
    main()
