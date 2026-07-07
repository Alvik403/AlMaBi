"""Отчёт «Чистая прибыль» — прибыль до НО + налоги (с учётом знаков)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from almabi_excel_utils import MONTH_NAMES, normalize_text
from almabi_profit_before_tax_report import (
    TAX_BUCKET_NON_PRIVILEGED,
    TAX_BUCKET_PRIVILEGED,
    build_profit_before_tax_report,
)
from almabi_taxes_report import build_taxes_report

COMPONENT_ORDER = (
    "Прибыль/убыток до налогообложения",
    "Налоги",
)

PBT_COMPONENT = "Прибыль/убыток до налогообложения"
TAXES_COMPONENT = "Налоги"

DETAIL_COLUMNS = (
    "Месяц",
    "Льгота",
    "Компонент",
    "Подкомпонент",
    "Направление",
    "Группа проектов",
    "Проект",
    "Статья",
    "Документ",
    "Дата",
    "Сумма",
    "Вид НО",
)

ANALYTICS_LEVELS: tuple[tuple[str, str], ...] = (("Компонент", "component"),)
MONTH_LEVELS: tuple[tuple[str, str], ...] = (("Месяц", "month"), ("Компонент", "component"))

MONTH_ORDER = {name: index for index, name in enumerate(MONTH_NAMES.values(), start=1)}

FIELD_DEFAULTS = {
    "Компонент": "—",
    "Подкомпонент": "—",
    "Льгота": TAX_BUCKET_NON_PRIVILEGED,
    "Месяц": "Без месяца",
}


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
    if field == "Компонент":
        order = {name: index for index, name in enumerate(COMPONENT_ORDER)}
        return sorted(unique, key=lambda item: (order.get(item, 99), item))
    return sorted(unique)


def build_hierarchy(
    rows: list[dict[str, object]],
    level_specs: tuple[tuple[str, str], ...] | list[tuple[str, str]],
    *,
    amount_field: str = "Сумма",
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


def _pbt_detail_rows(pbt_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for row in pbt_rows:
        rows.append(
            {
                "Месяц": row.get("Месяц"),
                "Льгота": row.get("Льгота"),
                "Компонент": PBT_COMPONENT,
                "Подкомпонент": row.get("Компонент"),
                "Направление": row.get("Направление"),
                "Группа проектов": row.get("Группа проектов"),
                "Проект": row.get("Проект"),
                "Статья": row.get("Статья"),
                "Документ": row.get("Документ"),
                "Дата": row.get("Дата"),
                "Сумма": float(row.get("Сумма БУ") or 0),
                "Вид НО": row.get("Вид НО"),
            }
        )
    return rows


def _tax_detail_rows(tax_calc_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for row in tax_calc_rows:
        rate = normalize_text(row.get("Ставка"))
        rows.append(
            {
                "Месяц": row.get("Месяц"),
                "Льгота": row.get("Льгота"),
                "Компонент": TAXES_COMPONENT,
                "Подкомпонент": "—",
                "Направление": "—",
                "Группа проектов": "—",
                "Проект": "—",
                "Статья": f"Налог {rate} от базы НУ",
                "Документ": "—",
                "Дата": "—",
                "Сумма": float(row.get("Налог") or 0),
                "Вид НО": "—",
            }
        )
    return rows


def build_net_profit_hierarchy(rows: list[dict[str, object]]) -> list[dict[str, Any]]:
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
            month_totals[bucket] += float(row.get("Сумма") or 0)

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


def _component_totals(rows: list[dict[str, object]]) -> dict[str, float]:
    totals = {name: 0.0 for name in COMPONENT_ORDER}
    for row in rows:
        component = _field_value(row, "Компонент")
        if component in totals:
            totals[component] += float(row.get("Сумма") or 0)
    return totals


def _tax_totals(rows: list[dict[str, object]]) -> dict[str, float]:
    totals = {TAX_BUCKET_PRIVILEGED: 0.0, TAX_BUCKET_NON_PRIVILEGED: 0.0}
    for row in rows:
        bucket = _field_value(row, "Льгота")
        if bucket in totals:
            totals[bucket] += float(row.get("Сумма") or 0)
    return totals


def build_net_profit_report(
    *,
    buh_path: Path,
    cost_path: Path | None = None,
    revenue_path: Path | None = None,
    projects_path: Path | None = None,
) -> dict[str, object]:
    pbt_report = build_profit_before_tax_report(
        buh_path=buh_path,
        cost_path=cost_path,
        revenue_path=revenue_path,
        projects_path=projects_path,
    )
    taxes_report = build_taxes_report(
        buh_path=buh_path,
        cost_path=cost_path,
        revenue_path=revenue_path,
        projects_path=projects_path,
    )

    pbt_rows = _pbt_detail_rows(pbt_report["rows"])
    tax_rows = _tax_detail_rows(taxes_report["rows"])
    rows = pbt_rows + tax_rows

    total = sum(float(row.get("Сумма") or 0) for row in rows)
    tax_totals = _tax_totals(rows)
    component_totals = _component_totals(rows)
    months = {normalize_text(row.get("Месяц")) for row in rows if row.get("Месяц")}

    return {
        "loaded": bool(rows),
        "rows": rows,
        "tree": build_hierarchy(rows, ANALYTICS_LEVELS),
        "tree_by_month": build_hierarchy(rows, MONTH_LEVELS),
        "month_table": build_month_tax_table(rows),
        "summary": {
            "row_count": len(rows),
            "total_amount": total,
            "privileged_amount": tax_totals[TAX_BUCKET_PRIVILEGED],
            "non_privileged_amount": tax_totals[TAX_BUCKET_NON_PRIVILEGED],
            "component_totals": component_totals,
            "pbt_amount": component_totals[PBT_COMPONENT],
            "taxes_amount": component_totals[TAXES_COMPONENT],
            "month_count": len(months),
            "amount_column": "Сумма",
            "columns": list(DETAIL_COLUMNS),
        },
    }
