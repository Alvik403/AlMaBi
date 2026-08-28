"""Сверка общей себестoимости НУ по месяцам с эталоном (бухрегистр NU 90.02)."""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from almabi_excel_utils import MONTH_NAMES
from almabi_export_parsers import classify_buh_section, parse_exports
from almabi_pipeline import _amount_nu_for_section, _dedupe_cost_nu_rows
from almabi_test_pipeline import run_test_pipeline

NU_RESIDUAL_ARTICLE = "Сверка НУ с бухрегистром 90.02"


def _latest(prefix: str) -> Path:
    uploads = ROOT / "uploads" / "almabi"
    return sorted(uploads.glob(f"{prefix}*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True)[0]


def _monthly_buh_nu_90_02(exports) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    for row in exports.buh:
        section = classify_buh_section(row.account_dt, row.account_kt)
        if section != "Себестоимость" or not row.month:
            continue
        totals[row.month] += _amount_nu_for_section(section, row.amount_nu_dt, row.amount_nu_kt)
    return {month: abs(value) for month, value in totals.items()}


def _monthly_buh_bu_90_02(exports) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    for row in exports.buh:
        if classify_buh_section(row.account_dt, row.account_kt) == "Себестоимость" and row.month:
            totals[row.month] += abs(float(row.amount_buh or 0))
    return dict(totals)


def _monthly_cost_nu_file(exports) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    for row in _dedupe_cost_nu_rows(exports.cost_nu):
        if row.month:
            totals[row.month] += float(row.amount_nu or 0)
    return {month: abs(value) for month, value in totals.items()}


def _monthly_pipeline_nu(facts) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    for fact in facts:
        if fact.kpi_l1 != "Себестоимость":
            continue
        totals[fact.month] += -float(fact.amount_nu or 0)
    return dict(totals)


def _monthly_pipeline_bu(facts) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    for fact in facts:
        if fact.kpi_l1 == "Себестоимость":
            totals[fact.month] += -float(fact.amount_buh or 0)
    return dict(totals)


def _monthly_register_residual(facts) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    for fact in facts:
        if (
            fact.kpi_l1 == "Себестоимость"
            and fact.expense_article == NU_RESIDUAL_ARTICLE
        ):
            totals[fact.month] += -float(fact.amount_nu or 0)
    return dict(totals)


def main() -> None:
    paths = {
        "buh": _latest("buh-"),
        "cost": _latest("cost-"),
        "realization": _latest("realization-"),
        "cost_nu": _latest("cost_nu-"),
    }
    exports = parse_exports(paths)
    pipeline = run_test_pipeline(paths)
    facts = pipeline.result.facts

    buh_bu = _monthly_buh_bu_90_02(exports)
    bi_bu = _monthly_pipeline_bu(facts)
    buh_nu = _monthly_buh_nu_90_02(exports)
    file_nu = _monthly_cost_nu_file(exports)
    bi_nu = _monthly_pipeline_nu(facts)
    residual_nu = _monthly_register_residual(facts)

    rows = []
    max_bu_delta = 0.0
    max_nu_delta = 0.0
    for month in MONTH_NAMES.values():
        bu_etalon = buh_bu.get(month, 0.0)
        bu_pipeline = bi_bu.get(month, 0.0)
        nu_etalon = buh_nu.get(month, 0.0)
        nu_pipeline = bi_nu.get(month, 0.0)
        file_total = file_nu.get(month, 0.0)
        residual = residual_nu.get(month, 0.0)
        matched_file_nu = nu_pipeline - residual
        unallocated_file_nu = file_total - matched_file_nu
        if not bu_etalon and not bu_pipeline and not nu_etalon and not nu_pipeline and not file_total:
            continue
        bu_delta = bu_pipeline - bu_etalon
        nu_delta = nu_pipeline - nu_etalon
        max_bu_delta = max(max_bu_delta, abs(bu_delta))
        max_nu_delta = max(max_nu_delta, abs(nu_delta))
        rows.append(
            {
                "month": month,
                "buh_bu_90_02": bu_etalon,
                "bi_bu_pipeline": bu_pipeline,
                "delta_bu_vs_buh": bu_delta,
                "buh_nu_90_02": nu_etalon,
                "cost_nu_file_deduped": file_total,
                "matched_file_nu": matched_file_nu,
                "unallocated_file_nu": unallocated_file_nu,
                "register_residual_nu": residual,
                "bi_nu_pipeline": nu_pipeline,
                "delta_nu_vs_buh": nu_delta,
                "delta_file_vs_buh": file_total - nu_etalon,
            }
        )

    data = {
        "paths": {k: v.name for k, v in paths.items()},
        "months": rows,
        "max_abs_delta_bu_vs_buh": max_bu_delta,
        "max_abs_delta_nu_vs_buh": max_nu_delta,
        "all_bu_months_match": max_bu_delta < 0.01,
        "all_nu_months_match": max_nu_delta < 0.01,
    }
    print(json.dumps(data, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
