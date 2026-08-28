from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from almabi_excel_utils import tax_bucket
from almabi_export_parsers import parse_exports, classify_buh_section
from almabi_pipeline import run_pipeline

REF_INCOME = {
    "total_bu": 131_578_005.87,
    "total_nu": 142_009_654.55,
    "priv_bu": 2_047_897.23,
    "priv_nu": 13_622_524.36,
    "non_bu": 129_530_108.64,
    "non_nu": 128_387_130.19,
}
REF_EXPENSE = {
    "total_bu": 2_511_699_405.38,
    "total_nu": 144_529_181.34,
    "non_bu": 128_307_529.33,
    "non_nu": 118_671_636.07,
    "priv_bu": 2_383_391_876.05,
    "priv_nu": 25_857_545.27,
}
MONTH = "Март"

paths = {
    "buh": Path.home() / "Downloads" / "Выгрузка - бух.регистр (2).xlsx",
    "cost": Path.home() / "Downloads" / "Выгрузка - себестоимость (1).xlsx",
    "realization": Path.home() / "Downloads" / "Выгрузка - Реализации проекты (2).xlsx",
}
facts = run_pipeline(paths).facts

for kpi, ref in (("Прочие доходы", REF_INCOME), ("Прочие расходы", REF_EXPENSE)):
    rows = [f for f in facts if f.kpi_l1 == kpi and f.month == MONTH]
    bu = sum(f.amount_buh for f in rows)
    nu = sum(f.amount_nu for f in rows)
    print(f"\n=== {kpi} ===")
    print(f"pipeline BU {bu:,.2f} vs ref {ref['total_bu']:,.2f} delta {bu - ref['total_bu']:,.2f}")
    print(f"pipeline NU {nu:,.2f} vs ref {ref['total_nu']:,.2f} delta {nu + ref['total_nu']:,.2f}")

    for label, bu_key, nu_key in (
        ("priv", "priv_bu", "priv_nu"),
        ("non", "non_bu", "non_nu"),
    ):
        pb = sum(f.amount_buh for f in rows if tax_bucket(f.tax_type) == "Льготные проекты")
        pn = sum(f.amount_nu for f in rows if tax_bucket(f.tax_type) == "Льготные проекты")
        nb = sum(f.amount_buh for f in rows if tax_bucket(f.tax_type) == "Нельготные проекты")
        nn = sum(f.amount_nu for f in rows if tax_bucket(f.tax_type) == "Нельготные проекты")
        if label == "priv":
            print(f"  priv BU {pb:,.2f} vs {ref[bu_key]:,.2f} delta {pb - ref[bu_key]:,.2f}")
            print(f"  priv NU {pn:,.2f} vs {ref[nu_key]:,.2f} delta {pn - ref[nu_key]:,.2f}")
        else:
            print(f"  non  BU {nb:,.2f} vs {ref[bu_key]:,.2f} delta {nb + ref[bu_key]:,.2f}")
            print(f"  non  NU {nn:,.2f} vs {ref[nu_key]:,.2f} delta {nn + ref[nu_key]:,.2f}")

# BU-only / NU-only split facts for income
print("\n=== Income split facts (BU-only vs NU-only) ===")
income = [f for f in facts if f.kpi_l1 == "Прочие доходы" and f.month == MONTH]
bu_only = [f for f in income if f.amount_buh and not f.amount_nu]
nu_only = [f for f in income if f.amount_nu and not f.amount_buh]
both = [f for f in income if f.amount_buh and f.amount_nu]
print("bu_only", len(bu_only), "sum bu", sum(f.amount_buh for f in bu_only))
print("nu_only", len(nu_only), "sum nu", sum(f.amount_nu for f in nu_only))
print("both", len(both), "bu", sum(f.amount_buh for f in both), "nu", sum(f.amount_nu for f in both))

# Raw buh register March other income by raw tax_type vs amounts
exports = parse_exports(paths)
raw_priv_bu = raw_non_bu = raw_priv_nu = raw_non_nu = 0.0
for row in exports.buh:
    if row.month != MONTH:
        continue
    section = classify_buh_section(row.account_dt, row.account_kt)
    if section != "Прочие доходы":
        continue
    bu = row.amount_buh or 0
    nu = (row.amount_nu_dt or 0) - (row.amount_nu_kt or 0) if hasattr(row, "amount_nu_dt") else 0
    # use pipeline amount helper pattern
    from almabi_pipeline import _amount_nu_for_section

    nu = _amount_nu_for_section(section, row.amount_nu_dt, row.amount_nu_kt)
    bucket = tax_bucket(row.tax_type or "")
    if bucket == "Льготные проекты":
        raw_priv_bu += bu
        raw_priv_nu += nu
    else:
        raw_non_bu += bu
        raw_non_nu += nu
print("\n=== Raw register tax_type split (no storno resolve) ===")
print("priv BU", raw_priv_bu, "NU", raw_priv_nu)
print("non BU", raw_non_bu, "NU", raw_non_nu)
print("total BU", raw_priv_bu + raw_non_bu, "NU", raw_priv_nu + raw_non_nu)
