"""Январь: себестоимость по статьям/разделам для экономиста."""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from almabi_dashboard_builder import COST_STRUCTURE_SECTIONS, build_unified_cost_structure_facts
from almabi_pq_cost import build_pq_cost_table
from almabi_test_builder import load_test_dashboard_from_exports
from almabi_test_pipeline import run_test_pipeline

MONTH = "Январь"


def _latest(prefix: str) -> Path:
    return sorted((ROOT / "uploads" / "almabi").glob(f"{prefix}*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True)[0]


def main() -> None:
    paths = {
        "buh": _latest("buh"),
        "cost": _latest("cost"),
        "realization": _latest("realization"),
        "cost_nu": _latest("cost_nu"),
    }
    pipeline = run_test_pipeline(paths, logs_dir=None, write_audit=False)
    dash = load_test_dashboard_from_exports(
        paths,
        upload_names={k: v.name for k, v in paths.items()},
        logs_dir=None,
    )
    cost = next(row for row in dash["summary_rows"] if row["name"] == "Себестоимость")

    pq = pipeline.pq_cost_rows or build_pq_cost_table(paths["cost"], projects_path=paths["realization"])
    buh_facts = [fact for fact in pipeline.result.facts if fact.kpi_l1 == "Себестоимость"]
    unified = build_unified_cost_structure_facts(buh_facts, pq)

    print(f"=== {MONTH}: себестоимость по разделам (как на дашборде) ===")
    print(f"{'Раздел':<42} {'БУ':>18} {'НУ':>18}")
    print("-" * 80)
    for child in cost.get("children") or []:
        bu = float(child["values"]["Факт БУ"].get(MONTH, 0) or 0)
        nu = float(child["values"]["Факт НУ"].get(MONTH, 0) or 0)
        if abs(bu) < 0.01 and abs(nu) < 0.01:
            continue
        print(f"{child['name']:<42} {bu:>18,.2f} {nu:>18,.2f}")
        for sub in child.get("children") or []:
            sub_bu = float(sub["values"]["Факт БУ"].get(MONTH, 0) or 0)
            sub_nu = float(sub["values"]["Факт НУ"].get(MONTH, 0) or 0)
            if abs(sub_bu) < 0.01 and abs(sub_nu) < 0.01:
                continue
            print(f"  {sub['name']:<40} {sub_bu:>18,.2f} {sub_nu:>18,.2f}")

    total_bu = float(cost["values"]["Факт БУ"].get(MONTH, 0) or 0)
    total_nu = float(cost["values"]["Факт НУ"].get(MONTH, 0) or 0)
    print("-" * 80)
    print(f"{'ИТОГО':<42} {total_bu:>18,.2f} {total_nu:>18,.2f}")

    print(f"\n=== {MONTH}: unified cost structure (БУ по разделам) ===")
    by_section = defaultdict(float)
    by_section_nu = defaultdict(float)
    by_section_nom = defaultdict(lambda: defaultdict(float))
    for fact in unified:
        if fact.month != MONTH:
            continue
        section = fact.cost_section or "(без раздела)"
        by_section[section] += float(fact.amount_buh or 0)
        by_section_nu[section] += float(fact.amount_nu or 0)
        label = (fact.nomenclature or fact.expense_article or fact.direction or "—").strip()
        by_section_nom[section][label] += float(fact.amount_buh or 0)

    for section in list(COST_STRUCTURE_SECTIONS) + ["Прочее", "(без раздела)"]:
        if section not in by_section:
            continue
        print(f"\n{section}: БУ {by_section[section]:,.2f} | НУ {by_section_nu[section]:,.2f}")
        items = sorted(by_section_nom[section].items(), key=lambda item: -abs(item[1]))
        for label, amount in items[:12]:
            if abs(amount) < 0.01:
                continue
            print(f"  • {label[:70]} — {amount:,.2f}")

    print(f"\n=== {MONTH}: детализация из PQ cost (статьи калькуляции) ===")
    from almabi_excel_utils import month_name, parse_date_from_text, normalize_text
    from almabi_export_parsers import classify_cost_section_pq

    by_pq_sec: dict[str, float] = defaultdict(float)
    by_pq_sec_nom: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    by_calc_article: dict[str, float] = defaultdict(float)
    for row in pq:
        row_month = month_name(parse_date_from_text(row.get("Дата") or row.get("Документ") or ""))
        if not row_month:
            row_month = normalize_text(row.get("Месяц"))
        if row_month != MONTH:
            continue
        if normalize_text(row.get("Основной раздел")) != "Расходы":
            continue
        calc_article = normalize_text(row.get("Статья калькуляции") or row.get("Вид затрат") or "")
        account = normalize_text(str(row.get("Счет") or row.get("Счёт") or "20"))
        section = classify_cost_section_pq(calc_article, account)
        amount = float(row.get("Сумма") or 0)
        nomenclature = normalize_text(row.get("Номенклатура") or row.get("Продукция") or "—")
        by_pq_sec[section] += amount
        by_pq_sec_nom[section][nomenclature] += amount
        by_calc_article[calc_article or "(без статьи)"] += amount

    print(f"{'Раздел PQ':<42} {'Сумма':>18}")
    print("-" * 62)
    for section, amount in sorted(by_pq_sec.items(), key=lambda item: -abs(item[1])):
        print(f"{section:<42} {amount:>18,.2f}")
        for label, item_amount in sorted(by_pq_sec_nom[section].items(), key=lambda item: -abs(item[1]))[:6]:
            print(f"  • {label[:68]} — {item_amount:,.2f}")
    print("-" * 62)
    print(f"{'ИТОГО PQ':<42} {sum(by_pq_sec.values()):>18,.2f}")

    print(f"\n=== {MONTH}: статьи калькуляции (PQ) ===")
    for article, amount in sorted(by_calc_article.items(), key=lambda item: -abs(item[1])):
        if abs(amount) >= 0.01:
            print(f"  {article}: {amount:,.2f}")


if __name__ == "__main__":
    main()
