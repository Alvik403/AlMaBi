"""March gap / Прочее breakdown."""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from almabi_dashboard_builder import build_cost_structure_facts_from_pq_rows
from almabi_excel_utils import month_name, normalize_text, parse_date_from_text, read_workbook_rows
from almabi_pq_common import (
    build_davaltz_document_totals,
    is_black_metal_scrap_nomenclature,
    is_cost_structure_cost_document,
    should_include_in_cost_structure,
)
from almabi_pq_cost import build_pq_cost_table, _load_cost_prepared_rows, _prepare_raw_rows
from almabi_test_builder import load_almabi_dashboard_from_exports
from almabi_test_pipeline import run_test_pipeline

MONTH = "Март"


def _latest(prefix: str) -> Path:
    return sorted(Path("uploads/almabi").glob(f"{prefix}-*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True)[0]


def main() -> None:
    paths = {"buh": _latest("buh"), "cost": _latest("cost"), "realization": _latest("realization")}
    pipeline = run_test_pipeline(paths, logs_dir=None, write_audit=False)
    dashboard = load_almabi_dashboard_from_exports(
        paths, upload_names={k: v.name for k, v in paths.items()}, logs_dir=None
    )
    cost = next(r for r in dashboard["summary_rows"] if r["name"] == "Себестоимость")
    gap_node = next(c for c in cost["children"] if c["name"] == "Прочее")
    march_gap = gap_node["values"]["Факт БУ"][MONTH]
    print(f"March gap (Прочее): {march_gap:,.2f}")
    print("\nПрочее — детализация (March):")
    for child in gap_node.get("children") or []:
        val = child["values"]["Факт БУ"][MONTH]
        print(f"  {child['name']}: {val:,.2f}")
        for sub in child.get("children") or []:
            sub_val = sub["values"]["Факт БУ"][MONTH]
            print(f"    · {sub['name']}: {sub_val:,.2f}")

    pq = pipeline.pq_cost_rows or []
    davaltz = build_davaltz_document_totals(pq)
    structure = build_cost_structure_facts_from_pq_rows(pq)

    excluded: dict[str, float] = defaultdict(float)
    for row in pq:
        if normalize_text(row.get("Основной раздел")) != "Расходы":
            continue
        month = month_name(parse_date_from_text(row.get("Документ")))
        if month != MONTH:
            continue
        if should_include_in_cost_structure(
            document=row.get("Документ"),
            nomenclature=row.get("Номенклатура"),
            davaltz_totals=davaltz,
        ):
            continue
        doc = str(row.get("Документ") or "")
        key = doc.split(" от ")[0].strip()
        if is_black_metal_scrap_nomenclature(row.get("Номенклатура")):
            key = "Лом черных металлов"
        section = str(row.get("Раздел") or "")
        label = f"{key} ({section})" if section else key
        excluded[label] += float(row.get("Сумма") or 0)

    print("\nExcluded PQ rows (March):")
    total = 0.0
    for label, val in sorted(excluded.items(), key=lambda x: -abs(x[1])):
        total += val
        print(f"  {label}: {val:,.2f}")
    print(f"  ИТОГО excluded PQ: {total:,.2f}")

    buh_march = sum(f.amount_buh for f in pipeline.result.facts if f.kpi_l1 == "Себестоимость" and f.month == MONTH)
    struct_march = sum(f.amount_buh for f in structure if f.month == MONTH)
    print(f"\nBuh L1 march: {buh_march:,.2f}")
    print(f"Structure march: {struct_march:,.2f}")
    print(f"Gap computed: {buh_march - struct_march:,.2f}")


if __name__ == "__main__":
    main()
