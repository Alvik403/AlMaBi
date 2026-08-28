"""Разбивка расхождения BI vs этalon по апрелю/маю."""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from almabi_export_parsers import parse_exports
from almabi_pipeline import _build_cost_nu_exact_pool, _consume_cost_nu_exact, _dedupe_cost_nu_rows
from almabi_test_pipeline import run_test_pipeline


def _latest(prefix: str) -> Path:
    return sorted((ROOT / "uploads" / "almabi").glob(f"{prefix}*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True)[0]


def analyze_month(facts, deduped, month: str) -> dict:
    pool = _build_cost_nu_exact_pool(deduped)
    consumed: set[int] = set()
    cost = [f for f in facts if f.kpi_l1 == "Себестоимость" and f.month == month]

    unmatched_buh = 0.0
    matched_nu = 0.0
    zero_nu_with_buh = 0.0
    unmatched_samples = []

    for fact in cost:
        raw = _consume_cost_nu_exact(
            pool, deduped, consumed,
            document=fact.document,
            nomenclature=fact.nomenclature,
            account=fact.cost_account,
            calc_article=fact.expense_article,
        )
        buh_abs = abs(float(fact.amount_buh or 0))
        nu_abs = abs(float(fact.amount_nu or 0))
        if raw is None:
            unmatched_buh += buh_abs
            if nu_abs < 0.01 and buh_abs > 0.01:
                zero_nu_with_buh += buh_abs
                if len(unmatched_samples) < 5:
                    unmatched_samples.append({
                        "buh": fact.amount_buh,
                        "document": fact.document[:60],
                        "nomenclature": (fact.nomenclature or "")[:40],
                        "account": fact.cost_account,
                        "article": fact.expense_article,
                    })
        else:
            matched_nu += abs(float(raw))

    orphan_nu = 0.0
    for i, row in enumerate(deduped):
        if i not in consumed and row.month == month:
            orphan_nu += float(row.amount_nu or 0)

    bi_total = sum(abs(float(f.amount_nu or 0)) for f in cost)
    return {
        "facts": len(cost),
        "bi_total_abs": bi_total,
        "unmatched_buh_abs": unmatched_buh,
        "zero_nu_with_buh_abs": zero_nu_with_buh,
        "matched_from_pool_abs": matched_nu,
        "orphan_nu_file_abs": abs(orphan_nu),
        "unmatched_samples": unmatched_samples,
    }


def main() -> None:
    paths = {k: _latest(k + "-") for k in ("buh", "cost", "realization", "cost_nu")}
    exports = parse_exports(paths)
    facts = run_test_pipeline(paths).result.facts
    deduped = _dedupe_cost_nu_rows(exports.cost_nu)

    for month in ("Апрель", "Май"):
        print(month, analyze_month(facts, deduped, month))


if __name__ == "__main__":
    main()
