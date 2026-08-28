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
    run_pipeline,
)

paths = {
    "buh": Path.home() / "Downloads" / "Выгрузка - бух.регистр (2).xlsx",
    "cost": Path.home() / "Downloads" / "Выгрузка - себестоимость (1).xlsx",
    "realization": Path.home() / "Downloads" / "Выгрузка - Реализации проекты (2).xlsx",
}
exports = parse_exports(paths)
storno = _build_other_pnl_storno_groups(exports)
nu_storno = _build_other_pnl_nu_storno_groups(exports)
nu_mismatch = _other_pnl_nu_mismatch_documents(exports)

# docs with NU per section
_doc_section_has_nu: dict[tuple[str, str, str], bool] = {}
for row in exports.buh:
    if not row.month:
        continue
    sec = classify_buh_section(row.account_dt, row.account_kt)
    if sec not in ("Прочие доходы", "Прочие расходы"):
        continue
    key = (row.document, row.month, sec)
    nu = _amount_nu_for_section(sec, row.amount_nu_dt, row.amount_nu_kt)
    if abs(nu) >= 0.01:
        _doc_section_has_nu[key] = True


def resolve_bu_new(row) -> str:
    fallback = row.tax_type or "Общие условия налогообложения"
    if tax_bucket(fallback) == "Льготные проекты":
        return fallback
    if row.document not in nu_mismatch:
        return fallback
    section = classify_buh_section(row.account_dt, row.account_kt)
    if section not in ("Прочие доходы", "Прочие расходы"):
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


REF = {
    "Март": {
        "Прочие доходы": {"priv_bu": 2_047_897.23, "non_bu": 129_530_108.64, "priv_nu": 13_622_524.36, "non_nu": 128_387_130.19},
        "Прочие расходы": {"priv_bu": 2_383_391_876.05, "non_bu": 128_307_529.33, "priv_nu": 25_857_545.27, "non_nu": 118_671_636.07},
    }
}

for month in ("Март", "Апрель"):
    print(f"\n===== {month} =====")
    for section in ("Прочие доходы", "Прочие расходы"):
        priv_bu = non_bu = priv_nu = non_nu = total_bu = total_nu = 0.0
        for row in exports.buh:
            if row.month != month:
                continue
            sec = classify_buh_section(row.account_dt, row.account_kt)
            if sec != section:
                continue
            bu = _amount_buh_for_section(sec, row, None)
            nu = _amount_nu_for_section(sec, row.amount_nu_dt, row.amount_nu_kt)
            bu_tax = resolve_bu_new(row)
            nu_tax = _resolve_other_pnl_nu_tax_type(
                row, exports=exports, doc_tax={}, buh_storno_groups=storno,
                nu_storno_groups=nu_storno, nu_mismatch_docs=nu_mismatch,
            )
            total_bu += bu
            total_nu += nu
            if tax_bucket(bu_tax) == "Льготные проекты":
                priv_bu += bu
            else:
                non_bu += bu
            if tax_bucket(nu_tax) == "Льготные проекты":
                priv_nu += nu
            else:
                non_nu += nu
        print(f"{section}: total BU {total_bu:,.2f} NU {total_nu:,.2f}")
        print(f"  priv BU {priv_bu:,.2f}  non BU {non_bu:,.2f}")
        print(f"  priv NU {priv_nu:,.2f}  non NU {non_nu:,.2f}")
        if month in REF and section in REF[month]:
            r = REF[month][section]
            print(f"  ref priv BU {r['priv_bu']:,.2f} delta {priv_bu - r['priv_bu']:,.2f}")

# Compare pipeline current vs new for split facts
facts = run_pipeline(paths).facts
for month in ("Март", "Апрель"):
    for section in ("Прочие доходы", "Прочие расходы"):
        rows = [f for f in facts if f.kpi_l1 == section and f.month == month]
        cur_priv_bu = sum(f.amount_buh for f in rows if tax_bucket(f.tax_type) == "Льготные проекты")
        print(f"pipeline current {month} {section} priv BU {cur_priv_bu:,.2f}")
