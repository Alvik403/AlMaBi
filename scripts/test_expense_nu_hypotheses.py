from __future__ import annotations

import sys
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
)

MONTH = "Март"
REF = {"priv_nu": 25_857_545.27, "non_nu": 118_671_636.07, "priv_bu": 2_383_391_876.05, "non_bu": 128_307_529.33}
paths = {"buh": Path.home() / "Downloads" / "Выгрузка - бух.регистр (2).xlsx", "cost": Path.home() / "Downloads" / "Выгрузка - себестоимость (1).xlsx", "realization": Path.home() / "Downloads" / "Выгрузка - Реализации проекты (2).xlsx"}
exports = parse_exports(paths)
doc_tax = {row.document: row.tax_type for row in exports.buh if row.document and row.tax_type}
storno = _build_other_pnl_storno_groups(exports)
nu_storno = _build_other_pnl_nu_storno_groups(exports)
nu_mismatch = _other_pnl_nu_mismatch_documents(exports)
section = "Прочие расходы"

current_nu = lambda r: _resolve_other_pnl_nu_tax_type(
    r, exports=exports, doc_tax=doc_tax, buh_storno_groups=storno,
    nu_storno_groups=nu_storno, nu_mismatch_docs=nu_mismatch,
)


def nu_tax_both_nonzero_raw(row) -> str:
    bu = abs(_amount_buh_for_section(section, row, None))
    nu = abs(_amount_nu_for_section(section, row.amount_nu_dt, row.amount_nu_kt))
    if bu >= 0.01 and nu >= 0.01:
        return row.tax_type or "Общие условия налогообложения"
    return current_nu(row)


def nu_tax_nu_only_resolve(row) -> str:
    bu = abs(_amount_buh_for_section(section, row, None))
    nu = abs(_amount_nu_for_section(section, row.amount_nu_dt, row.amount_nu_kt))
    if bu >= 0.01:
        return row.tax_type or "Общие условия налогообложения"
    return current_nu(row)


for label, fn in (
    ("current", current_nu),
    ("both_nonzero -> raw", nu_tax_both_nonzero_raw),
    ("any_bu -> raw else resolve", nu_tax_nu_only_resolve),
):
    priv = non = 0.0
    for row in exports.buh:
        if row.month != MONTH:
            continue
        sec = classify_buh_section(row.account_dt, row.account_kt)
        if sec != section:
            continue
        nu = _amount_nu_for_section(sec, row.amount_nu_dt, row.amount_nu_kt)
        if abs(nu) < 0.01:
            continue
        t = fn(row)
        if tax_bucket(t) == "Льготные проекты":
            priv += nu
        else:
            non += nu
    print(f"{label}: priv {priv:,.2f} (delta {priv + REF['priv_nu']:,.2f})  non {non:,.2f} (delta {non + REF['non_nu']:,.2f})")
