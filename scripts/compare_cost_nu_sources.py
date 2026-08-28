"""Сверка факта НУ по себестоимости: бухрегистр vs выгрузка «Себестоимость НУ»."""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from almabi_excel_utils import MONTH_NAMES
from almabi_export_parsers import classify_buh_section, parse_cost_nu, parse_exports
from almabi_pipeline import _amount_nu_for_section
from almabi_test_pipeline import build_test_facts

DEBUG_LOG = ROOT / "debug-099d59.log"


def _export_paths(cost_nu_path: Path | None = None) -> dict[str, Path]:
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
    if cost_nu_path and cost_nu_path.exists():
        paths["cost_nu"] = cost_nu_path
    return paths


def _monthly_cost_nu_from_file(cost_nu_path: Path) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    for row in parse_cost_nu(cost_nu_path):
        if row.month:
            totals[row.month] += float(row.amount_nu or 0)
    return dict(totals)


def _monthly_old_nu(exports, facts_new) -> dict[str, float]:
    """НУ из бухрегистра (старая логика) по строкам себестоимости."""
    totals: dict[str, float] = defaultdict(float)
    for row in exports.buh:
        section = classify_buh_section(row.account_dt, row.account_kt)
        if section != "Себестоимость" or not row.month:
            continue
        totals[row.month] += _amount_nu_for_section(section, row.amount_nu_dt, row.amount_nu_kt)
    return dict(totals)


def _monthly_facts(facts, field: str) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    for fact in facts:
        if fact.kpi_l1 != "Себестоимость":
            continue
        totals[fact.month] += float(getattr(fact, field) or 0)
    return dict(totals)


def _log(message: str, data: dict, hypothesis_id: str = "H1") -> None:
    payload = {
        "sessionId": "099d59",
        "runId": "compare-cost-nu",
        "hypothesisId": hypothesis_id,
        "location": "scripts/compare_cost_nu_sources.py",
        "message": message,
        "data": data,
        "timestamp": __import__("time").time_ns() // 1_000_000,
    }
    with DEBUG_LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def main() -> None:
    cost_nu_arg = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
        r"c:\Users\Flirp\Downloads\Выгрузка - Себестоимость НУ.xlsx"
    )
    paths = _export_paths(cost_nu_arg if cost_nu_arg.exists() else None)
    missing = [key for key in ("buh", "realization", "cost") if key not in paths]
    if missing:
        print("Missing uploads:", ", ".join(missing))
        sys.exit(1)

    exports = parse_exports(paths)
    exports_no_nu = parse_exports({k: v for k, v in paths.items() if k != "cost_nu"})
    facts_with_nu = build_test_facts(exports).facts
    facts_without_nu = build_test_facts(exports_no_nu).facts

    file_totals = _monthly_cost_nu_from_file(paths["cost_nu"]) if "cost_nu" in paths else {}
    old_buh_totals = _monthly_old_nu(exports, facts_with_nu)
    new_fact_totals = _monthly_facts(facts_with_nu, "amount_nu")
    buh_fact_totals = _monthly_facts(facts_with_nu, "amount_buh")
    zero_without_file = _monthly_facts(facts_without_nu, "amount_nu")
    buh_fallback_hits = sum(
        1
        for fact in facts_with_nu
        if fact.kpi_l1 == "Себестоимость" and abs(fact.amount_nu - fact.amount_buh) < 0.01 and fact.amount_nu != 0
    )

    month_order = list(MONTH_NAMES.values())
    months = sorted(
        set(old_buh_totals) | set(new_fact_totals) | set(file_totals) | set(buh_fact_totals),
        key=month_order.index,
    )

    print(f"{'Month':<12} {'BU fact':>16} {'NU old':>16} {'NU new':>16} {'NU file':>16} {'d new-file':>16}")
    print("-" * 96)
    for month in months:
        buh = buh_fact_totals.get(month, 0.0)
        old = old_buh_totals.get(month, 0.0)
        new = new_fact_totals.get(month, 0.0)
        file_total = -file_totals.get(month, 0.0) if file_totals else 0.0
        delta = new - file_total if file_totals else 0.0
        print(
            f"{month:<12} {buh:>16,.0f} {old:>16,.0f} {new:>16,.0f} {file_total:>16,.0f} {delta:>16,.0f}"
        )

    _log(
        "cost_nu_comparison",
        {
            "paths": {k: str(v) for k, v in paths.items()},
            "months": months,
            "buh_fact_totals": buh_fact_totals,
            "old_buh_nu_totals": old_buh_totals,
            "new_fact_nu_totals": new_fact_totals,
            "file_nu_totals_negated": {m: -file_totals.get(m, 0) for m in months},
            "zero_nu_without_file": zero_without_file,
            "buh_fallback_hits": buh_fallback_hits,
            "parsed_cost_nu_rows": len(exports.cost_nu),
        },
    )


if __name__ == "__main__":
    main()
