"""Find source of +5635 in March Прочие расходы non-priv vs 1C ref."""
from __future__ import annotations

import json
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from almabi_excel_utils import tax_bucket
from almabi_export_parsers import parse_exports, classify_buh_section
from almabi_pipeline import _amount_buh_for_section, _amount_nu_for_section
from almabi_test_pipeline import run_test_pipeline

MONTH = "Март"
REF_NON = 128_307_529.33
REF_TOTAL = 2_511_699_405.38
paths = {
    "buh": Path.home() / "Downloads" / "Выгрузка - бух.регистр (2).xlsx",
    "cost": Path.home() / "Downloads" / "Выгрузка - себестоимость (1).xlsx",
    "realization": Path.home() / "Downloads" / "Выгрузка - Реализации проекты (2).xlsx",
}

facts = run_test_pipeline(paths).result.facts
expense = [f for f in facts if f.kpi_l1 == "Прочие расходы" and f.month == MONTH]
non_facts = [f for f in expense if tax_bucket(f.tax_type) == "Нельготные проекты"]
non_total = sum(f.amount_buh for f in non_facts)
print(f"non-priv signed {non_total:,.2f}  abs {abs(non_total):,.2f}  delta vs ref {abs(non_total) - REF_NON:,.2f}")

# By expense article
by_art: dict[str, float] = defaultdict(float)
for f in non_facts:
    by_art[f.expense_article or "Прочее"] += f.amount_buh
print("\nTop non-priv by expense_article (abs):")
for art, v in sorted(by_art.items(), key=lambda x: -abs(x[1]))[:15]:
    print(f"  {abs(v):>15,.2f}  {art[:70]}")

# By document prefix
by_doc: dict[str, float] = defaultdict(float)
for f in non_facts:
    by_doc[(f.contract or "")[:40] or (f.expense_article or "")[:30]] += f.amount_buh

# group by first 50 chars of... use contract+article from fact - we don't have document on Fact!
# Check Fact fields
print("\nFact fields sample:", [a for a in expense[0].__dataclass_fields__])

# Aggregate from raw buh rows classified as non-priv using same facts logic - group by document
exports = parse_exports(paths)
from almabi_pipeline import (
    _build_other_pnl_section_has_nu,
    _build_other_pnl_storno_groups,
    _other_pnl_nu_mismatch_documents,
    _resolve_row_tax_type,
)

doc_tax = {r.document: r.tax_type for r in exports.buh if r.document and r.tax_type}
st = _build_other_pnl_storno_groups(exports)
nm = _other_pnl_nu_mismatch_documents(exports)
has = _build_other_pnl_section_has_nu(exports)

raw_by_doc: dict[str, float] = defaultdict(float)
for row in exports.buh:
    if row.month != MONTH:
        continue
    sec = classify_buh_section(row.account_dt, row.account_kt)
    if sec != "Прочие расходы":
        continue
    bu = _amount_buh_for_section(sec, row, None)
    tax = _resolve_row_tax_type(
        sec, row, doc_tax,
        other_pnl_storno_groups=st,
        other_pnl_nu_mismatch_docs=nm,
        other_pnl_section_has_nu=has,
    )
    if tax_bucket(tax) != "Нельготные проекты":
        continue
    raw_by_doc[row.document[:60]] += bu

print("\nTop non-priv BU by document (register rows):")
for doc, v in sorted(raw_by_doc.items(), key=lambda x: -abs(x[1]))[:20]:
    print(f"  {abs(v):>15,.2f}  {doc}")

# Rows where BU != NU on same line - sum non-priv
mismatch_sum = 0.0
mismatch_rows = []
for row in exports.buh:
    if row.month != MONTH:
        continue
    sec = classify_buh_section(row.account_dt, row.account_kt)
    if sec != "Прочие расходы":
        continue
    bu = abs(_amount_buh_for_section(sec, row, None))
    nu = abs(_amount_nu_for_section(sec, row.amount_nu_dt, row.amount_nu_kt))
    if bu < 0.01 or nu < 0.01 or abs(bu - nu) <= 0.01:
        continue
    tax = row.tax_type or ""
    if tax_bucket(tax) == "Нельготные проекты":
        mismatch_sum += _amount_buh_for_section(sec, row, None)
        mismatch_rows.append((row.document[:50], bu, nu, bu - nu))

print(f"\nBU!=NU rows with raw non-priv tax: signed sum {mismatch_sum:,.2f} abs {abs(mismatch_sum):,.2f}")
for item in mismatch_rows[:10]:
    print(f"  doc={item[0]} bu={item[1]:,.2f} nu={item[2]:,.2f} diff={item[3]:,.2f}")

# 5635 hunt: small docs
small = [(d, v) for d, v in raw_by_doc.items() if 5000 < abs(v) < 7000]
print("\nDocs with non-priv abs between 5000 and 7000:", small)

log_path = Path(__file__).resolve().parent.parent / "debug-a10d6d.log"
payload = {
    "sessionId": "a10d6d",
    "runId": "5635-trace",
    "hypothesisId": "H-5635-non-priv",
    "location": "scripts/trace_5635_other_expense.py",
    "message": "March other expense non-priv delta",
    "data": {
        "non_abs": abs(non_total),
        "ref_non": REF_NON,
        "delta": abs(non_total) - REF_NON,
        "mismatch_non_priv_sum": mismatch_sum,
    },
    "timestamp": int(time.time() * 1000),
}
with log_path.open("a", encoding="utf-8") as f:
    f.write(json.dumps(payload, ensure_ascii=False) + "\n")
