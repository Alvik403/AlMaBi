"""Compare March cost structure etalon vs BI and list directions."""
from __future__ import annotations

import json
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from almabi_test_builder import load_almabi_dashboard_from_exports
from almabi_excel_utils import read_workbook_rows, month_name, parse_date_from_text
from almabi_pq_cost import _load_cost_prepared_rows, _prepare_raw_rows
from almabi_export_parsers import classify_cost_section_pq, parse_exports, classify_buh_section
from almabi_pq_common import is_cost_structure_shipment_document
from almabi_dashboard_builder import _normalize_cost_structure_section

ETALON = {
    "Сырье и материалы": 188_537_518.24,
    "Амортизация": 431_444.29,
    "Аренда": 3_095.06,
    "ФОТ": 23_889_518.79,
    "Общепроизводственные расходы": 4_184_422.22,
    "Прочие производственные расходы": 4_419_998.02,
}
ETALON_TO_BI = {
    "Сырье и материалы": "Материальные затраты",
    "Аренда": "Аренда (прямые)",
}
MONTH = "Март"
LOG_PATH = Path("debug-099d59.log")


def _latest(prefix: str) -> Path:
    return sorted(Path("uploads/almabi").glob(f"{prefix}-*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True)[0]


def _log(data: dict) -> None:
    payload = {
        "sessionId": "099d59",
        "location": "scripts/analyze_march_etalon.py",
        "message": "march etalon analysis",
        "data": data,
        "timestamp": int(time.time() * 1000),
        "hypothesisId": "E",
        "runId": "march-etalon",
    }
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def main() -> None:
    if LOG_PATH.exists():
        LOG_PATH.unlink()

    paths = {"buh": _latest("buh"), "cost": _latest("cost"), "realization": _latest("realization")}
    dashboard = load_almabi_dashboard_from_exports(
        paths, upload_names={k: v.name for k, v in paths.items()}, logs_dir=None
    )
    cost_node = next(r for r in dashboard["summary_rows"] if r["name"] == "Себестоимость")

    bi: dict[str, float] = {}
    for child in cost_node["children"]:
        value = child["values"]["Факт БУ"][MONTH]
        if value:
            bi[child["name"]] = abs(value)

    print("=== MARCH: ETALON vs BI ===")
    print(f"{'Раздел':<40} {'Эталон':>18} {'BI':>18} {'Δ':>12}")
    deltas: dict[str, float] = {}
    etalon_sum = 0.0
    bi_struct = 0.0
    for etalon_name, etalon_value in ETALON.items():
        bi_name = ETALON_TO_BI.get(etalon_name, etalon_name)
        bi_value = bi.get(bi_name, 0.0)
        delta = bi_value - etalon_value
        deltas[etalon_name] = delta
        etalon_sum += etalon_value
        bi_struct += bi_value
        mark = " *" if abs(delta) > 0.02 else ""
        print(f"{etalon_name:<40} {etalon_value:>18,.2f} {bi_value:>18,.2f} {delta:>+12,.2f}{mark}")

    kpi = abs(cost_node["values"]["Факт БУ"][MONTH])
    gap = bi.get("Вне структуры cost", 0.0)
    children_sum = sum(bi.values())

    print("---")
    print(f"Эталон (структура):     {etalon_sum:>18,.2f}")
    print(f"BI (разделы без gap):   {bi_struct:>18,.2f}")
    print(f"BI «Вне структуры cost»:{gap:>18,.2f}")
    print(f"BI (все дочерние):      {children_sum:>18,.2f}")
    print(f"KPI L1 buh:             {kpi:>18,.2f}")
    print(f"KPI − этalon структура: {kpi - etalon_sum:>+18,.2f}")
    print(f"KPI − BI дочерние:      {kpi - children_sum:>+18,.2f}")

    # Materials delta deep-dive
    if abs(deltas.get("Сырье и материалы", 0)) > 0.02:
        print("\n=== MATERIALS DELTA ANALYSIS ===")
        prepared = _load_cost_prepared_rows(_prepare_raw_rows(read_workbook_rows(paths["cost"]))) or []
        by_article = defaultdict(float)
        for row in prepared:
            if month_name(parse_date_from_text(row.document)) != MONTH:
                continue
            if not is_cost_structure_shipment_document(row.document):
                continue
            sec = _normalize_cost_structure_section(classify_cost_section_pq(row.calc_article, str(row.account)))
            if sec != "Материальные затраты":
                continue
            by_article[row.calc_article or "?"] += float(row.amount or 0)
        for art, amt in sorted(by_article.items(), key=lambda x: -x[1]):
            print(f"  {art}: {amt:,.2f}")

    print("\n=== MARCH: DIRECTIONS BY SECTION ===")
    direction_totals: dict[str, float] = defaultdict(float)
    for section in cost_node["children"]:
        if section["name"] == "Вне структуры cost":
            continue
        sec_total = abs(section["values"]["Факт БУ"].get(MONTH, 0) or 0)
        if not sec_total:
            continue
        print(f"\n{section['name']} — {sec_total:,.2f} ₽")
        dir_rows: list[tuple[str, float]] = []
        for direction in section.get("children") or []:
            value = abs(direction["values"]["Факт БУ"].get(MONTH, 0) or 0)
            if value:
                dir_rows.append((direction["name"], value))
                direction_totals[direction["name"]] += value
        for name, value in sorted(dir_rows, key=lambda x: -x[1]):
            pct = value / sec_total * 100 if sec_total else 0
            print(f"  {value:>16,.2f}  ({pct:5.1f}%)  {name}")

    print("\n=== MARCH: ALL DIRECTIONS (TOTAL) ===")
    grand = sum(direction_totals.values())
    for name, value in sorted(direction_totals.items(), key=lambda x: -x[1]):
        print(f"  {value:>16,.2f}  ({value/grand*100:5.1f}%)  {name}")
    print(f"  {'ИТОГО':>16}  {grand:,.2f}")

    _log(
        {
            "deltas": deltas,
            "etalon_sum": etalon_sum,
            "bi_struct_sum": bi_struct,
            "gap": gap,
            "kpi": kpi,
            "direction_totals": dict(direction_totals),
        }
    )


if __name__ == "__main__":
    main()
