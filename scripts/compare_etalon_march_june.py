"""Compare March/June vs etalon; quantify lom and article splits."""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from almabi_dashboard_builder import _normalize_cost_structure_section
from almabi_excel_utils import month_name, parse_date_from_text, read_workbook_rows
from almabi_export_parsers import classify_cost_section_pq
from almabi_pq_common import is_cost_structure_shipment_document
from almabi_pq_cost import _load_cost_prepared_rows, _prepare_raw_rows
from almabi_test_builder import load_almabi_dashboard_from_exports

ETALON = {
    "Март": {
        "Сырье и материалы": 188_537_518.24,
        "Амортизация": 431_444.29,
        "Аренда": 3_095.06,
        "ФОТ": 23_889_518.79,
        "Общепроизводственные расходы": 4_184_422.22,
        "Прочие производственные расходы": 4_419_998.02,
    },
    "Июнь": {
        "Сырье и материалы": 647_948_367.50,
        "Амортизация": 4_753_260.24,
        "Аренда": 1_816_616.75,
        "ФОТ": 59_194_341.89,
        "Общепроизводственные расходы": 3_614_435.29,
        "Прочие производственные расходы": 6_253_417.00,
        "Работы Субподрядчика": 74_980.44,
    },
}
BI_MAP = {
    "Сырье и материалы": "Материальные затраты",
    "Аренда": "Аренда (прямые)",
    "Общепроизводственные расходы": "Общепроизводственные затраты",
    "Работы Субподрядчика": "Прочие производственные расходы",
}


def _latest(prefix: str) -> Path:
    return sorted(Path("uploads/almabi").glob(f"{prefix}-*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True)[0]


def _is_scrap_nomenclature(nomenclature: str) -> bool:
    text = (nomenclature or "").casefold()
    if text.startswith("лом ") or text.startswith("лом."):
        return True
    if "лом черн" in text or "лом цвет" in text:
        return True
    if "лом " in text and "металл" in text:
        return True
    return False


def _pq_rows(month: str, prepared) -> list:
    out = []
    for row in prepared:
        if month_name(parse_date_from_text(row.document)) != month:
            continue
        if not is_cost_structure_shipment_document(row.document):
            continue
        out.append(row)
    return out


def main() -> None:
    paths = {"buh": _latest("buh"), "cost": _latest("cost"), "realization": _latest("realization")}
    prepared = _load_cost_prepared_rows(_prepare_raw_rows(read_workbook_rows(paths["cost"]))) or []
    dashboard = load_almabi_dashboard_from_exports(
        paths, upload_names={k: v.name for k, v in paths.items()}, logs_dir=None
    )
    cost_node = next(r for r in dashboard["summary_rows"] if r["name"] == "Себестоимость")

    for month in ("Март", "Июнь"):
        print(f"\n{'='*70}\n{month}\n{'='*70}")
        bi = {
            c["name"]: abs(c["values"]["Факт БУ"].get(month, 0) or 0)
            for c in cost_node["children"]
            if c["values"]["Факт БУ"].get(month)
        }

        rows = _pq_rows(month, prepared)
        by_calc: dict[str, float] = defaultdict(float)
        syrie_no_lom = 0.0
        lom_in_syrie = 0.0
        lom_lines: list[tuple[str, float]] = []

        for row in rows:
            amount = float(row.amount or 0)
            by_calc[row.calc_article] += amount
            if row.calc_article == "Сырье и материалы" and _is_scrap_nomenclature(row.nomenclature):
                lom_in_syrie += amount
                lom_lines.append((row.nomenclature, amount))
            elif row.calc_article == "Сырье и материалы":
                syrie_no_lom += amount

        materials_bi = by_calc["Сырье и материалы"] + by_calc["Возвратные отходы"] + by_calc.get(
            "Полуфабрикаты производимые в процессе", 0.0
        )
        syrie_only = by_calc["Сырье и материалы"]
        etalon_mat = ETALON[month]["Сырье и материалы"]

        print(f"PQ Сырье и материалы (all):     {syrie_only:>18,.2f}")
        print(f"  из них лом-номенклатура:      {lom_in_syrie:>18,.2f}")
        print(f"  Сырье без лом:                {syrie_no_lom:>18,.2f}")
        print(f"  Возвратные отходы:            {by_calc['Возвратные отходы']:>18,.2f}")
        print(f"  Материальные (3 статьи BI):   {materials_bi:>18,.2f}")
        print(f"Эталон Сырье и материалы:       {etalon_mat:>18,.2f}")
        print(f"Δ BI materials - etalon:        {materials_bi - etalon_mat:>18,.2f}")
        print(f"Δ Сырье без лом - etalon:       {syrie_no_lom - etalon_mat:>18,.2f}")
        print(f"Δ (Сырье без лом + возвр.) - et: {syrie_no_lom + by_calc['Возвратные отходы'] - etalon_mat:>18,.2f}")

        print(f"\n{'Раздел':<40} {'Эталон':>14} {'BI':>14} {'Δ':>12}")
        for name, ev in ETALON[month].items():
            bn = BI_MAP.get(name, name)
            bv = bi.get(bn, 0.0)
            print(f"{name:<40} {ev:>14,.2f} {bv:>14,.2f} {bv-ev:>12,.2f}")

        print("\nСтатьи калкуляции → раздел:")
        for art, val in sorted(by_calc.items(), key=lambda x: -abs(x[1])):
            sec = _normalize_cost_structure_section(classify_cost_section_pq(art, "20"))
            print(f"  {art:42} {val:>14,.2f}  → {sec}")


if __name__ == "__main__":
    main()
