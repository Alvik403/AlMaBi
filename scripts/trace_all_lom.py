"""Find colored/black lom in PQ cost."""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from almabi_excel_utils import month_name, normalize_text, parse_date_from_text
from almabi_dashboard_builder import build_cost_structure_facts_from_pq_rows
from almabi_pq_common import is_black_metal_scrap_nomenclature, should_include_in_cost_structure, build_davaltz_document_totals
from almabi_pq_cost import build_pq_cost_table


def _latest(prefix: str) -> Path:
    return sorted(Path("uploads/almabi").glob(f"{prefix}-*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True)[0]


def main() -> None:
    pq = build_pq_cost_table(_latest("cost"), projects_path=_latest("realization"))
    davaltz = build_davaltz_document_totals(pq)
    structure = build_cost_structure_facts_from_pq_rows(pq)
    by_nom: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))

    for row in pq:
        nom = normalize_text(row.get("Номенклатура"))
        if "лом" not in nom.casefold():
            continue
        month = month_name(parse_date_from_text(row.get("Документ"))) or "?"
        if normalize_text(row.get("Основной раздел")) != "Расходы":
            continue
        by_nom[nom][month] += float(row.get("Сумма") or 0)

    print("All lom nomenclatures (Расходы):")
    for nom, months in sorted(by_nom.items(), key=lambda x: -sum(x[1].values())):
        in_struct = should_include_in_cost_structure(
            document="Реализация",
            nomenclature=nom,
            davaltz_totals=davaltz,
        ) if False else None
        black = is_black_metal_scrap_nomenclature(nom)
        struct_march = sum(f.amount_buh for f in structure if f.nomenclature == nom and f.month == "Март")
        print(f"  {nom[:70]}")
        print(f"    black={black} march_struct={struct_march:,.2f} months={dict(months)}")


if __name__ == "__main__":
    main()
