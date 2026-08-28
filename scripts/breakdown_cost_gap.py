"""Break down «Вне структуры» = KPI buh − PQ structure (Реализация only)."""
from __future__ import annotations

import json
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from almabi_dashboard_builder import build_cost_structure_facts_from_pq_rows
from almabi_excel_utils import month_name, normalize_text, parse_date_from_text
from almabi_pq_common import is_cost_structure_shipment_document
from almabi_pq_cost import build_pq_cost_table, _load_cost_prepared_rows, _prepare_raw_rows
from almabi_excel_utils import read_workbook_rows
from almabi_test_pipeline import run_test_pipeline

LOG_PATH = Path("debug-099d59.log")
MONTH = "Март"


def _log(data: dict) -> None:
    payload = {
        "sessionId": "099d59",
        "location": "scripts/breakdown_cost_gap.py",
        "message": "gap breakdown",
        "data": data,
        "timestamp": int(time.time() * 1000),
        "hypothesisId": "H2",
        "runId": "gap-breakdown",
    }
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _latest(prefix: str) -> Path:
    return sorted(Path("uploads/almabi").glob(f"{prefix}-*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True)[0]


def main() -> None:
    paths = {"buh": _latest("buh"), "cost": _latest("cost"), "realization": _latest("realization")}
    pipeline = run_test_pipeline(paths, logs_dir=None, write_audit=False)
    facts = pipeline.result.facts

    buh_march = sum(f.amount_buh for f in facts if f.kpi_l1 == "Себестоимость" and f.month == MONTH)
    structure_facts = build_cost_structure_facts_from_pq_rows(pipeline.pq_cost_rows or [])
    struct_march = sum(f.amount_buh for f in structure_facts if f.month == MONTH)
    gap = buh_march - struct_march

    print(f"=== {MONTH}: сверка верхнего уровня ===")
    print(f"KPI L1 «Себестоимость» (buh):     {buh_march:>18,.2f}")
    print(f"Сумма разделов PQ (Реализация):   {struct_march:>18,.2f}")
    print(f"«Вне структуры» (разница):        {gap:>18,.2f}")
    print(f"Проверка (структура + вне):       {struct_march + gap:>18,.2f}")

    # Buh cost lines in March grouped by document prefix
    buh_by_doc: dict[str, float] = defaultdict(float)
    for f in facts:
        if f.kpi_l1 != "Себестоимость" or f.month != MONTH:
            continue
        doc = normalize_text(getattr(f, "contract", ""))  # often empty
        # use expense_article / nomenclature as hint — document not on Fact always
        key = f.cost_section or "(без раздела)"
        buh_by_doc[key] += f.amount_buh

    print(f"\n=== Buh себестоимость {MONTH} по cost_section ===")
    for name, amount in sorted(buh_by_doc.items(), key=lambda x: x[1]):
        print(f"  {name:<40} {amount:>15,.2f}")

    # Raw cost file: non-realization docs in March
    prepared = _load_cost_prepared_rows(_prepare_raw_rows(read_workbook_rows(paths["cost"]))) or []
    non_ship: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for row in prepared:
        month = month_name(parse_date_from_text(row.document))
        if month != MONTH:
            continue
        if is_cost_structure_shipment_document(row.document):
            continue
        doc_key = row.document.split(" от ")[0].strip()
        non_ship[doc_key][row.section] += float(row.amount or 0)

    print(f"\n=== Cost-файл: документы НЕ «Реализация» ({MONTH}) ===")
    total_non_ship = 0.0
    for doc, sections in sorted(non_ship.items(), key=lambda x: -sum(x[1].values())):
        doc_total = sum(sections.values())
        total_non_ship += doc_total
        print(f"  {doc}: {doc_total:,.2f}")
        for sec, val in sorted(sections.items(), key=lambda x: -x[1]):
            print(f"      {sec}: {val:,.2f}")
    print(f"  ИТОГО не-Реализация: {total_non_ship:,.2f}")

    # PQ rows excluded from structure (all expense rows, any month filter March)
    pq = pipeline.pq_cost_rows or []
    excluded: dict[str, float] = defaultdict(float)
    for row in pq:
        if normalize_text(row.get("Основной раздел")) != "Расходы":
            continue
        month = month_name(parse_date_from_text(row.get("Документ")))
        if month != MONTH:
            continue
        if is_cost_structure_shipment_document(row.get("Документ")):
            continue
        doc = str(row.get("Документ") or "").split(" от ")[0]
        excluded[doc] += float(row.get("Сумма") or 0)

    print(f"\n=== PQ «Расходы» без «Реализация» ({MONTH}) ===")
    ex_total = 0.0
    for doc, val in sorted(excluded.items(), key=lambda x: -x[1]):
        ex_total += val
        print(f"  {doc}: {val:,.2f}")
    print(f"  ИТОГО: {ex_total:,.2f}")

    _log(
        {
            "month": MONTH,
            "buh_l1": buh_march,
            "pq_structure": struct_march,
            "gap": gap,
            "non_shipment_cost_file": total_non_ship,
            "pq_excluded": ex_total,
        }
    )


if __name__ == "__main__":
    main()
