"""Отчёт «Налоги» — 2% льготные, 25% нельготные от налоговой базы НУ."""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from almabi_excel_utils import MONTH_NAMES, analytics_value, normalize_text, parse_date, tax_bucket
from almabi_pq_buh_register import build_pq_buh_register_table

TAX_BUCKET_PRIVILEGED = "Льготные проекты"
TAX_BUCKET_NON_PRIVILEGED = "Нельготные проекты"
TAX_BUCKETS = (TAX_BUCKET_PRIVILEGED, TAX_BUCKET_NON_PRIVILEGED)

TAXABLE_SECTIONS = frozenset({"Выручка", "Себестоимость", "Прочие доходы", "Прочие расходы"})

PBT_SECTIONS = frozenset(
    {
        "Выручка",
        "Себестоимость",
        "Расходы на продажу",
        "Управленческие расходы",
        "Прочие доходы",
        "Прочие расходы",
    }
)

TAX_RATE_BY_BUCKET: dict[str, float] = {
    TAX_BUCKET_PRIVILEGED: 0.02,
    TAX_BUCKET_NON_PRIVILEGED: 0.25,
}

COMPONENT_ORDER = TAX_BUCKETS

SOURCE_DETAIL_COLUMNS = (
    "Месяц",
    "Льгота",
    "Раздел",
    "Направление",
    "Группа проектов",
    "Проект",
    "Статья",
    "Документ",
    "Дата",
    "Сумма НУ",
    "Вид НО",
)

TAX_DETAIL_COLUMNS = (
    "Месяц",
    "Льгота",
    "Налоговая база НУ",
    "Ставка",
    "Налог",
)

ANALYTICS_LEVELS: tuple[tuple[str, str], ...] = (("Льгота", "tax"),)
MONTH_LEVELS: tuple[tuple[str, str], ...] = (("Месяц", "month"), ("Льгота", "tax"))

MONTH_ORDER = {name: index for index, name in enumerate(MONTH_NAMES.values(), start=1)}

FIELD_DEFAULTS = {
    "Льгота": TAX_BUCKET_NON_PRIVILEGED,
    "Раздел": "—",
    "Направление": "—",
    "Группа проектов": "—",
    "Проект": "—",
    "Статья": "—",
    "Документ": "Без документа",
    "Месяц": "Без месяца",
}


def _label(value: object, *, default: str) -> str:
    return analytics_value(value, default=default)


def _month_label(raw_date: object) -> str:
    parsed = parse_date(raw_date)
    if parsed is None and raw_date not in (None, ""):
        parsed = parse_date(str(raw_date))
    if parsed is None:
        return FIELD_DEFAULTS["Месяц"]
    return MONTH_NAMES.get(parsed.month, FIELD_DEFAULTS["Месяц"])


def _field_value(row: dict[str, object], field: str) -> str:
    value = normalize_text(row.get(field))
    return value or FIELD_DEFAULTS.get(field, "—")


def _sorted_group_keys(field: str, keys: list[str] | set[str]) -> list[str]:
    unique = list(keys)
    if field == "Месяц":
        return sorted(unique, key=lambda item: (MONTH_ORDER.get(item, 99), item))
    if field == "Льгота":
        order = {TAX_BUCKET_PRIVILEGED: 0, TAX_BUCKET_NON_PRIVILEGED: 1}
        return sorted(unique, key=lambda item: (order.get(item, 2), item))
    return sorted(unique)


def _tax_rate_for_bucket(bucket: str) -> float:
    return TAX_RATE_BY_BUCKET.get(bucket, TAX_RATE_BY_BUCKET[TAX_BUCKET_NON_PRIVILEGED])


def _format_rate(rate: float) -> str:
    percent = rate * 100
    if percent == int(percent):
        return f"{int(percent)}%"
    return f"{percent:g}%"


def _tax_amount(base: float, bucket: str) -> float:
    return -abs(base) * _tax_rate_for_bucket(bucket)


