"""Diagnose «Разница buh / cost» = KPI L1 buh − PQ structure sum."""
from __future__ import annotations

import json
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from almabi_dashboard_builder import build_cost_structure_facts_from_pq_rows
from almabi_excel_utils import month_name, normalize_text, parse_date_from_text
from almabi_pq_common import is_black_metal_scrap_nomenclature, should_include_in_cost_tree
from almabi_pq_cost import build_pq_cost_table
from almabi_test_builder import load_almabi_dashboard_from_exports
from almabi_test_pipeline import run_test_pipeline

LOG_PATH = Path("debug-099d59.log")
MONTHS = ("Март", "Июнь")


def _latest(prefix: str) -> Path:
    return sorted(Path("uploads/almabi").glob(f"{prefix}-*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True)[0]


def _log(message: str, data: dict, hypothesis_id: str) -> None:
    payload = {
        "sessionId": "099d59",
        "location": "scripts/diagnose_cost_gap.py",
        "message": message,
        "data": data,
        "timestamp": int(time.time() * 1000),
        "hypothesisId": hypothesis_id,
        "runId": "gap-diagnosis",
    }
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def main() -> None:
    paths = {"buh": _latest("buh"), "cost": _latest("cost"), "realization": _latest("realization")}
    pipeline = run_test_pipeline(paths, logs_dir=None, write_audit=False)
    pq = pipeline.pq_cost_rows or build_pq_cost_table(paths["cost"], projects_path=paths["realization"])
    structure = build_cost_structure_facts_from_pq_rows(pq)
    dashboard = load_almabi_dashboard_from_exports(
        paths, upload_names={k: v.name for k, v in paths.items()}, logs_dir=None
    )
    cost_node = next(r for r in dashboard["summary_rows"] if r["name"] == "Себестоимость")
    prochee = next((c for c in cost_node["children"] if c["name"] == "Прочее"), None)

    buh_facts = [f for f in pipeline.result.facts if f.kpi_l1 == "Себестоимость"]

    for month in MONTHS:
        buh_l1 = float(cost_node["values"]["Факт БУ"].get(month, 0) or 0)
        struct_sum = sum(f.amount_buh for f in structure if f.month == month)
        l2_sum = sum(
            float(c["values"]["Факт БУ"].get(month, 0) or 0)
            for c in cost_node["children"]
            if c["name"] != "Прочее"
        )
        gap_ui = float(prochee["values"]["Факт БУ"].get(month, 0) or 0) if prochee else 0.0
        buh_facts_sum = sum(f.amount_buh for f in buh_facts if f.month == month)

        # PQ totals for tree-eligible rows
        pq_tree_total = 0.0
        pq_by_doc: dict[str, float] = defaultdict(float)
        for row in pq:
            if normalize_text(row.get("Основной раздел")) != "Расходы":
                continue
            if month_name(parse_date_from_text(row.get("Документ"))) != month:
                continue
            if not should_include_in_cost_tree(
                document=row.get("Документ"), nomenclature=row.get("Номенклатура")
            ):
                continue
            amount = float(row.get("Сумма") or 0)
            if not amount:
                continue
            pq_tree_total -= amount
            doc_key = normalize_text(row.get("Документ")).split(" от ")[0][:40]
            pq_by_doc[doc_key] -= amount

        # Buh facts not represented in structure (by nomenclature+doc rough match)
        struct_keys = {
            (
                (f.nomenclature or "").casefold(),
                round(f.amount_buh, 2),
            )
            for f in structure
            if f.month == month
        }
        buh_only: list[dict] = []
        for f in buh_facts:
            if f.month != month:
                continue
            key = ((f.nomenclature or "").casefold(), round(f.amount_buh, 2))
            if key not in struct_keys:
                buh_only.append(
                    {
                        "nomenclature": f.nomenclature,
                        "amount_buh": f.amount_buh,
                        "cost_section": f.cost_section,
                        "direction": f.direction,
                    }
                )

        struct_only = []
        buh_keys = {
            ((f.nomenclature or "").casefold(), round(f.amount_buh, 2))
            for f in buh_facts
            if f.month == month
        }
        for f in structure:
            if f.month != month:
                continue
            key = ((f.nomenclature or "").casefold(), round(f.amount_buh, 2))
            if key not in buh_keys:
                struct_only.append(
                    {
                        "nomenclature": f.nomenclature,
                        "amount_buh": f.amount_buh,
                        "cost_section": f.cost_section,
                        "direction": f.direction or "Без направления",
                    }
                )

        black_buh = sum(
            f.amount_buh
            for f in buh_facts
            if f.month == month and is_black_metal_scrap_nomenclature(f.nomenclature)
        )

        print(f"\n=== {month} ===")
        print(f"  KPI L1 (node):           {buh_l1:>18,.2f}")
        print(f"  Buh facts sum:           {buh_facts_sum:>18,.2f}")
        print(f"  Structure facts sum:     {struct_sum:>18,.2f}")
        print(f"  L2 children (no Прочее): {l2_sum:>18,.2f}")
        print(f"  Gap (Прочее UI):         {gap_ui:>18,.2f}")
        print(f"  Computed L1 − structure: {buh_l1 - struct_sum:>18,.2f}")
        print(f"  PQ tree raw total:       {pq_tree_total:>18,.2f}")
        print(f"  Black scrap in buh facts:{black_buh:>18,.2f}")
        print(f"  Buh-only lines (sample): {len(buh_only)}")
        for item in sorted(buh_only, key=lambda x: abs(x["amount_buh"]), reverse=True)[:5]:
            print(f"    {item['amount_buh']:>14,.2f}  {item['nomenclature'][:60]}")
        print(f"  Structure-only (sample): {len(struct_only)}")
        for item in sorted(struct_only, key=lambda x: abs(x["amount_buh"]), reverse=True)[:5]:
            print(f"    {item['amount_buh']:>14,.2f}  {item['nomenclature'][:60]}")

        _log(
            f"{month} gap breakdown",
            {
                "month": month,
                "buh_l1": buh_l1,
                "buh_facts_sum": buh_facts_sum,
                "structure_sum": struct_sum,
                "gap_ui": gap_ui,
                "computed_gap": buh_l1 - struct_sum,
                "black_scrap_buh": black_buh,
                "buh_only_count": len(buh_only),
                "struct_only_count": len(struct_only),
                "top_struct_only": struct_only[:3],
                "top_buh_only": buh_only[:3],
            },
            "A-E",
        )


if __name__ == "__main__":
    main()
