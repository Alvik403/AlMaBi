"""Отчёт «Налоги» — 2% льготные, 25% нельготные от налоговой базы НУ."""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from almabi_excel_utils import (
    MONTH_NAMES,
    analytics_value,
    normalize_text,
    parse_date,
    period_sort_key,
    tax_bucket,
)
from almabi_pq_buh_register import build_pq_buh_register_table

TAX_BUCKET_PRIVILEGED = "Льготные проекты"
TAX_BUCKET_NON_PRIVILEGED = "Нельготные проекты"
TAX_BUCKETS = (TAX_BUCKET_PRIVILEGED, TAX_BUCKET_NON_PRIVILEGED)

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
TAXABLE_SECTIONS = PBT_SECTIONS

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
    return parsed.strftime("%Y-%m")


def _field_value(row: dict[str, object], field: str) -> str:
    value = normalize_text(row.get(field))
    return value or FIELD_DEFAULTS.get(field, "—")


def _sorted_group_keys(field: str, keys: list[str] | set[str]) -> list[str]:
    unique = list(keys)
    if field == "Месяц":
        return sorted(
            unique,
            key=lambda item: (
                period_sort_key(item, fallback=item),
                MONTH_ORDER.get(item, 99),
                item,
            ),
        )
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


MONTHS_ORDERED = tuple(MONTH_NAMES.values())


def compute_tax_with_loss_carryforward(
    monthly_base: dict[str, float],
    *,
    rate: float,
    months: tuple[str, ...] | None = None,
) -> tuple[dict[str, float], dict[str, float]]:
    """Налог и налогооблагаемая база по месяцам с переносом убытков внутри корзины."""
    has_period_keys = any(
        len(key) == 7 and key[4] == "-" and key[:4].isdigit()
        for key in monthly_base
    )
    requested = list(months) if months is not None else (
        list(monthly_base) if has_period_keys else list(MONTHS_ORDERED)
    )
    month_order = sorted(requested, key=lambda key: period_sort_key(key, fallback=key))
    carryforward = 0.0
    previous_year: str | None = None
    taxes: dict[str, float] = {}
    taxable_bases: dict[str, float] = {}
    for month in month_order:
        current_year = month[:4] if len(month) == 7 and month[4] == "-" and month[:4].isdigit() else None
        if current_year is not None and previous_year is not None and current_year != previous_year:
            carryforward = 0.0
        if current_year is not None:
            previous_year = current_year
        pbt = float(monthly_base.get(month, 0) or 0)
        net = carryforward + pbt
        if net <= 0:
            carryforward = net
            taxes[month] = 0.0
            taxable_bases[month] = 0.0
        else:
            carryforward = 0.0
            taxable_bases[month] = net
            taxes[month] = -net * rate
    return taxes, taxable_bases


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
            bucket = TAX_BUCKET_NON_PRIVILEGED
            grouped[(month, bucket)] = base

    monthly_by_bucket: dict[str, dict[str, float]] = {bucket: {} for bucket in TAX_BUCKETS}
    for (month, bucket), amount in grouped.items():
        if bucket in monthly_by_bucket:
            monthly_by_bucket[bucket][month] = amount

    rows: list[dict[str, object]] = []
    buckets = (TAX_BUCKET_NON_PRIVILEGED,) if fallback else TAX_BUCKETS
    for bucket in buckets:
        rate = (
            TAX_RATE_BY_BUCKET[TAX_BUCKET_NON_PRIVILEGED]
            if fallback
            else _tax_rate_for_bucket(bucket)
        )
        taxes, taxable_bases = compute_tax_with_loss_carryforward(
            monthly_by_bucket.get(bucket, {}),
            rate=rate,
        )
        for month in _sorted_group_keys("Месяц", taxes.keys()):
            tax = taxes[month]
            base = taxable_bases[month]
            if tax == 0 and base == 0:
                continue
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
