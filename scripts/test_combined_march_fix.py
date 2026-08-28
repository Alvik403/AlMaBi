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
    _resolve_other_pnl_tax_type,
)

MONTH = "Март"
paths = {
    "buh": Path.home() / "Downloads" / "Выгрузка - бух.регистр (2).xlsx",
    "cost": Path.home() / "Downloads" / "Выгрузка - себестоимость (1).xlsx",
    "realization": Path.home() / "Downloads" / "Выгрузка - Реализации проекты (2).xlsx",
}
exports = parse_exports(paths)
storno = _build_other_pnl_storno_groups(exports)
nu_storno = _build_other_pnl_nu_storno_groups(exports)
nu_mismatch = _other_pnl_nu_mismatch_documents(exports)
doc_tax = {r.document: r.tax_type for r in exports.buh if r.document and r.tax_type}

has_nu_in_section: set[tuple[str, str, str]] = set()
for row in exports.buh:
    if not row.month:
        continue
    section = classify_buh_section(row.account_dt, row.account_kt)
    if section not in ("Прочие доходы", "Прочие расходы"):
        continue
    nu = _amount_nu_for_section(section, row.amount_nu_dt, row.amount_nu_kt)
    if abs(nu) >= 0.01:
        has_nu_in_section.add((row.document, row.month, section))

REF = {
    "Прочие доходы": {"priv_bu": 2_047_897.23, "non_bu": 129_530_108.64, "total_nu": 142_009_654.55, "priv_nu": 13_622_524.36, "non_nu": 128_387_130.19},
    "Прочие расходы": {"priv_bu": 2_383_391_876.05, "non_bu": 128_307_529.33, "total_nu": 144_529_181.34, "priv_nu": 25_857_545.27, "non_nu": 118_671_636.07},
}


def resolve_bu_tax(row) -> str:
    fallback = row.tax_type or "Общие условия налогообложения"
    if row.expense_article and COST_ROUNDING_ARTICLE in row.expense_article:
        return fallback
    if tax_bucket(fallback) == "Льготные проекты":
        return fallback
    section = classify_buh_section(row.account_dt, row.account_kt)
    if row.document not in nu_mismatch:
        return fallback
    if (row.document, row.month, section) not in has_nu_in_section:
        return fallback
    bu_raw = abs(_amount_buh_for_section(section, row, None))
    nu_raw = abs(_amount_nu_for_section(section, row.amount_nu_dt, row.amount_nu_kt))
    if section == "Прочие расходы" and bu_raw >= 0.01 and nu_raw >= 0.01 and abs(bu_raw - nu_raw) <= 0.01:
        return fallback
    return _resolve_other_pnl_tax_type(row, storno_groups=storno, nu_mismatch_docs=nu_mismatch)


def resolve_nu_tax(row) -> str:
    section = classify_buh_section(row.account_dt, row.account_kt)
    bu_raw = abs(_amount_buh_for_section(section, row, None))
    nu_raw = abs(_amount_nu_for_section(section, row.amount_nu_dt, row.amount_nu_kt))
    if section == "Прочие расходы" and bu_raw >= 0.01 and nu_raw >= 0.01 and abs(bu_raw - nu_raw) <= 0.01:
        return row.tax_type or doc_tax.get(row.document, "Общие условия налогообложения")
    return _resolve_other_pnl_nu_tax_type(
        row,
        exports=exports,
        doc_tax=doc_tax,
        buh_storno_groups=storno,
        nu_storno_groups=nu_storno,
        nu_mismatch_docs=nu_mismatch,
    )


for section, ref in REF.items():
    priv_bu = non_bu = priv_nu = non_nu = total_bu = total_nu = 0.0
    for row in exports.buh:
        if row.month != MONTH:
            continue
        sec = classify_buh_section(row.account_dt, row.account_kt)
        if sec != section:
            continue
        bu = _amount_buh_for_section(sec, row, None)
        nu = _amount_nu_for_section(sec, row.amount_nu_dt, row.amount_nu_kt)
        bt = resolve_bu_tax(row)
        nt = resolve_nu_tax(row)
        total_bu += bu
        total_nu += nu
        if tax_bucket(bt) == "Льготные проекты":
            priv_bu += bu
        else:
            non_bu += bu
        if tax_bucket(nt) == "Льготные проекты":
            priv_nu += nu
        else:
            non_nu += nu
    print(f"\n{section}")
    print(f"  total BU {total_bu:,.2f}  total NU {total_nu:,.2f}")
    print(f"  priv BU delta {priv_bu - ref['priv_bu']:,.2f}  non BU delta {non_bu + ref['non_bu']:,.2f}")
    print(f"  priv NU delta {priv_nu - ref['priv_nu']:,.2f}  non NU delta {non_nu + ref['non_nu']:,.2f}")
