"""Monthly cost sections (without gap) + gap explanation per month."""
from __future__ import annotations

import json
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from almabi_dashboard_builder import COST_STRUCTURE_SECTIONS, build_cost_structure_facts_from_pq_rows
from almabi_excel_utils import month_name, normalize_text, parse_date_from_text
from almabi_mock_data import MONTHS
from almabi_pq_common import is_black_metal_scrap_nomenclature
from almabi_pq_cost import build_pq_cost_table
from almabi_test_builder import load_almabi_dashboard_from_exports
from almabi_test_pipeline import run_test_pipeline

LOG_PATH = Path("debug-099d59.log")


def _latest(prefix: str) -> Path:
    return sorted(Path("uploads/almabi").glob(f"{prefix}-*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True)[0]


def _log(message: str, data: dict) -> None:
    payload = {
        "sessionId": "099d59",
        "location": "scripts/monthly_cost_sections_and_gap.py",
        "message": message,
        "data": data,
        "timestamp": int(time.time() * 1000),
        "hypothesisId": "monthly-report",
        "runId": "monthly-sections-gap",
    }
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _money(v: float) -> str:
    return f"{v:,.2f}".replace(",", " ")


def main() -> None:
    paths = {"buh": _latest("buh"), "cost": _latest("cost"), "realization": _latest("realization")}
    pipeline = run_test_pipeline(paths, logs_dir=None, write_audit=False)
    pq = pipeline.pq_cost_rows or build_pq_cost_table(paths["cost"], projects_path=paths["realization"])
    structure = build_cost_structure_facts_from_pq_rows(pq)
    dashboard = load_almabi_dashboard_from_exports(
        paths, upload_names={k: v.name for k, v in paths.items()}, logs_dir=None
    )
    cost_node = next(r for r in dashboard["summary_rows"] if r["name"] == "Себестоимость")
    buh_facts = [f for f in pipeline.result.facts if f.kpi_l1 == "Себестоимость"]

    # Verify black scrap exclusion
    black_buh = sum(f.amount_buh for f in buh_facts if is_black_metal_scrap_nomenclature(f.nomenclature))
    black_struct = sum(
        f.amount_buh for f in structure if is_black_metal_scrap_nomenclature(f.nomenclature)
    )
    black_pq_expense = sum(
        float(row.get("Сумма") or 0)
        for row in pq
        if normalize_text(row.get("Основной раздел")) == "Расходы"
        and is_black_metal_scrap_nomenclature(row.get("Номенклатура"))
    )
    print("=== Проверка: лом чёрных металлов ===")
    print(f"  В buh-фактах себестоимости:     {_money(black_buh)}")
    print(f"  В PQ-структуре (дерево):        {_money(black_struct)}")
    print(f"  В PQ cost (Расходы, сырьё):     {_money(black_pq_expense)} (не в дереве)")
    print(f"  Исключён из себестoимости BI:   {'ДА' if abs(black_buh) < 0.01 and abs(black_struct) < 0.01 else 'НЕТ'}")
    print()

    prochee = next((c for c in cost_node["children"] if c["name"] == "Прочее"), None)

    # Aggregate buh/structure by month + nomenclature
    buh_by_month_nom: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    struct_by_month_nom: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for f in buh_facts:
        if is_black_metal_scrap_nomenclature(f.nomenclature):
            continue
        buh_by_month_nom[f.month][(f.nomenclature or "—").strip()] += f.amount_buh
    for f in structure:
        if is_black_metal_scrap_nomenclature(f.nomenclature):
            continue
        struct_by_month_nom[f.month][(f.nomenclature or "—").strip()] += f.amount_buh

    report: dict[str, dict] = {}

    for month in MONTHS:
        buh_l1 = float(cost_node["values"]["Факт БУ"].get(month, 0) or 0)
        sections: dict[str, float] = {}
        for child in cost_node["children"]:
            if child["name"] == "Прочее":
                continue
            val = float(child["values"]["Факт БУ"].get(month, 0) or 0)
            if abs(val) > 0.005:
                sections[child["name"]] = val
        struct_total = sum(sections.values())
        gap = float(prochee["values"]["Факт БУ"].get(month, 0) or 0) if prochee else buh_l1 - struct_total

        buh_noms = buh_by_month_nom[month]
        struct_noms = struct_by_month_nom[month]
        all_noms = set(buh_noms) | set(struct_noms)
        buh_only: list[dict] = []
        struct_only: list[dict] = []
        for nom in all_noms:
            b = buh_noms.get(nom, 0.0)
            s = struct_noms.get(nom, 0.0)
            d = b - s
            if abs(d) < 0.005:
                continue
            if abs(b) < 0.005:
                struct_only.append({"nomenclature": nom, "amount": s, "delta": d})
            elif abs(s) < 0.005:
                buh_only.append({"nomenclature": nom, "amount": b, "delta": d})
            else:
                # same nom, different split — show net delta
                buh_only.append({"nomenclature": f"{nom} (buh≠PQ сумма)", "amount": b, "delta": d})
                struct_only.append({"nomenclature": f"{nom} (buh≠PQ сумма)", "amount": s, "delta": -d})

        buh_only.sort(key=lambda x: -abs(x["delta"]))
        struct_only.sort(key=lambda x: -abs(x["delta"]))
        net_buh_only = sum(x["delta"] for x in buh_only if abs(x["amount"]) > 0.005 and "buh≠PQ" not in x["nomenclature"])
        net_struct_only = sum(-x["delta"] for x in struct_only if abs(x["amount"]) > 0.005 and "buh≠PQ" not in x["nomenclature"])

        report[month] = {
            "buh_l1": buh_l1,
            "sections": sections,
            "struct_total": struct_total,
            "gap": gap,
            "buh_only_top": buh_only[:5],
            "struct_only_top": struct_only[:5],
        }

        if not any(abs(v) > 0.005 for v in sections.values()) and abs(gap) < 0.005 and abs(buh_l1) < 0.005:
            continue

        print(f"=== {month} ===")
        print(f"  KPI L1 (buh):           {_money(buh_l1)}")
        print(f"  Σ разделов (без gap):   {_money(struct_total)}")
        print(f"  Разница (Прочее):       {_money(gap)}")
        print("  Статьи (PQ-структура, без «Разница buh/cost»):")
        for name in COST_STRUCTURE_SECTIONS:
            val = sections.get(name, 0.0)
            if abs(val) > 0.005:
                print(f"    {name}: {_money(val)}")
        for name, val in sections.items():
            if name not in COST_STRUCTURE_SECTIONS and abs(val) > 0.005:
                print(f"    {name}: {_money(val)}")

        if abs(gap) > 0.005:
            print("  Что даёт разницу (без лома чёрных металлов):")
            explained = 0.0
            for item in buh_only:
                if abs(item["delta"]) < 0.005:
                    continue
                if abs(item["amount"]) < 0.005:
                    continue
                print(f"    + только buh: {item['nomenclature'][:72]} → {_money(item['delta'])}")
                explained += item["delta"]
            for item in struct_only:
                if abs(item["amount"]) < 0.005:
                    continue
                print(f"    − только PQ:  {item['nomenclature'][:72]} → {_money(-item['delta'])}")
                explained += -item["delta"]
            # Show net orphan lines (clean list)
            orphans_buh = [x for x in buh_only if abs(x["amount"]) > 0.005 and "buh≠PQ" not in x["nomenclature"]]
            orphans_pq = [x for x in struct_only if abs(x["amount"]) > 0.005 and "buh≠PQ" not in x["nomenclature"]]
            if orphans_buh or orphans_pq:
                print("  Итого по «сиротам» (нет пары в другом источнике):")
                for item in orphans_buh:
                    print(f"    buh: {item['nomenclature'][:70]} = {_money(item['amount'])}")
                for item in orphans_pq:
                    print(f"    PQ:  {item['nomenclature'][:70]} = {_money(item['amount'])}")
        print()

        _log(
            f"{month} sections and gap",
            {
                "month": month,
                "buh_l1": buh_l1,
                "struct_total": struct_total,
                "gap": gap,
                "sections": sections,
                "buh_only": orphans_buh if abs(gap) > 0.005 else [],
                "struct_only": orphans_pq if abs(gap) > 0.005 else [],
            },
        )

    # Summary table
    print("=== Сводка: разделы без gap (|сумма| по месяцам) ===")
    header = ["Раздел"] + [m[:3] for m in MONTHS]
    print(" | ".join(f"{h:>12}" for h in header))
    for sec in list(COST_STRUCTURE_SECTIONS):
        row = [sec[:12]]
        for month in MONTHS:
            val = report.get(month, {}).get("sections", {}).get(sec, 0.0)
            row.append(_money(abs(val)) if abs(val) > 0.005 else "—")
        print(" | ".join(f"{c:>12}" for c in row))
    print()
    gap_row = ["Прочее/gap"]
    for month in MONTHS:
        g = report.get(month, {}).get("gap", 0.0)
        gap_row.append(_money(g) if abs(g) > 0.005 else "—")
    print(" | ".join(f"{c:>12}" for c in gap_row))


if __name__ == "__main__":
    main()
