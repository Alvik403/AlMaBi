"""Проверка: помогает ли нормализация счёта (20.01 -> 20) для 1:1."""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from almabi_excel_utils import normalize_text, tax_bucket
from almabi_export_parsers import parse_exports
from almabi_pipeline import _build_cost_nu_exact_pool, _consume_cost_nu_exact, _dedupe_cost_nu_rows, _cost_nu_match_defaults
from almabi_pq_common import nomenclature_key
from almabi_test_pipeline import build_test_facts


def _latest(prefix: str) -> Path:
    uploads = ROOT / "uploads" / "almabi"
    return sorted(uploads.glob(f"{prefix}*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True)[0]


def _norm_account(account: str) -> str:
    text = normalize_text(account or "20")
    if not text:
        return "20"
    return text.split(".")[0]


def main() -> None:
    paths = {"buh": _latest("buh-"), "cost": _latest("cost-"), "realization": _latest("realization-"), "cost_nu": _latest("cost_nu-")}
    exports = parse_exports(paths)
    facts = build_test_facts(exports).facts
    cost_facts = [f for f in facts if f.kpi_l1 == "Себестоимость"]
    deduped = _dedupe_cost_nu_rows(exports.cost_nu)

    def run_match(use_parent_account: bool) -> tuple[int, float, float]:
        pool = _build_cost_nu_exact_pool(deduped) if not use_parent_account else None
        if use_parent_account:
            from collections import defaultdict as dd
            from almabi_excel_utils import document_match_keys
            pool = dd(list)
            for index, row in enumerate(deduped):
                amount = float(row.amount_nu or 0)
                if not amount:
                    continue
                nom = nomenclature_key(row.nomenclature)
                if not nom:
                    continue
                acct = _norm_account(row.account).casefold()
                article = _cost_nu_match_defaults(row.account, row.calc_article)[1]
                for doc_key in document_match_keys(row.document):
                    pool[(doc_key, nom, acct, article)].append(index)
            pool = dict(pool)
        consumed: set[int] = set()
        unmatched = 0
        priv_gap = 0.0
        for fact in cost_facts:
            acct = _norm_account(fact.cost_account) if use_parent_account else fact.cost_account
            raw = _consume_cost_nu_exact(pool, deduped, consumed, document=fact.document, nomenclature=fact.nomenclature, account=acct, calc_article=fact.expense_article)
            if raw is None:
                unmatched += 1
                if tax_bucket(fact.tax_type) == "Льготные проекты":
                    priv_gap += abs(float(fact.amount_buh or 0))
        return unmatched, priv_gap, len(consumed)

    strict = run_match(False)
    relaxed = run_match(True)
    print({"strict_4key": {"unmatched": strict[0], "priv_unmatched_buh": strict[1], "matched_rows": strict[2]}, "parent_account_4key": {"unmatched": relaxed[0], "priv_unmatched_buh": relaxed[1], "matched_rows": relaxed[2]}})


if __name__ == "__main__":
    main()
