from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from almabi_excel_utils import tax_bucket
from almabi_export_parsers import parse_exports, classify_buh_section
from almabi_pipeline import (
    _amount_buh_for_section,
    _amount_nu_for_section,
    _build_other_pnl_storno_groups,
    _other_pnl_nu_mismatch_documents,
    _resolve_other_pnl_nu_tax_type,
    _resolve_row_tax_type,
    run_pipeline,
)

MONTH = "Март"
paths = {
    "buh": Path.home() / "Downloads" / "Выгрузка - бух.регистр (2).xlsx",
    "cost": Path.home() / "Downloads" / "Выгрузка - себестоимость (1).xlsx",
    "realization": Path.home() / "Downloads" / "Выгрузка - Реализации проекты (2).xlsx",
}
exports = parse_exports(paths)
doc_tax: dict[str, str] = {}
for row in exports.buh:
    if row.document and row.tax_type:
        doc_tax.setdefault(row.document, row.tax_type)

storno = _build_other_pnl_storno_groups(exports)
from almabi_pipeline import _build_other_pnl_nu_storno_groups

nu_storno = _build_other_pnl_nu_storno_groups(exports)
nu_mismatch = _other_pnl_nu_mismatch_documents(exports)

section = "Прочие доходы"
shifts: list[tuple[float, str, str, str, str]] = []
raw_priv = raw_non = resolved_priv = resolved_non = 0.0
nu_priv = nu_non = 0.0

for row in exports.buh:
    if row.month != MONTH:
        continue
    sec = classify_buh_section(row.account_dt, row.account_kt)
    if sec != section:
        continue
    bu = _amount_buh_for_section(sec, row, None)
    nu = _amount_nu_for_section(sec, row.amount_nu_dt, row.amount_nu_kt)
    if abs(bu) < 0.01 and abs(nu) < 0.01:
        continue

    raw = row.tax_type or "Общие условия налогообложения"
    resolved_bu = _resolve_row_tax_type(
        sec, row, doc_tax, other_pnl_storno_groups=storno, other_pnl_nu_mismatch_docs=nu_mismatch
    )
    resolved_nu = _resolve_other_pnl_nu_tax_type(
        row,
        exports=exports,
        doc_tax=doc_tax,
        buh_storno_groups=storno,
        nu_storno_groups=nu_storno,
        nu_mismatch_docs=nu_mismatch,
    )

    if tax_bucket(raw) == "Льготные проекты":
        raw_priv += bu
    else:
        raw_non += bu
    if tax_bucket(resolved_bu) == "Льготные проекты":
        resolved_priv += bu
    else:
        resolved_non += bu
    if tax_bucket(resolved_nu) == "Льготные проекты":
        nu_priv += nu
    else:
        nu_non += nu

    if tax_bucket(raw) != tax_bucket(resolved_bu) and abs(bu) >= 0.01:
        shifts.append((bu, raw, resolved_bu, row.document, row.expense_article or ""))

print("=== March Прочие доходы row-level ===")
print(f"raw       priv BU {raw_priv:,.2f}  non BU {raw_non:,.2f}")
print(f"resolved  priv BU {resolved_priv:,.2f}  non BU {resolved_non:,.2f}")
print(f"resolved  priv NU {nu_priv:,.2f}  non NU {nu_non:,.2f}")
print(f"ref       priv BU 2,047,897.23  non BU 129,530,108.64")
print(f"ref       priv NU 13,622,524.36  non NU 128,387,130.19")
print(f"\nBU bucket shifts raw->resolved: {len(shifts)} rows, total BU moved {sum(s[0] for s in shifts):,.2f}")

by_doc: dict[str, float] = defaultdict(float)
for bu, raw, resolved, doc, art in shifts:
    by_doc[doc] += bu
print("\nTop docs shifting BU from priv raw to non resolved (or vice versa):")
for doc, amt in sorted(by_doc.items(), key=lambda x: -abs(x[1]))[:15]:
    print(f"  {amt:,.2f}  {doc[:80]}")

# Split facts analysis
facts = run_pipeline(paths).facts
income = [f for f in facts if f.kpi_l1 == section and f.month == MONTH]
print("\n=== Split fact pattern ===")
mismatch_facts = [
    f
    for f in income
    if (f.amount_buh and not f.amount_nu) or (f.amount_nu and not f.amount_buh)
]
print(f"split facts: {len(mismatch_facts)}")
priv_bu_from_bu_only = sum(
    f.amount_buh for f in income if f.amount_buh and not f.amount_nu and tax_bucket(f.tax_type) == "Льготные проекты"
)
non_bu_from_bu_only = sum(
    f.amount_buh for f in income if f.amount_buh and not f.amount_nu and tax_bucket(f.tax_type) == "Нельготные проекты"
)
priv_bu_from_both = sum(
    f.amount_buh for f in income if f.amount_buh and f.amount_nu and tax_bucket(f.tax_type) == "Льготные проекты"
)
non_bu_from_both = sum(
    f.amount_buh for f in income if f.amount_buh and f.amount_nu and tax_bucket(f.tax_type) == "Нельготные проекты"
)
print(f"BU-only priv {priv_bu_from_bu_only:,.2f} non {non_bu_from_bu_only:,.2f}")
print(f"Both   priv {priv_bu_from_both:,.2f} non {non_bu_from_both:,.2f}")

# What if BU bucket used nu_tax_type when they differ?
hyp_priv = hyp_non = 0.0
for row in exports.buh:
    if row.month != MONTH:
        continue
    sec = classify_buh_section(row.account_dt, row.account_kt)
    if sec != section:
        continue
    bu = _amount_buh_for_section(sec, row, None)
    if abs(bu) < 0.01:
        continue
    resolved_bu = _resolve_row_tax_type(
        sec, row, doc_tax, other_pnl_storno_groups=storno, other_pnl_nu_mismatch_docs=nu_mismatch
    )
    resolved_nu = _resolve_other_pnl_nu_tax_type(
        row,
        exports=exports,
        doc_tax=doc_tax,
        buh_storno_groups=storno,
        nu_storno_groups=nu_storno,
        nu_mismatch_docs=nu_mismatch,
    )
    bucket = tax_bucket(resolved_nu if tax_bucket(resolved_bu) != tax_bucket(resolved_nu) else resolved_bu)
    if bucket == "Льготные проекты":
        hyp_priv += bu
    else:
        hyp_non += bu
print(f"\nHypothesis: BU bucket = NU bucket when they differ")
print(f"  priv BU {hyp_priv:,.2f}  non BU {hyp_non:,.2f}")

# What if BU always raw tax_type?
print(f"\nHypothesis: BU bucket always raw tax_type (already computed above)")
