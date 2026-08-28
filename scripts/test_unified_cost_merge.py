"""Test unified buh+PQ merge vs current L1/structure; colored scrap by month."""
from __future__ import annotations

import json
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from almabi_dashboard_builder import COST_STRUCTURE_SECTIONS, build_cost_structure_facts_from_pq_rows
from almabi_excel_utils import month_name, normalize_text, parse_date_from_text
from almabi_export_parsers import classify_cost_section_pq
from almabi_mock_data import MONTHS
from almabi_pipeline import Fact
from almabi_pq_common import is_black_metal_scrap_nomenclature, should_include_in_cost_tree
from almabi_pq_cost import build_pq_cost_table
from almabi_test_builder import load_almabi_dashboard_from_exports
from almabi_test_pipeline import run_test_pipeline

LOG_PATH = Path("debug-099d59.log")


def _latest(prefix: str) -> Path:
    return sorted(Path("uploads/almabi").glob(f"{prefix}-*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True)[0]


def _log(message: str, data: dict) -> None:
    payload = {
        "sessionId": "099d59",
        "location": "scripts/test_unified_cost_merge.py",
        "message": message,
        "data": data,
        "timestamp": int(time.time() * 1000),
        "hypothesisId": "unified-merge",
        "runId": "unified-cost-test",
    }
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def is_colored_metal_scrap(nomenclature: object) -> bool:
    if is_black_metal_scrap_nomenclature(nomenclature):
        return False
    text = normalize_text(nomenclature).casefold()
    return "лом" in text and "цветн" in text


def _money(v: float) -> str:
    return f"{abs(v):,.2f}".replace(",", " ")


def _buh_section(fact: Fact) -> str:
    section = normalize_text(fact.cost_section)
    if section:
        return section
    article = normalize_text(fact.expense_article)
    if article:
        mapped = classify_cost_section_pq(article, "20")
        if mapped:
            return mapped
    return "Общепроизводственные затраты"


def build_unified_structure_facts(
    buh_facts: list[Fact],
    pq_facts: list[Fact],
) -> list[Fact]:
    """PQ-разбивка где есть совпадение по номенклатуре+месяц; buh-only / PQ-only без дубля суммы."""
    pq_groups: dict[tuple[str, str], list[Fact]] = defaultdict(list)
    for fact in pq_facts:
        key = (fact.month, normalize_text(fact.nomenclature).casefold())
        pq_groups[key].append(fact)

    buh_groups: dict[tuple[str, str], list[Fact]] = defaultdict(list)
    for fact in buh_facts:
        if is_black_metal_scrap_nomenclature(fact.nomenclature):
            continue
        key = (fact.month, normalize_text(fact.nomenclature).casefold())
        buh_groups[key].append(fact)

    unified: list[Fact] = []
    all_keys = set(pq_groups) | set(buh_groups)

    for key in all_keys:
        pq_items = pq_groups.get(key, [])
        buh_items = buh_groups.get(key, [])
        pq_total = sum(f.amount_buh for f in pq_items)
        buh_total = sum(f.amount_buh for f in buh_items)

        if pq_items and buh_items and abs(pq_total - buh_total) <= 0.05:
            unified.extend(pq_items)
            continue
        if pq_items and not buh_items:
            unified.extend(pq_items)
            continue
        if buh_items and not pq_items:
            for fact in buh_items:
                unified.append(
                    Fact(
                        kpi_l1=fact.kpi_l1,
                        month=fact.month,
                        amount_buh=fact.amount_buh,
                        amount_nu=fact.amount_nu,
                        direction=fact.direction,
                        project_group=fact.project_group,
                        project=fact.project,
                        nomenclature=fact.nomenclature,
                        cost_section=_buh_section(fact),
                    )
                )
            continue
        # Оба есть, суммы разные: buh — источник L1, PQ — детализация если |PQ|<=|buh|
        if pq_items and buh_items:
            if abs(pq_total) <= abs(buh_total) + 0.05:
                unified.extend(pq_items)
                residual = buh_total - pq_total
                if abs(residual) > 0.05:
                    sample = buh_items[0]
                    unified.append(
                        Fact(
                            kpi_l1=sample.kpi_l1,
                            month=sample.month,
                            amount_buh=residual,
                            amount_nu=residual,
                            direction=sample.direction,
                            project_group=sample.project_group,
                            project=sample.project,
                            nomenclature=sample.nomenclature,
                            cost_section=_buh_section(sample),
                        )
                    )
            else:
                for fact in buh_items:
                    unified.append(
                        Fact(
                            kpi_l1=fact.kpi_l1,
                            month=fact.month,
                            amount_buh=fact.amount_buh,
                            amount_nu=fact.amount_nu,
                            direction=fact.direction,
                            project_group=fact.project_group,
                            project=fact.project,
                            nomenclature=fact.nomenclature,
                            cost_section=_buh_section(fact),
                        )
                    )
    return unified


def _section_totals(facts: list[Fact], month: str) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    for fact in facts:
        if fact.month != month:
            continue
        section = normalize_text(fact.cost_section) or "Общепроизводственные затраты"
        totals[section] += fact.amount_buh
    return dict(totals)


def main() -> None:
    paths = {"buh": _latest("buh"), "cost": _latest("cost"), "realization": _latest("realization")}
    pipeline = run_test_pipeline(paths, logs_dir=None, write_audit=False)
    pq_rows = pipeline.pq_cost_rows or build_pq_cost_table(paths["cost"], projects_path=paths["realization"])
    pq_structure = build_cost_structure_facts_from_pq_rows(pq_rows)
    buh_cost = [
        f
        for f in pipeline.result.facts
        if f.kpi_l1 == "Себестоимость" and not is_black_metal_scrap_nomenclature(f.nomenclature)
    ]
    unified = build_unified_structure_facts(buh_cost, pq_structure)

    dashboard = load_almabi_dashboard_from_exports(
        paths, upload_names={k: v.name for k, v in paths.items()}, logs_dir=None
    )
    cost_node = next(r for r in dashboard["summary_rows"] if r["name"] == "Себестоимость")
    prochee = next((c for c in cost_node["children"] if c["name"] == "Прочее"), None)

    print("=" * 72)
    print("ПОЧЕМУ СЕЙЧАС ДВА ИСТОЧНИКА")
    print("=" * 72)
    print("  L1 KPI  = бухрегистр (90.02.1) — официальная сумма P&L.")
    print("  Дерево  = файл себестоимости (PQ) — разбивка по статьям/направлениям.")
    print("  «Прочее» = buh − PQ, когда строки не совпадают 1:1.")
    print()
    print("  Единая модель возможна: PQ-детализация + buh-only строки без дубля")
    print("  (тест ниже). Тогда gap → 0, L1 остаётся buh.")
    print()

    # Black + colored scrap verification
    black_buh = sum(f.amount_buh for f in pipeline.result.facts if f.kpi_l1 == "Себестоимость" and is_black_metal_scrap_nomenclature(f.nomenclature))
    black_pq_raw = sum(
        float(r.get("Сумма") or 0)
        for r in pq_rows
        if normalize_text(r.get("Основной раздел")) == "Расходы"
        and is_black_metal_scrap_nomenclature(r.get("Номенклатура"))
    )
    print("=" * 72)
    print("ЛОМ ЧЁРНЫХ МЕТАЛЛОВ — не в себестoимости BI")
    print("=" * 72)
    print(f"  buh-факты: {black_buh:,.2f}  |  PQ raw (не в дереве): {black_pq_raw:,.2f}")
    print()

    print("=" * 72)
    print("ЛОМ ЦВЕТНЫХ МЕТАЛЛОВ — по месяцам")
    print("=" * 72)
    print(f"{'Месяц':<10} {'PQ cost':>14} {'В дереве PQ':>14} {'buh L1':>14} {'В gap?':>8}  Куда")
    for month in MONTHS:
        pq_amt = 0.0
        for row in pq_rows:
            if normalize_text(row.get("Основной раздел")) != "Расходы":
                continue
            if month_name(parse_date_from_text(row.get("Документ"))) != month:
                continue
            if not is_colored_metal_scrap(row.get("Номенклатура")):
                continue
            if should_include_in_cost_tree(document=row.get("Документ"), nomenclature=row.get("Номенклатура")):
                pq_amt += float(row.get("Сумма") or 0)
        struct_amt = abs(
            sum(f.amount_buh for f in pq_structure if f.month == month and is_colored_metal_scrap(f.nomenclature))
        )
        buh_amt = abs(
            sum(f.amount_buh for f in buh_cost if f.month == month and is_colored_metal_scrap(f.nomenclature))
        )
        in_gap = struct_amt > 0.01 and buh_amt < 0.01
        if pq_amt < 0.01 and struct_amt < 0.01 and buh_amt < 0.01:
            continue
        where = "Материальные затраты (PQ-дерево)" if struct_amt > 0.01 else "—"
        gap_flag = "ДА" if in_gap else ("нет" if buh_amt > 0.01 else "—")
        print(
            f"{month:<10} {_money(pq_amt):>14} {_money(struct_amt):>14} {_money(buh_amt):>14} {gap_flag:>8}  {where}"
            + (" → только PQ, в «Прочее»" if in_gap else (" → в L1+buh" if buh_amt > 0.01 else ""))
        )
    print("  Учитывается: ДА в PQ-структуре (материалы). В buh L1 — только если есть строка buh.")
    print("  Лом чёрных — НЕ учитывается нигде в BI.")
    print()

    print("=" * 72)
    print("СРАВНЕНИЕ: L1 buh | текущее PQ-дерево | unified (PQ+buh без дубля) | gap")
    print("=" * 72)
    print(
        f"{'Месяц':<10} {'L1 buh':>16} {'PQ struct':>16} {'Unified Σ':>16} {'Gap сейчас':>14} {'Unified−L1':>14}"
    )
    report_rows = []
    for month in MONTHS:
        l1 = float(cost_node["values"]["Факт БУ"].get(month, 0) or 0)
        current_sections = sum(
            float(c["values"]["Факт БУ"].get(month, 0) or 0)
            for c in cost_node["children"]
            if c["name"] != "Прочее"
        )
        unified_total = sum(f.amount_buh for f in unified if f.month == month)
        gap = float(prochee["values"]["Факт БУ"].get(month, 0) or 0) if prochee else l1 - current_sections
        unified_delta = l1 - unified_total
        if abs(l1) < 0.01 and abs(current_sections) < 0.01:
            continue
        print(
            f"{month:<10} {_money(l1):>16} {_money(current_sections):>16} {_money(unified_total):>16} "
            f"{gap:>14,.2f} {unified_delta:>14,.2f}"
        )
        report_rows.append(
            {
                "month": month,
                "l1_buh": l1,
                "pq_structure": current_sections,
                "unified_total": unified_total,
                "gap_current": gap,
                "unified_minus_l1": unified_delta,
                "sections_unified": _section_totals(unified, month),
                "sections_current": {
                    c["name"]: float(c["values"]["Факт БУ"].get(month, 0) or 0)
                    for c in cost_node["children"]
                    if c["name"] != "Прочее" and abs(float(c["values"]["Факт БУ"].get(month, 0) or 0)) > 0.005
                },
            }
        )

    print()
    print("=" * 72)
    print("UNIFIED — статьи по месяцам (|сумма|, без gap)")
    print("=" * 72)
    for row in report_rows:
        month = row["month"]
        print(f"\n--- {month} (unified Σ = {_money(row['unified_total'])}, L1 = {_money(row['l1_buh'])}) ---")
        secs = row["sections_unified"]
        for name in COST_STRUCTURE_SECTIONS:
            val = secs.get(name, 0.0)
            if abs(val) > 0.005:
                cur = row["sections_current"].get(name, 0.0)
                delta = val - cur
                note = f"  (было PQ {_money(cur)}" + (f", Δ {_money(delta)})" if abs(delta) > 0.01 else ")")
                print(f"  {name}: {_money(val)}{note}")

    _log("unified merge comparison", {"rows": report_rows, "black_scrap_excluded_buh": black_buh})


if __name__ == "__main__":
    main()
