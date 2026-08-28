"""Почему строки НУ из файла не сопоставляются с фактами БУ (апрель)."""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from almabi_excel_utils import document_match_keys
from almabi_export_parsers import parse_exports
from almabi_pipeline import (
    _build_cost_nu_exact_pool,
    _consume_cost_nu_exact,
    _cost_nu_match_defaults,
    _dedupe_cost_nu_rows,
)
from almabi_pq_common import nomenclature_key
from almabi_test_pipeline import run_test_pipeline


def _latest(prefix: str) -> Path:
    return sorted((ROOT / "uploads" / "almabi").glob(f"{prefix}*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True)[0]


def main() -> None:
    paths = {k: _latest(k + "-") for k in ("buh", "cost", "realization", "cost_nu")}
    exports = parse_exports(paths)
    facts = run_test_pipeline(paths).result.facts
    deduped = _dedupe_cost_nu_rows(exports.cost_nu)
    pool = _build_cost_nu_exact_pool(deduped)
    consumed: set[int] = set()

    cost_facts = [f for f in facts if f.kpi_l1 == "Себестоимость" and f.month == "Апрель"]
    fact_keys: set[tuple] = set()
    for fact in cost_facts:
        _consume_cost_nu_exact(
            pool, deduped, consumed,
            document=fact.document,
            nomenclature=fact.nomenclature,
            account=fact.cost_account,
            calc_article=fact.expense_article,
        )
        acct, article = _cost_nu_match_defaults(fact.cost_account, fact.expense_article)
        for dk in document_match_keys(fact.document):
            fact_keys.add((dk, nomenclature_key(fact.nomenclature), acct, article))

    reasons = defaultdict(float)
    samples: list[str] = []

    for index, row in enumerate(deduped):
        if index in consumed or row.month != "Апрель":
            continue
        amount = float(row.amount_nu or 0)
        acct, article = _cost_nu_match_defaults(row.account, row.calc_article)
        nom = nomenclature_key(row.nomenclature)
        doc_keys = document_match_keys(row.document)

        partial_doc = any(dk in {k[0] for k in fact_keys} for dk in doc_keys)
        partial_nom = any(nom == k[1] for k in fact_keys if any(dk == k[0] for dk in doc_keys))
        exact = any((dk, nom, acct, article) in fact_keys for dk in doc_keys)

        if exact:
            reason = "exact_key_exists_but_unconsumed"
        elif partial_doc and partial_nom and acct == "20":
            reason = "doc_nom_match_article_or_account_diff"
        elif partial_doc:
            reason = "doc_only_match"
        else:
            reason = "no_doc_match"

        reasons[reason] += amount
        if len(samples) < 8 and amount > 500_000:
            samples.append(
                f"{amount:,.0f} | {reason} | acct={row.account} art={row.calc_article[:25]} | {row.nomenclature[:40]}"
            )

    print("unconsumed NU by reason (April):")
    for k, v in sorted(reasons.items(), key=lambda x: -abs(x[1])):
        print(f"  {k}: {v:,.2f}")
    print("samples:")
    for s in samples:
        print(" ", s)


if __name__ == "__main__":
    main()
