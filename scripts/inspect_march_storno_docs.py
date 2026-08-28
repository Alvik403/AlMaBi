from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from almabi_export_parsers import parse_exports, classify_buh_section
from almabi_excel_utils import tax_bucket
from almabi_pipeline import _amount_buh_for_section, _amount_nu_for_section

paths = {
    "buh": Path.home() / "Downloads" / "Выгрузка - бух.регистр (2).xlsx",
    "cost": Path.home() / "Downloads" / "Выгрузка - себестоимость (1).xlsx",
    "realization": Path.home() / "Downloads" / "Выгрузка - Реализации проекты (2).xlsx",
}
exports = parse_exports(paths)
DOCS = [
    "00АМ-000549",
    "00АМ-000550",
    "00АМ-000552",
    "00АМ-000545",
]

for doc_prefix in DOCS:
    print(f"\n{'='*80}\n{doc_prefix}")
    for row in exports.buh:
        if doc_prefix not in (row.document or ""):
            continue
        if row.month != "Март":
            continue
        sec = classify_buh_section(row.account_dt, row.account_kt)
        if sec not in ("Прочие доходы", "Прочие расходы"):
            continue
        bu = _amount_buh_for_section(sec, row, None)
        nu = _amount_nu_for_section(sec, row.amount_nu_dt, row.amount_nu_kt)
        print(
            f"  {sec[:12]:12} dt={row.account_dt} kt={row.account_kt} "
            f"BU={bu:,.2f} NU={nu:,.2f} tax={row.tax_type!r} bucket={tax_bucket(row.tax_type)} "
            f"art={row.expense_article!r}"
        )