def _taxable_source_rows_from_buh(all_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for row in all_rows:
        section = normalize_text(row.get("Раздел"))
        if section not in TAXABLE_SECTIONS:
            continue
        amount_nu = float(row.get("Сумма НУ") or 0)
        if not amount_nu:
            continue
        tax_type = normalize_text(row.get("Вид НО")) or "Общие условия налогообложения"
        if section in {"Прочие доходы", "Прочие расходы"}:
            article = _label(row.get("Статья дохода расхода"), default="Прочее")
            direction = "—"
            group = "—"
            project = "—"
        else:
            article = _label(row.get("Статья дохода расхода"), default="—")
            direction = _label(row.get("Направление"), default="—")
            group = _label(row.get("Группа проектов"), default="—")
            project = _label(row.get("Проект"), default="—")
        rows.append(
            {
                "Месяц": _month_label(row.get("Дата")),
                "Льгота": tax_bucket(tax_type),
                "Раздел": section,
                "Направление": direction,
                "Группа проектов": group,
                "Проект": project,
                "Статья": article,
                "Документ": normalize_text(row.get("Документ")),
                "Дата": row.get("Дата"),
                "Сумма НУ": amount_nu,
                "Вид НО": tax_type,
            }
        )
    return rows


def _pbt_fallback_source_rows(all_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for row in all_rows:
        section = normalize_text(row.get("Раздел"))
        if section not in PBT_SECTIONS:
            continue
        amount_nu = float(row.get("Сумма НУ") or 0)
        if not amount_nu:
            continue
        tax_type = normalize_text(row.get("Вид НО")) or "Общие условия налогообложения"
        rows.append(
            {
                "Месяц": _month_label(row.get("Дата")),
                "Льгота": tax_bucket(tax_type),
                "Раздел": section,
                "Направление": _label(row.get("Направление"), default="—"),
                "Группа проектов": _label(row.get("Группа проектов"), default="—"),
                "Проект": _label(row.get("Проект"), default="—"),
                "Статья": _label(row.get("Статья дохода расхода"), default="—"),
                "Документ": normalize_text(row.get("Документ")),
                "Дата": row.get("Дата"),
                "Сумма НУ": amount_nu,
                "Вид НО": tax_type,
            }
        )
    return rows


def _tax_calculation_rows(source_rows: list[dict[str, object]], *, fallback: bool = False) -> list[dict[str, object]]:
    grouped: dict[tuple[str, str], float] = defaultdict(float)
    for row in source_rows:
        month = _field_value(row, "Месяц")
        bucket = _field_value(row, "Льгота")
        grouped[(month, bucket)] += float(row.get("Сумма НУ") or 0)

    if not grouped and not fallback:
        return []

    if not grouped and fallback:
        by_month: dict[str, float] = defaultdict(float)
        for row in source_rows:
            by_month[_field_value(row, "Месяц")] += float(row.get("Сумма НУ") or 0)
        for month, base in by_month.items():
            if not base:
                continue
            bucket = TAX_BUCKET_NON_PRIVILEGED
            grouped[(month, bucket)] = base

    rows: list[dict[str, object]] = []
    bucket_order = {TAX_BUCKET_PRIVILEGED: 0, TAX_BUCKET_NON_PRIVILEGED: 1}
    for (month, bucket) in sorted(
        grouped.keys(),
        key=lambda item: (MONTH_ORDER.get(item[0], 99), bucket_order.get(item[1], 2)),
    ):
        base = grouped[(month, bucket)]
        if not base:
            continue
        rate = _tax_rate_for_bucket(bucket) if not fallback else TAX_RATE_BY_BUCKET[TAX_BUCKET_NON_PRIVILEGED]
        tax = -abs(base) * rate
        rows.append(
            {
                "Месяц": month,
                "Льгота": bucket,
                "Налоговая база НУ": base,
                "Ставка": _format_rate(rate),
                "Налог": tax,
            }
        )
    return rows


def build_hierarchy(
    rows: list[dict[str, object]],
    level_specs: tuple[tuple[str, str], ...] | list[tuple[str, str]],
    *,
    amount_field: str = "Налог",
) -> list[dict[str, Any]]:
    if not rows or not level_specs:
        return []

    field, level = level_specs[0]
    grouped: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        key = _field_value(row, field)
        grouped.setdefault(key, []).append(row)

    tree: list[dict[str, Any]] = []
    for name in _sorted_group_keys(field, grouped.keys()):
        child_rows = grouped[name]
        amount = sum(float(item.get(amount_field) or 0) for item in child_rows)
        node: dict[str, Any] = {
            "name": name,
            "level": level,
            "amount": amount,
            "row_count": len(child_rows),
            "children": [],
        }
        if len(level_specs) > 1:
            node["children"] = build_hierarchy(child_rows, level_specs[1:], amount_field=amount_field)
        tree.append(node)
    return tree


def build_taxes_hierarchy(rows: list[dict[str, object]]) -> list[dict[str, Any]]:
    return build_hierarchy(rows, ANALYTICS_LEVELS)


def build_month_tax_table(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    by_month: dict[str, dict[str, float]] = {}
    for row in rows:
        month = _field_value(row, "Месяц")
        bucket = _field_value(row, "Льгота")
        month_totals = by_month.setdefault(
            month,
            {TAX_BUCKET_PRIVILEGED: 0.0, TAX_BUCKET_NON_PRIVILEGED: 0.0},
        )
        if bucket in month_totals:
            month_totals[bucket] += float(row.get("Налог") or 0)

    table: list[dict[str, object]] = []
    for month in _sorted_group_keys("Месяц", by_month.keys()):
        privileged = by_month[month][TAX_BUCKET_PRIVILEGED]
        non_privileged = by_month[month][TAX_BUCKET_NON_PRIVILEGED]
        table.append(
            {
                "month": month,
                "privileged": privileged,
                "non_privileged": non_privileged,
                "total": privileged + non_privileged,
            }
        )
    return table


def _bucket_totals(calc_rows: list[dict[str, object]]) -> tuple[dict[str, float], dict[str, float]]:
    bases = {name: 0.0 for name in TAX_BUCKETS}
    taxes = {name: 0.0 for name in TAX_BUCKETS}
    for row in calc_rows:
        bucket = _field_value(row, "Льгота")
        if bucket in bases:
            bases[bucket] += float(row.get("Налоговая база НУ") or 0)
            taxes[bucket] += float(row.get("Налог") or 0)
    return bases, taxes


def build_taxes_report(
    *,
    buh_path: Path,
    cost_path: Path | None = None,
    revenue_path: Path | None = None,
    projects_path: Path | None = None,
) -> dict[str, object]:
    all_rows = build_pq_buh_register_table(
        buh_path,
        cost_path=cost_path,
        revenue_path=revenue_path,
        projects_path=projects_path,
    )
    source_rows = _taxable_source_rows_from_buh(all_rows)
    fallback = False
    if not source_rows:
        fallback_rows = _pbt_fallback_source_rows(all_rows)
        source_rows = fallback_rows
        fallback = bool(fallback_rows)

    calc_rows = _tax_calculation_rows(source_rows, fallback=fallback)
    base_totals, component_totals = _bucket_totals(calc_rows)
    total_tax = sum(float(row.get("Налог") or 0) for row in calc_rows)
    months = {normalize_text(row.get("Месяц")) for row in calc_rows if row.get("Месяц")}
    return {
        "loaded": bool(calc_rows),
        "source_rows": source_rows,
        "rows": calc_rows,
        "tree": build_hierarchy(calc_rows, ANALYTICS_LEVELS),
        "tree_by_month": build_hierarchy(calc_rows, MONTH_LEVELS),
        "month_table": build_month_tax_table(calc_rows),
        "summary": {
            "row_count": len(source_rows),
            "calc_row_count": len(calc_rows),
            "total_amount": total_tax,
            "privileged_amount": component_totals[TAX_BUCKET_PRIVILEGED],
            "non_privileged_amount": component_totals[TAX_BUCKET_NON_PRIVILEGED],
            "base_totals": base_totals,
            "component_totals": component_totals,
            "rates": {bucket: _format_rate(TAX_RATE_BY_BUCKET[bucket]) for bucket in TAX_BUCKETS},
            "month_count": len(months),
            "amount_column": "Налог",
            "columns": list(TAX_DETAIL_COLUMNS),
            "source_columns": list(SOURCE_DETAIL_COLUMNS),
            "fallback_mode": fallback,
        },
    }
