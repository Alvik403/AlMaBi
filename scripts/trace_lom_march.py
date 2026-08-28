"""Where lom nomenclatures go in March."""
from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from almabi_dashboard_builder import build_cost_structure_facts_from_pq_rows
from almabi_excel_utils import month_name, normalize_text, parse_date_from_text
from almabi_pq_common import is_black_metal_scrap_nomenclature, should_include_in_cost_structure, build_davaltz_document_totals
from almabi_pq_cost import build_pq_cost_table
from almabi_test_builder import load_almabi_dashboard_from_exports


def _latest(prefix: str) -> Path:
    return sorted(Path("uploads/almabi").glob(f"{prefix}-*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True)[0]


TARGETS = (
    "алюминий 2-4",
    "алюминиевая стружка",
    "лом черных м/л 12",
)
MONTHS_FILTER = ("Март", "Июнь")


def main() -> None:
    paths = {"buh": _latest("buh"), "cost": _latest("cost"), "realization": _latest("realization")}
    pq = build_pq_cost_table(paths["cost"], projects_path=paths["realization"])
    davaltz = build_davaltz_document_totals(pq)
    dashboard = load_almabi_dashboard_from_exports(
        paths, upload_names={k: v.name for k, v in paths.items()}, logs_dir=None
    )
    cost = next(r for r in dashboard["summary_rows"] if r["name"] == "Себестоимость")
    structure = build_cost_structure_facts_from_pq_rows(pq)

    print("=== PQ rows ===")
    for row in pq:
        nom = normalize_text(row.get("Номенклатура"))
        if not any(t in nom.casefold() for t in TARGETS):
            continue
        month = month_name(parse_date_from_text(row.get("Документ")))
        if month not in MONTHS_FILTER:
            continue
        in_struct = should_include_in_cost_structure(
            document=row.get("Документ"),
            nomenclature=row.get("Номенклатура"),
            davaltz_totals=davaltz,
        )
        print(
            f"  {nom}\n"
            f"    sum={row.get('Сумма')} section={row.get('Раздел')} "
            f"dir={row.get('Направление')} in_structure={in_struct} "
            f"black={is_black_metal_scrap_nomenclature(nom)}"
        )

    print("\n=== In structure facts ===")
    for fact in structure:
        if fact.month not in MONTHS_FILTER:
            continue
        if not any(t in (fact.nomenclature or "").casefold() for t in TARGETS):
            continue
        print(
            f"  {fact.nomenclature}: {fact.amount_buh:,.2f} "
            f"section={fact.cost_section} dir={fact.direction or 'Без направления'}"
        )

    prochee = next((c for c in cost["children"] if c["name"] == "Прочее"), None)
    if prochee:
        print("\n=== Under Прочее ===")
        for month in MONTHS_FILTER:
            print(f"  -- {month} --")
            for child in prochee.get("children") or []:
                val = child["values"]["Факт БУ"].get(month, 0)
                if not val:
                    continue
                print(f"    {child['name']}: {val:,.2f}")
                for sub in child.get("children") or []:
                    sv = sub["values"]["Факт БУ"].get(month, 0)
                    if sv:
                        print(f"      · {sub['name']}: {sv:,.2f}")
            continue

    print("\n=== L2 with 'Себестоимость' in name ===")
    for child in cost["children"]:
        if "себест" in child["name"].casefold():
            print(f"  {child['name']!r} total={child.get('total_fact', 0):,.2f}")


if __name__ == "__main__":
    main()
