"""Trace March amortization: pipeline vs raw cost vs buh (debug session 099d59)."""
from __future__ import annotations

import json
import time
from collections import defaultdict
from pathlib import Path

from almabi_dashboard_builder import _chart_cost_structure
from almabi_export_parsers import classify_buh_section, classify_cost_section_pq, parse_exports
from almabi_pq_common import build_cost_pq_lookup, lookup_cost_pq_rows
from almabi_pq_cost import _load_cost_prepared_rows, _prepare_raw_rows, build_pq_cost_table
from almabi_excel_utils import read_workbook_rows
from almabi_test_pipeline import build_test_facts, _pq_cost_section, _cost_row_from_pq_dict

LOG_PATH = Path("debug-099d59.log")
MONTH = "Март"
UPLOAD_DIR = Path("uploads/almabi")


def _log(message: str, data: dict, hypothesis_id: str) -> None:
    payload = {
        "sessionId": "099d59",
        "location": "scripts/trace_march_amortization.py",
        "message": message,
        "data": data,
        "timestamp": int(time.time() * 1000),
        "hypothesisId": hypothesis_id,
        "runId": "march-amort",
    }
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _latest(prefix: str) -> Path:
    files = sorted(UPLOAD_DIR.glob(f"{prefix}-*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        raise SystemExit(f"No {prefix} uploads found")
    return files[0]


def _month_from_document(document: str) -> str | None:
    doc = document or ""
    for month, token in (
        ("Январь", ".01."),
        ("Февраль", ".02."),
        ("Март", ".03."),
        ("Апрель", ".04."),
        ("Май", ".05."),
        ("Июнь", ".06."),
        ("Июль", ".07."),
        ("Август", ".08."),
        ("Сентябрь", ".09."),
        ("Октябрь", ".10."),
        ("Ноябрь", ".11."),
        ("Декабрь", ".12."),
    ):
        if token in doc:
            return month
    return None


def main() -> None:
    if LOG_PATH.exists():
        LOG_PATH.unlink()

    buh_path = _latest("buh")
    cost_path = _latest("cost")
    real_path = _latest("realization")
    paths = {"buh": buh_path, "cost": cost_path, "realization": real_path}

    exports = parse_exports(paths)
    result = build_test_facts(exports, cost_path=cost_path, projects_path=real_path)
    chart = _chart_cost_structure(result.facts)
    march_chart = next(item for item in chart["by_month"] if item["month"] == "Мар.")
    dashboard_amort = march_chart["sections"]["Амортизация"]

    pq_rows = build_pq_cost_table(cost_path, projects_path=real_path)
    cost_by_full, cost_by_doc = build_cost_pq_lookup(pq_rows)

    cost_amort_march = [
        r
        for r in pq_rows
        if r.get("Раздел") == "Амортизация"
        and _month_from_document(str(r.get("Документ") or "")) == MONTH
    ]
    cost_amort_march_sum = sum(float(r.get("Сумма") or 0) for r in cost_amort_march)

    # Pipeline-like allocation for March buh cost rows
    buh_march_by_section: dict[str, float] = defaultdict(float)
    buh_march_no_join = 0.0
    buh_march_joined_not_amort: dict[str, float] = defaultdict(float)
    for row in exports.buh:
        if row.month != MONTH:
            continue
        if classify_buh_section(row.account_dt, row.account_kt) != "Себестоимость":
            continue
        matches = lookup_cost_pq_rows(
            cost_by_full,
            cost_by_doc,
            document=row.document,
            main_section="Расходы",
            nomenclature=row.nomenclature_kt,
        )
        if not matches:
            buh_march_no_join += row.amount_buh
            continue
        for raw in matches:
            cost_match = _cost_row_from_pq_dict(raw) if isinstance(raw, dict) else raw
            section = _pq_cost_section(cost_match)
            amt = float(cost_match.amount or 0)
            buh_march_by_section[section or "(empty)"] += amt
            if section != "Амортизация":
                buh_march_joined_not_amort[section or "(empty)"] += amt

    # Cost amortization March rows: do they link to ANY buh cost row? which buh month?
    linked_buh_months: dict[str, float] = defaultdict(float)
    unlinked_cost_amort = 0.0
    unlinked_samples: list[dict] = []
    for r in cost_amort_march:
        doc = str(r.get("Документ") or "")
        nom = str(r.get("Номенклатура") or "")
        amt = float(r.get("Сумма") or 0)
        linked = False
        for row in exports.buh:
            if classify_buh_section(row.account_dt, row.account_kt) != "Себестоимость":
                continue
            matches = lookup_cost_pq_rows(
                cost_by_full,
                cost_by_doc,
                document=row.document,
                main_section="Расходы",
                nomenclature=row.nomenclature_kt,
            )
            if not any(
                str(m.get("Раздел") if isinstance(m, dict) else "") == "Амортизация"
                and str(m.get("Документ") if isinstance(m, dict) else "") == doc
                for m in matches
            ):
                continue
            linked = True
            linked_buh_months[row.month or "?"] += amt
            break
        if not linked:
            unlinked_cost_amort += amt
            if len(unlinked_samples) < 8:
                unlinked_samples.append({"document": doc, "nomenclature": nom, "amount": amt})

    prepared = _load_cost_prepared_rows(_prepare_raw_rows(read_workbook_rows(cost_path))) or []
    fuzzy_amort_march = 0.0
    fuzzy_articles: dict[str, float] = defaultdict(float)
    for row in prepared:
        article = (row.calc_article or "").casefold()
        if "амортиз" not in article:
            continue
        if classify_cost_section_pq(row.calc_article, str(row.account)) == "Амортизация":
            continue
        if _month_from_document(row.document) == MONTH:
            fuzzy_amort_march += float(row.amount or 0)
            fuzzy_articles[row.calc_article or ""] += float(row.amount or 0)

    summary = {
        "files": {k: v.name for k, v in paths.items()},
        "etalon_amort_march": 421_444.29,
        "dashboard_amort_march": dashboard_amort,
        "cost_pq_amort_march_by_doc_date": cost_amort_march_sum,
        "cost_amort_march_row_count": len(cost_amort_march),
        "buh_march_cost_by_joined_section": dict(buh_march_by_section),
        "buh_march_cost_no_join_amount": buh_march_no_join,
        "cost_amort_march_linked_to_buh_month": dict(linked_buh_months),
        "cost_amort_march_unlinked": unlinked_cost_amort,
        "unlinked_samples": unlinked_samples,
        "fuzzy_amort_march_not_in_Амортизация_section": fuzzy_amort_march,
        "fuzzy_articles": dict(fuzzy_articles),
        "etalon_gap_vs_cost_pq": cost_amort_march_sum - 421_444.29,
        "dashboard_gap_vs_cost_pq": cost_amort_march_sum - dashboard_amort,
    }
    _log("march amortization summary", summary, "ALL")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
