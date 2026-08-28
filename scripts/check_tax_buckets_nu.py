"""Сверка льготной/нельготной корзины по себестoимости НУ после 1:1."""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from almabi_test_builder import load_test_dashboard_from_exports
from almabi_excel_utils import MONTH_NAMES, tax_bucket
from almabi_export_parsers import parse_exports
from almabi_pipeline import (
    _apply_cost_nu_to_buh_facts,
    _build_cost_nu_exact_pool,
    _consume_cost_nu_exact,
    _dedupe_cost_nu_rows,
)
from almabi_test_pipeline import build_test_facts

LOG = ROOT / "debug-099d59.log"


def _latest(prefix: str) -> Path:
    uploads = ROOT / "uploads" / "almabi"
    matches = sorted(uploads.glob(f"{prefix}*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not matches:
        raise FileNotFoundError(prefix)
    return matches[0]


def _sum_by_bucket(facts, field: str, kpi: str | None = None) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    for fact in facts:
        if kpi and fact.kpi_l1 != kpi:
            continue
        totals[tax_bucket(fact.tax_type)] += float(getattr(fact, field) or 0)
    return dict(totals)


def _find_benefit_node(dashboard: dict, name: str) -> dict | None:
    for row in dashboard.get("summary_rows") or []:
        for child in row.get("children") or []:
            if child.get("name") == name:
                return child
    return None


def _month_total(node: dict | None, scenario: str) -> dict[str, float]:
    if not node:
        return {}
    values = (node.get("values") or {}).get(scenario) or {}
    return {month: float(values.get(month) or 0) for month in MONTH_NAMES.values()}


def main() -> None:
    paths = {
        "buh": _latest("buh-"),
        "cost": _latest("cost-"),
        "realization": _latest("realization-"),
        "cost_nu": _latest("cost_nu-"),
    }
    exports = parse_exports(paths)
    result = build_test_facts(exports)
    facts = result.facts

    cost_facts = [f for f in facts if f.kpi_l1 == "Себестоимость"]
    deduped = _dedupe_cost_nu_rows(exports.cost_nu)
    pool = _build_cost_nu_exact_pool(deduped)
    consumed: set[int] = set()
    unmatched_priv = 0.0
    unmatched_npriv = 0.0
    matched_priv = 0.0
    matched_npriv = 0.0
    for fact in cost_facts:
        bucket = tax_bucket(fact.tax_type)
        raw = _consume_cost_nu_exact(
            pool,
            deduped,
            consumed,
            document=fact.document,
            nomenclature=fact.nomenclature,
            account=fact.cost_account,
            calc_article=fact.expense_article,
        )
        buh = abs(float(fact.amount_buh or 0))
        if raw is None:
            if bucket == "Льготные проекты":
                unmatched_priv += buh
            else:
                unmatched_npriv += buh
        else:
            nu = abs(float(raw))
            if bucket == "Льготные проекты":
                matched_priv += nu
            else:
                matched_npriv += nu

    orphan_priv = 0.0
    orphan_npriv = 0.0
    doc_tax: dict[str, str] = {}
    for row in exports.buh:
        if row.document and row.tax_type:
            doc_tax[row.document] = row.tax_type
    for index, row in enumerate(deduped):
        if index in consumed:
            continue
        bucket = tax_bucket(doc_tax.get(row.document, "Общие условия налогообложения"))
        amount = abs(float(row.amount_nu or 0))
        if bucket == "Льготные проекты":
            orphan_priv += amount
        else:
            orphan_npriv += amount

    dashboard = load_test_dashboard_from_exports(paths, upload_names={k: v.name for k, v in paths.items()})
    priv_node = _find_benefit_node(dashboard, "Льготные проекты")
    npriv_node = _find_benefit_node(dashboard, "Нельготные проекты")

    cost_buh_bucket = _sum_by_bucket(cost_facts, "amount_buh")
    cost_nu_bucket = _sum_by_bucket(cost_facts, "amount_nu")
    all_buh_bucket = _sum_by_bucket(facts, "amount_buh")
    all_nu_bucket = _sum_by_bucket(facts, "amount_nu")

    april = "Апрель"
    data = {
        "paths": {k: str(v.name) for k, v in paths.items()},
        "cost_facts_count": len(cost_facts),
        "cost_nu_file_rows": len(exports.cost_nu),
        "cost_nu_deduped_rows": len(deduped),
        "match_stats_from_apply": None,
        "unmatched_buh_abs_by_bucket": {
            "Льготные проекты": unmatched_priv,
            "Нельготные проекты": unmatched_npriv,
        },
        "matched_nu_abs_by_bucket": {
            "Льготные проекты": matched_priv,
            "Нельготные проекты": matched_npriv,
        },
        "orphan_nu_abs_by_bucket_approx": {
            "Льготные проекты": orphan_priv,
            "Нельготные проекты": orphan_npriv,
        },
        "cost_buh_by_bucket_total": cost_buh_bucket,
        "cost_nu_by_bucket_total": cost_nu_bucket,
        "all_kpi_nu_by_bucket_total": all_nu_bucket,
        "april_benefit_nu": {
            "Льготные проекты": _month_total(priv_node, "Факт НУ").get(april, 0),
            "Нельготные проекты": _month_total(npriv_node, "Факт НУ").get(april, 0),
        },
        "april_cost_nu_by_bucket": {
            bucket: sum(
                abs(float(f.amount_nu or 0))
                for f in cost_facts
                if f.month == april and tax_bucket(f.tax_type) == bucket
            )
            for bucket in ("Льготные проекты", "Нельготные проекты")
        },
    }

    print(json.dumps(data, ensure_ascii=False, indent=2))
    payload = {
        "sessionId": "099d59",
        "runId": "tax-bucket-check",
        "hypothesisId": "H-priv",
        "location": "scripts/check_tax_buckets_nu.py",
        "message": "tax_bucket_nu_analysis",
        "data": data,
        "timestamp": __import__("time").time_ns() // 1_000_000,
    }
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
