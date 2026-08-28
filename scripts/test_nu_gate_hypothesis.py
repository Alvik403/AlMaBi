from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from almabi_excel_utils import tax_bucket
from almabi_export_parsers import parse_exports, classify_buh_section
from almabi_pipeline import (
    _amount_buh_for_section,
    _amount_nu_for_section,
    _build_other_pnl_storno_groups,
    _other_pnl_nu_mismatch_documents,
)

REF = {
    "income": {"priv_bu": 2_047_897.23, "non_bu": 129_530_108.64, "priv_nu": 13_622_524.36, "non_nu": 128_387_130.19},
    "expense": {"priv_bu": 2_383_391_876.05, "non_bu": 128_307_529.33, "priv_nu": 25_857_545.27, "non_nu": 118_671_636.07},
}
MONTH = "Март"
paths = {"buh": Path.home() / "Downloads" / "Выгрузка - бух.регистр (2).xlsx", "cost": Path.home() / "Downloads" / "Выгрузка - себестоимость (1).xlsx", "realization": Path.home() / "Downloads" / "Выгрузка - Реализации проекты (2).xlsx"}
exports = parse_exports(paths)
storno = _build_other_pnl_storno_groups(exports)
nu_mismatch = _other_pnl_nu_mismatch_documents(exports)


def resolve_bu_hyp(row, *, nu_gate: bool) -> str:
    from almabi_pipeline import _resolve_other_pnl_tax_type

    fallback = row.tax_type or "Общие условия налогообложения"
    if tax_bucket(fallback) == "Льготные проекты":
        return fallback
    if row.document not in nu_mismatch:
        return fallback
    section = classify_buh_section(row.account_dt, row.account_kt)
    if section not in ("Прочие доходы", "Прочие расходы"):
        return fallback
    if nu_gate:
        nu = _amount_nu_for_section(section, row.amount_nu_dt, row.amount_nu_kt)
        if abs(nu) < 0.01:
            return fallback
    return _resolve_other_pnl_tax_type(row, storno_groups=storno, nu_mismatch_docs=nu_mismatch)


for section, ref in (("Прочие доходы", REF["income"]), ("Прочие расходы", REF["expense"])):
    for label, nu_gate in (("current (all storno)", False), ("hyp: storno only if row NU != 0", True)):
        priv_bu = non_bu = priv_nu = non_nu = 0.0
        for row in exports.buh:
            if row.month != MONTH:
                continue
            sec = classify_buh_section(row.account_dt, row.account_kt)
            if sec != section:
                continue
            bu = _amount_buh_for_section(sec, row, None)
            nu = _amount_nu_for_section(sec, row.amount_nu_dt, row.amount_nu_kt)
            if nu_gate:
                bu_tax = resolve_bu_hyp(row, nu_gate=True)
            else:
                from almabi_pipeline import _resolve_row_tax_type

                bu_tax = _resolve_row_tax_type(
                    sec, row, {}, other_pnl_storno_groups=storno, other_pnl_nu_mismatch_docs=nu_mismatch
                )
            if tax_bucket(bu_tax) == "Льготные проекты":
                priv_bu += bu
            else:
                non_bu += bu
            # NU always current resolution
            from almabi_pipeline import _build_other_pnl_nu_storno_groups, _resolve_other_pnl_nu_tax_type

            nu_tax = _resolve_other_pnl_nu_tax_type(
                row,
                exports=exports,
                doc_tax={},
                buh_storno_groups=storno,
                nu_storno_groups=_build_other_pnl_nu_storno_groups(exports),
                nu_mismatch_docs=nu_mismatch,
            )
            if tax_bucket(nu_tax) == "Льготные проекты":
                priv_nu += nu
            else:
                non_nu += nu
        print(f"\n{section} / {label}")
        print(f"  priv BU {priv_bu:,.2f} vs ref {ref['priv_bu']:,.2f} delta {priv_bu - ref['priv_bu']:,.2f}")
        print(f"  non  BU {non_bu:,.2f} vs ref {ref['non_bu']:,.2f} delta {non_bu + ref['non_bu']:,.2f}")
        print(f"  priv NU {priv_nu:,.2f} vs ref {ref['priv_nu']:,.2f} delta {priv_nu - ref['priv_nu']:,.2f}")
        print(f"  non  NU {non_nu:,.2f} vs ref {ref['non_nu']:,.2f} delta {non_nu + ref['non_nu']:,.2f}")
