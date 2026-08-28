from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from almabi_excel_utils import tax_bucket
from almabi_export_parsers import parse_exports, classify_buh_section
from almabi_pipeline import (
    COST_ROUNDING_ARTICLE,
    _amount_buh_for_section,
    _amount_nu_for_section,
    _build_other_pnl_nu_storno_groups,
    _build_other_pnl_storno_groups,
    _other_pnl_nu_mismatch_documents,
    _resolve_other_pnl_nu_tax_type,
    _resolve_row_tax_type,
)

MONTH = "Март"
REF = {"priv_bu": 2_383_391_876.05, "non_bu": 128_307_529.33, "priv_nu": 25_857_545.27, "non_nu": 118_671_636.07}
paths = {"buh": Path.home() / "Downloads" / "Выгрузка - бух.регистр (2).xlsx", "cost": Path.home() / "Downloads" / "Выгрузка - себестоимость (1).xlsx", "realization": Path.home() / "Downloads" / "Выгрузка - Реализации проекты (2).xlsx"}
exports = parse_exports(paths)
doc_tax = {}
for row in exports.buh:
    if row.document and row.tax_type:
        doc_tax.setdefault(row.document, row.tax_type)
storno = _build_other_pnl_storno_groups(exports)
nu_storno = _build_other_pnl_nu_storno_groups(exports)
nu_mismatch = _other_pnl_nu_mismatch_documents(exports)
section = "Прочие расходы"

_doc_section_has_nu: dict[tuple[str, str, str], bool] = {}
for row in exports.buh:
    if row.month != MONTH:
        continue
    sec = classify_buh_section(row.account_dt, row.account_kt)
    if sec != section:
        continue
    nu = _amount_nu_for_section(sec, row.amount_nu_dt, row.amount_nu_kt)
    if abs(nu) >= 0.01:
        _doc_section_has_nu[(row.document, row.month, sec)] = True


def resolve_bu_gated(row) -> str:
    fallback = row.tax_type or "Общие условия налогообложения"
    if row.expense_article and COST_ROUNDING_ARTICLE in row.expense_article:
        return fallback
    if tax_bucket(fallback) == "Льготные проекты":
        return fallback
    if row.document not in nu_mismatch:
        return fallback
    if not _doc_section_has_nu.get((row.document, row.month, section), False):
        return fallback
    key = (row.document, section, round(abs(row.amount_buh or 0), 2))
    for candidate in storno.get(key, []):
        if candidate is row:
            continue
        if tax_bucket(candidate.tax_type) != "Льготные проекты":
            continue
        if (row.amount_buh or 0) * (candidate.amount_buh or 0) < 0:
            return candidate.tax_type
    return fallback


def agg(bu_tax_fn, nu_tax_fn):
    priv_bu = non_bu = priv_nu = non_nu = total_bu = total_nu = 0.0
    for row in exports.buh:
        if row.month != MONTH:
            continue
        sec = classify_buh_section(row.account_dt, row.account_kt)
        if sec != section:
            continue
        bu = _amount_buh_for_section(sec, row, None)
        nu = _amount_nu_for_section(sec, row.amount_nu_dt, row.amount_nu_kt)
        bt = bu_tax_fn(row)
        nt = nu_tax_fn(row)
        total_bu += bu
        total_nu += nu
        (priv_bu if tax_bucket(bt) == "Льготные проекты" else non_bu).__iadd__(bu) if False else None
        if tax_bucket(bt) == "Льготные проекты":
            priv_bu += bu
        else:
            non_bu += bu
        if tax_bucket(nt) == "Льготные проекты":
            priv_nu += nu
        else:
            non_nu += nu
    return total_bu, total_nu, priv_bu, non_bu, priv_nu, non_nu

current_bu = lambda r: _resolve_row_tax_type(section, r, doc_tax, other_pnl_storno_groups=storno, other_pnl_nu_mismatch_docs=nu_mismatch)
current_nu = lambda r: _resolve_other_pnl_nu_tax_type(r, exports=exports, doc_tax=doc_tax, buh_storno_groups=storno, nu_storno_groups=nu_storno, nu_mismatch_docs=nu_mismatch)
raw_bu = lambda r: r.tax_type or "Общие условия налогообложения"

for label, bu_fn in (("current BU resolve", current_bu), ("gated BU resolve", resolve_bu_gated), ("raw BU tax", raw_bu)):
    t = agg(bu_fn, current_nu)
    print(f"\n{label}: total BU {t[0]:,.2f} NU {t[1]:,.2f}")
    print(f"  priv BU {t[2]:,.2f} (ref {REF['priv_bu']:,.2f})")
    print(f"  non  BU {t[3]:,.2f} (ref {REF['non_bu']:,.2f})")
    print(f"  priv NU {t[4]:,.2f} (ref {REF['priv_nu']:,.2f}) delta {t[4]+REF['priv_nu']:,.2f}")
    print(f"  non  NU {t[5]:,.2f} (ref {REF['non_nu']:,.2f}) delta {t[5]+REF['non_nu']:,.2f}")

# rounding rows
print("\n=== COST_ROUNDING / pogreshnost rows ===")
for row in exports.buh:
    if row.month != MONTH:
        continue
    sec = classify_buh_section(row.account_dt, row.account_kt)
    if sec != section:
        continue
    if not row.expense_article or COST_ROUNDING_ARTICLE not in row.expense_article:
        continue
    bu = _amount_buh_for_section(sec, row, None)
    nu = _amount_nu_for_section(sec, row.amount_nu_dt, row.amount_nu_kt)
    print(f"  BU {bu:,.2f} NU {nu:,.2f} tax={row.tax_type!r} art={row.expense_article!r} doc={row.document[:50]}")
