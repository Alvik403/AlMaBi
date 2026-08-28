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
    _build_other_pnl_nu_storno_groups,
    _build_other_pnl_storno_groups,
    _other_pnl_nu_mismatch_documents,
    _resolve_other_pnl_nu_tax_type,
    _resolve_row_tax_type,
)

MONTH = "Март"
section = "Прочие расходы"
REF = {"priv_nu": 25_857_545.27, "non_nu": 118_671_636.07}
paths = {"buh": Path.home() / "Downloads" / "Выгрузка - бух.регистр (2).xlsx", "cost": Path.home() / "Downloads" / "Выгрузка - себестоимость (1).xlsx", "realization": Path.home() / "Downloads" / "Выгрузка - Реализации проекты (2).xlsx"}
exports = parse_exports(paths)
doc_tax = {}
for row in exports.buh:
    if row.document and row.tax_type:
        doc_tax.setdefault(row.document, row.tax_type)
storno = _build_other_pnl_storno_groups(exports)
nu_storno = _build_other_pnl_nu_storno_groups(exports)
nu_mismatch = _other_pnl_nu_mismatch_documents(exports)

raw_priv = raw_non = res_priv = res_non = 0.0
shifts = []
for row in exports.buh:
    if row.month != MONTH:
        continue
    sec = classify_buh_section(row.account_dt, row.account_kt)
    if sec != section:
        continue
    nu = _amount_nu_for_section(sec, row.amount_nu_dt, row.amount_nu_kt)
    if abs(nu) < 0.01:
        continue
    raw = row.tax_type or "Общие условия налогообложения"
    resolved = _resolve_other_pnl_nu_tax_type(
        row, exports=exports, doc_tax=doc_tax, buh_storno_groups=storno,
        nu_storno_groups=nu_storno, nu_mismatch_docs=nu_mismatch,
    )
    if tax_bucket(raw) == "Льготные проекты":
        raw_priv += nu
    else:
        raw_non += nu
    if tax_bucket(resolved) == "Льготные проекты":
        res_priv += nu
    else:
        res_non += nu
    if tax_bucket(raw) != tax_bucket(resolved):
        shifts.append((nu, raw, resolved, row.document, row.account_dt, row.account_kt, row.amount_buh, row.amount_nu_dt))

print("NU bucket raw vs resolved")
print(f"raw  priv {raw_priv:,.2f} non {raw_non:,.2f}")
print(f"res  priv {res_priv:,.2f} non {res_non:,.2f}")
print(f"ref  priv {REF['priv_nu']:,.2f} non {REF['non_nu']:,.2f}")
print(f"shift count {len(shifts)} total nu shifted {sum(s[0] for s in shifts):,.2f}")

by_doc = defaultdict(float)
for nu, *_rest in shifts:
    by_doc[_rest[2]] += nu
print("\nTop NU shifts by doc:")
for doc, amt in sorted(by_doc.items(), key=lambda x: -abs(x[1]))[:10]:
    print(f"  {amt:,.2f}  {doc[:70]}")

# Try raw NU tax for expense
print("\nIf NU bucket = raw tax_type:")
print(f"  priv {raw_priv:,.2f} delta {raw_priv + REF['priv_nu']:,.2f}")

# Rows where buh != nu on same line - bucket by buh amount ratio?
print("\n=== 000552 expense lines ===")
for row in exports.buh:
    if "000552" not in (row.document or "") or row.month != MONTH:
        continue
    sec = classify_buh_section(row.account_dt, row.account_kt)
    if sec != section:
        continue
    bu = _amount_buh_for_section(sec, row, None)
    nu = _amount_nu_for_section(sec, row.amount_nu_dt, row.amount_nu_kt)
    rt = _resolve_other_pnl_nu_tax_type(row, exports=exports, doc_tax=doc_tax, buh_storno_groups=storno, nu_storno_groups=nu_storno, nu_mismatch_docs=nu_mismatch)
    print(f"  BU {bu:,.2f} NU {nu:,.2f} raw={row.tax_type[:20]!r} resolved={rt[:20]!r}")
