"""June etalon vs BI; where «Лом черных металлов» goes."""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from almabi_excel_utils import month_name, parse_date_from_text, read_workbook_rows
from almabi_export_parsers import classify_cost_section_pq
from almabi_pq_common import is_cost_structure_shipment_document
from almabi_pq_cost import _load_cost_prepared_rows, _prepare_raw_rows
from almabi_test_builder import load_almabi_dashboard_from_exports

ETALON = {
    "Сырье и материалы": 647_948_367.50,
    "Амортизация": 4_753_260.24,
    "Аренда": 1_816_616.75,
    "ФОТ": 59_194_341.89,
    "Общепроизводственные расходы": 3_614_435.29,
    "Прочие производственные расходы": 6_253_417.00,
    "Работы Субподрядчика": 74_980.44,
}
ETALON_TO_BI = {
    "Сырье и материалы": "Материальные затраты",
    "Аренда": "Аренда (прямые)",
    "Общепроизводственные расходы": "Общепроизводственные затраты",
    "Работы Субподрядчика": "Прочие производственные расходы",
}
MONTH = "Июнь"


def _latest(prefix: str) -> Path:
    return sorted(Path("uploads/almabi").glob(f"{prefix}-*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True)[0]


def main() -> None:
    paths = {"buh": _latest("buh"), "cost": _latest("cost"), "realization": _latest("realization")}
    dashboard = load_almabi_dashboard_from_exports(
        paths, upload_names={k: v.name for k, v in paths.items()}, logs_dir=None
    )
    cost = next(r for r in dashboard["summary_rows"] if r["name"] == "Себестоимость")
    bi = {
        c["name"]: abs(c["values"]["Факт БУ"][MONTH])
        for c in cost["children"]
        if c["values"]["Факт БУ"].get(MONTH)
    }

    print(f"=== {MONTH}: эталон vs BI ===")
    for etalon_name, etalon_value in ETALON.items():
        bi_name = ETALON_TO_BI.get(etalon_name, etalon_name)
        bi_value = bi.get(bi_name, 0.0)
        print(f"{etalon_name:40} etalon={etalon_value:>15,.2f} BI={bi_value:>15,.2f} Δ={bi_value - etalon_value:>12,.2f}")

    rows = _load_cost_prepared_rows(_prepare_raw_rows(read_workbook_rows(paths["cost"]))) or []
    by_article: dict[str, float] = defaultdict(float)
    lom_by_article: dict[str, float] = defaultdict(float)
    lom_samples: list[tuple[str, str, float, str]] = []

    for row in rows:
        if month_name(parse_date_from_text(row.document)) != MONTH:
            continue
        if not is_cost_structure_shipment_document(row.document):
            continue
        amount = float(row.amount or 0)
        by_article[row.calc_article] += amount
        nom = row.nomenclature
        if "лом" in nom.casefold() and "металл" in nom.casefold():
            lom_by_article[row.calc_article] += amount
            if len(lom_samples) < 5:
                section = classify_cost_section_pq(row.calc_article, str(row.account))
                lom_samples.append((nom, row.calc_article, amount, section))

    materials_three = (
        by_article["Сырье и материалы"]
        + by_article["Возвратные отходы"]
        + by_article.get("Полуфабрикаты производимые в процессе", 0.0)
    )

    print(f"\n=== {MONTH} PQ (Реализация): статьи калькуляции ===")
    for name, value in sorted(by_article.items(), key=lambda item: -abs(item[1])):
        section = classify_cost_section_pq(name, "20")
        print(f"  {name:45} {value:>15,.2f}  → {section}")
    print(f"\n  Итого «материальные» (3 статьи): {materials_three:,.2f}")

    print(f"\n=== Номенклатура с «лом» + «металл» ({MONTH}) ===")
    for art, val in sorted(lom_by_article.items(), key=lambda item: -abs(item[1])):
        print(f"  статья калькуляции «{art}»: {val:,.2f}  → {classify_cost_section_pq(art, '20')}")
    print(f"  ИТОГО лом-металл: {sum(lom_by_article.values()):,.2f}")

    print("\n=== Примеры строк ===")
    for nom, art, amount, section in lom_samples:
        print(f"  {nom[:65]}")
        print(f"    статья: {art} | сумма: {amount:,.2f} | раздел BI: {section}")


if __name__ == "__main__":
    main()
