"""Детальная сверка НУ по себестоимости для экономиста."""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from almabi_excel_utils import MONTH_NAMES, document_match_keys, normalize_text
from almabi_export_parsers import classify_buh_section, parse_cost_nu, parse_exports
from almabi_pipeline import CostNuAllocator, _amount_nu_for_section
from almabi_pq_common import nomenclature_key
from almabi_test_builder import load_test_dashboard_from_exports
from almabi_test_pipeline import build_test_facts, run_test_pipeline

DEBUG_LOG = ROOT / "debug-099d59.log"


def _paths() -> dict[str, Path]:
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


def _monthly_old_buh_nu(exports) -> dict[str, float]:
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


def _file_by_month_doc_nu(cost_nu_path: Path) -> dict[tuple[str, str, str], float]:
    grouped: dict[tuple[str, str, str], float] = defaultdict(float)
    for row in parse_cost_nu(cost_nu_path):
        if not row.month:
            continue
        doc = normalize_text(row.document)
        nom = nomenclature_key(row.nomenclature)
        grouped[(row.month, doc, nom)] += float(row.amount_nu or 0)
    return dict(grouped)


def _facts_by_month_doc_nu(facts) -> dict[tuple[str, str, str], float]:
    grouped: dict[tuple[str, str, str], float] = defaultdict(float)
    for fact in facts:
        if fact.kpi_l1 != "Себестоимость":
            continue
        doc = normalize_text(fact.contract or "")
        if not doc:
            continue
        nom = nomenclature_key(fact.nomenclature)
        grouped[(fact.month, doc, nom)] += -float(fact.amount_nu or 0)
    return dict(grouped)


