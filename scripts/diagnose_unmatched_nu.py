"""Диагностика причин несопоставления 1:1 и KPI по корзинам."""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from almabi_excel_utils import tax_bucket
from almabi_export_parsers import parse_exports
from almabi_pipeline import (
    _build_cost_nu_exact_pool,
    _consume_cost_nu_exact,
    _cost_nu_match_defaults,
    _dedupe_cost_nu_rows,
)
from almabi_pq_common import nomenclature_key
from almabi_test_pipeline import build_test_facts


def _latest(prefix: str) -> Path:
    uploads = ROOT / "uploads" / "almabi"
    return sorted(uploads.glob(f"{prefix}*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True)[0]


def main() -> None:
    paths = {
        "buh": _latest("buh-"),
        "cost": _latest("cost-"),
        "realization": _latest("realization-"),
        "cost_nu": _latest("cost_nu-"),
    }
    facts = build_test_facts(parse_exports(paths)).facts
    cost_facts = [f for f in facts if f.kpi_l1 == "Себестоимость"]
    deduped = _dedupe_cost_nu_rows(parse_exports(paths).cost_nu)
    pool = _build_cost_nu_exact_pool(deduped)
    consumed: set[int] = set()

    reasons = defaultdict(lambda: {"count": 0, "buh_abs": 0.0, "priv_buh_abs": 0.0})
    kpi_by_bucket = defaultdict(lambda: defaultdict(lambda: {"buh": 0.0, "nu": 0.0}))

    for fact in facts:
        bucket = tax_bucket(fact.tax_type)
        kpi_by_bucket[fact.kpi_l1][bucket]["buh"] += float(fact.amount_buh or 0)
        kpi_by_bucket[fact.kpi_l1][bucket]["nu"] += float(fact.amount_nu or 0)

    for fact in cost_facts:
        bucket = tax_bucket(fact.tax_type)
        buh_abs = abs(float(fact.amount_buh or 0))
        raw = _consume_cost_nu_exact(
            pool, deduped, consumed,
            document=fact.document,
            nomenclature=fact.nomenclature,
            account=fact.cost_account,
            calc_article=fact.expense_article,
        )
        if raw is not None:
            continue
        if not (fact.document or "").strip():
            reason = "empty_document"
        elif not nomenclature_key(fact.nomenclature):
            reason = "empty_nomenclature"
        else:
            acct, article = _cost_nu_match_defaults(fact.cost_account, fact.expense_article)
            doc_only_pool = {
                k: v for k, v in pool.items()
                if k[1] == nomenclature_key(fact.nomenclature) and k[2] == acct and k[3] == article
            }
            if not doc_only_pool:
                reason = "no_nu_key_at_all"
            else:
                reason = "document_mismatch"
        reasons[reason]["count"] += 1
        reasons[reason]["buh_abs"] += buh_abs
        if bucket == "Льготные проекты":
            reasons[reason]["priv_buh_abs"] += buh_abs

    april = "Апрель"
    april_kpi = {
        kpi: {
            bucket: {
                "buh": sum(float(f.amount_buh or 0) for f in facts if f.kpi_l1 == kpi and f.month == april and tax_bucket(f.tax_type) == bucket),
                "nu": sum(float(f.amount_nu or 0) for f in facts if f.kpi_l1 == kpi and f.month == april and tax_bucket(f.tax_type) == bucket),
            }
            for bucket in ("Льготные проекты", "Нельготные проекты")
        }
        for kpi in ("Выручка", "Себестоимость", "Коммерческие расходы", "Управленческие расходы", "Прочие доходы", "Прочие расходы", "Налоги")
    }

    data = {
        "unmatched_reasons": dict(reasons),
        "year_totals_by_kpi_bucket": {k: dict(v) for k, v in kpi_by_bucket.items()},
        "april_by_kpi_bucket": april_kpi,
        "april_privileged_pbt_components": {
            "revenue_nu": april_kpi["Выручка"]["Льготные проекты"]["nu"],
            "cost_nu": april_kpi["Себестоимость"]["Льготные проекты"]["nu"],
            "commercial_nu": april_kpi["Коммерческие расходы"]["Льготные проекты"]["nu"],
            "admin_nu": april_kpi["Управленческие расходы"]["Льготные проекты"]["nu"],
            "other_income_nu": april_kpi["Прочие доходы"]["Льготные проекты"]["nu"],
            "other_expense_nu": april_kpi["Прочие расходы"]["Льготные проекты"]["nu"],
        },
    }
    print(json.dumps(data, ensure_ascii=False, indent=2))

    with (ROOT / "debug-099d59.log").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "sessionId": "099d59",
            "runId": "tax-bucket-check",
            "hypothesisId": "H-priv-detail",
            "location": "scripts/diagnose_unmatched_nu.py",
            "message": "unmatched_and_bucket_kpi",
            "data": data,
            "timestamp": __import__("time").time_ns() // 1_000_000,
        }, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
