from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from almabi_excel_utils import MONTH_NAMES, parse_date
from almabi_export_parsers import classify_buh_section, parse_exports

rows = parse_exports({"buh": Path.home() / "Downloads" / "Выгрузка - бух.регистр (2).xlsx"}).buh
print("=== Raw buh rows with |amount| = 20,000 in Jan commercial/admin ===")
for row in rows:
    parsed = parse_date(row.date)
    month = MONTH_NAMES.get(parsed.month, "") if parsed else ""
    if month != "Январь":
        continue
    section = classify_buh_section(row.account_dt, row.account_kt)
    if section not in {"Коммерческие расходы", "Управленческие расходы"}:
        continue
    amounts = {
        "buh_dt": row.amount_buh_dt,
        "buh_kt": row.amount_buh_kt,
        "nu_dt": row.amount_nu_dt,
        "nu_kt": row.amount_nu_kt,
    }
    for label, value in amounts.items():
        if abs(abs(value) - 20_000) < 0.02:
            article = (row.expense_article or "")[:70]
            print(f"{section} {label}={value:,.2f} doc={row.document!r} article={article!r}")