def _log(message: str, data: dict) -> None:
    payload = {
        "sessionId": "099d59",
        "runId": "economist-reconcile",
        "hypothesisId": "reconcile",
        "location": "scripts/reconcile_cost_nu_for_economist.py",
        "message": message,
        "data": data,
        "timestamp": __import__("time").time_ns() // 1_000_000,
    }
    with DEBUG_LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def main() -> None:
    paths = _paths()
    if "cost_nu" not in paths:
        print("ERROR: cost_nu file missing")
        sys.exit(1)

    exports = parse_exports(paths)
    facts = build_test_facts(exports).facts
    dash = load_test_dashboard_from_exports(paths, upload_names={k: f"{k}.xlsx" for k in paths})
    cost_row = next(r for r in dash["summary_rows"] if r["name"] == "Себестоимость")

    file_raw: dict[str, float] = defaultdict(float)
    for row in parse_cost_nu(paths["cost_nu"]):
        if row.month:
            file_raw[row.month] += float(row.amount_nu or 0)

    old_buh = _monthly_old_buh_nu(exports)
    nu_facts = _monthly_facts(facts, "amount_nu")
    bu_facts = _monthly_facts(facts, "amount_buh")

    orphan_nu = _monthly_facts(
        [f for f in facts if f.kpi_l1 == "Себестоимость" and abs(f.amount_buh) < 0.005],
        "amount_nu",
    )
    matched_nu = _monthly_facts(
        [f for f in facts if f.kpi_l1 == "Себестоимость" and abs(f.amount_buh) >= 0.005],
        "amount_nu",
    )

    month_order = list(MONTH_NAMES.values())
    months = sorted(set(file_raw) | set(nu_facts) | set(old_buh), key=month_order.index)

    print("=" * 110)
    print("СВЕРКА НУ ПО СЕБЕСТОИМОСТИ (источники)")
    print("=" * 110)
    print(
        f"{'Месяц':<10} {'NU файл':>18} {'NU pipeline':>18} {'NU dash':>18} "
        f"{'NU buh-reg':>18} {'Δ pipe-file':>14} {'Δ dash-pipe':>12}"
    )
    print("-" * 110)

    summary_rows = []
    for month in months:
        file_neg = -file_raw.get(month, 0.0)
        pipe = nu_facts.get(month, 0.0)
        dash_nu = float(cost_row["values"]["Факт НУ"].get(month, 0) or 0)
        old = old_buh.get(month, 0.0)
        d_pf = pipe - file_neg
        d_dp = dash_nu - pipe
        print(
            f"{month:<10} {file_neg:>18,.2f} {pipe:>18,.2f} {dash_nu:>18,.2f} "
            f"{old:>18,.2f} {d_pf:>14,.2f} {d_dp:>12,.2f}"
        )
        summary_rows.append(
            {
                "month": month,
                "file_nu": file_neg,
                "pipeline_nu": pipe,
                "dashboard_nu": dash_nu,
                "old_buh_nu": old,
                "delta_pipe_file": d_pf,
                "delta_dash_pipe": d_dp,
                "orphan_nu": orphan_nu.get(month, 0.0),
                "matched_nu": matched_nu.get(month, 0.0),
            }
        )

    # April drill-down
    focus = "Апрель"
    print("\n" + "=" * 110)
    print(f"ДЕТАЛИЗАЦИЯ РАСХОЖДЕНИЯ: {focus}")
    print("=" * 110)

    file_map = _file_by_month_doc_nu(paths["cost_nu"])
    fact_map = _facts_by_month_doc_nu(facts)

    deltas: list[tuple[float, str, str, float, float]] = []
    keys = set(file_map) | set(fact_map)
    for key in keys:
        month, doc, nom = key
        if month != focus:
            continue
        file_val = file_map.get(key, 0.0)
        fact_val = fact_map.get(key, 0.0)
        delta = fact_val - file_val
        if abs(delta) > 1000:
            deltas.append((delta, doc, nom, file_val, fact_val))

    deltas.sort(key=lambda item: -abs(item[0]))
    print(f"{'Δ (pipe-file)':>16} {'NU файл':>16} {'NU pipe':>16}  документ / номенклатура")
    print("-" * 110)
    for delta, doc, nom, file_val, fact_val in deltas[:25]:
        print(f"{delta:>16,.2f} {file_val:>16,.2f} {fact_val:>16,.2f}  {doc[:45]} | {nom[:35]}")

    # Unmatched file rows (not consumed)
    allocator = CostNuAllocator.from_rows(exports.cost_nu)
    build_test_facts(exports)
    unconsumed = []
    for index, row in enumerate(exports.cost_nu):
        if index in allocator._consumed:
            continue
        amount = float(row.amount_nu or 0)
        if amount <= 0 or row.month != focus:
            continue
        unconsumed.append((amount, row.document, row.nomenclature))
    unconsumed.sort(key=lambda x: -x[0])

    print(f"\nСтроки файла НУ за {focus} без пары в buh (orphan, top 15):")
    orphan_total = 0.0
    for amount, doc, nom in unconsumed[:15]:
        orphan_total += amount
        print(f"  {amount:>14,.2f}  {doc[:50]} | {nom[:40]}")
    print(f"  ... всего orphan-строк: {len(unconsumed)}, сумма: {sum(a for a,_,_ in unconsumed):,.2f}")

    print(f"\nOrphan NU в фактах за {focus}: {orphan_nu.get(focus, 0):,.2f}")
    print(f"Matched NU в фактах за {focus}: {matched_nu.get(focus, 0):,.2f}")

    _log(
        "economist_reconciliation",
        {
            "paths": {k: str(v) for k, v in paths.items()},
            "monthly": summary_rows,
            "april_top_deltas": [
                {"delta": d, "doc": doc, "nom": nom, "file": fv, "pipe": pv}
                for d, doc, nom, fv, pv in deltas[:20]
            ],
            "april_orphan_count": len(unconsumed),
            "april_orphan_file_sum": sum(a for a, _, _ in unconsumed),
        },
    )


if __name__ == "__main__":
    main()
