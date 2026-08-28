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
REF_INC = {"priv_bu": 2_047_897.23, "non_bu": 129_530_108.64}
paths = {"buh": Path.home() / "Downloads" / "Выгрузка - бух.регистр (2).xlsx", "cost": Path.home() / "Downloads" / "Выгрузка - себестоимость (1).xlsx", "realization": Path.home() / "Downloads" / "Выгрузка - Реализации проекты (2).xlsx"}
exports = parse_exports(paths)
storno = _build_other_pnl_storno_groups(exports)
nu_storno = _build_other_pnl_nu_storno_groups(exports)
nu_mismatch = _other_pnl_nu_mismatch_documents(exports)


def resolve_bu(row, mode: str) -> str:
    fallback = row.tax_type or "Общие условия налогообложения"
    if tax_bucket(fallback) == "Льготные проекты":
        return fallback
    if row.document not in nu_mismatch:
        return fallback
    section = classify_buh_section(row.account_dt, row.account_kt)
    if section not in ("Прочие доходы", "Прочие расходы"):
        return fallback
    nu = _amount_nu_for_section(section, row.amount_nu_dt, row.amount_nu_kt)
    key = (row.document, section, round(abs(row.amount_buh or 0), 2))
    mirrors = [c for c in storno.get(key, []) if c is not row and tax_bucket(c.tax_type) == "Льготные проекты" and (row.amount_buh or 0) * (c.amount_buh or 0) < 0]

    if mode == "row_nu":
        if abs(nu) < 0.01:
            return fallback
    elif mode == "mirror_nu":
        if not any(abs(_amount_nu_for_section(section, c.amount_nu_dt, c.amount_nu_kt)) >= 0.01 for c in mirrors):
            if abs(nu) < 0.01:
                return fallback
    elif mode == "doc_has_nu_in_section":
        has_nu = any(
            abs(_amount_nu_for_section(section, r.amount_nu_dt, r.amount_nu_kt)) >= 0.01
            for r in exports.buh
            if r.document == row.document and r.month == row.month and classify_buh_section(r.account_dt, r.account_kt) == section
        )
        if not has_nu:
            return fallback
    elif mode == "pair_nu":
        if abs(nu) < 0.01 and not any(
            abs(_amount_nu_for_section(section, c.amount_nu_dt, c.amount_nu_kt)) >= 0.01 for c in mirrors
        ):
            return fallback

    for candidate in mirrors:
        return candidate.tax_type
    return fallback


for mode in ("row_nu", "mirror_nu", "doc_has_nu_in_section", "pair_nu"):
    priv = non = 0.0
    for row in exports.buh:
        if row.month != MONTH:
            continue
        sec = classify_buh_section(row.account_dt, row.account_kt)
        if sec != "Прочие доходы":
            continue
        bu = _amount_buh_for_section(sec, row, None)
        t = resolve_bu(row, mode)
        if tax_bucket(t) == "Льготные проекты":
            priv += bu
        else:
            non += bu
    print(f"{mode}: priv {priv:,.2f} delta {priv - REF_INC['priv_bu']:,.2f}")
