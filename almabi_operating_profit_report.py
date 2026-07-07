"""Отчёт «Операционная прибыль» — выручка − себестоимость − коммерческие − управленческие."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from almabi_excel_utils import MONTH_NAMES, analytics_value, normalize_text, parse_date, tax_bucket
from almabi_pq_buh_register import build_pq_buh_register_table

TAX_BUCKET_PRIVILEGED = "Льготные проекты"
TAX_BUCKET_NON_PRIVILEGED = "Нельготные проекты"
TAX_BUCKETS = (TAX_BUCKET_PRIVILEGED, TAX_BUCKET_NON_PRIVILEGED)

COMPONENT_ORDER = (
    "Выручка",
    "Себестоимость",
    "Коммерческие расходы",
    "Управленческие расходы",
)

PQ_SECTION_BY_COMPONENT: dict[str, str] = {
    "Выручка": "Выручка",
    "Себестоимость": "Себестоимость",
    "Коммерческие расходы": "Расходы на продажу",
    "Управленческие расходы": "Управленческие расходы",
}

DETAIL_COLUMNS = (
    "Месяц",
    "Льгота",
    "Компонент",
    "Направление",
    "Группа проектов",
    "Проект",
    "Статья",
    "Документ",
    "Дата",
    "Сумма БУ",
    "Вид НО",
)

ANALYTICS_LEVELS: tuple[tuple[str, str], ...] = (("Компонент", "component"),)
MONTH_LEVELS: tuple[tuple[str, str], ...] = (("Месяц", "month"), ("Компонент", "component"))

MONTH_ORDER = {name: index for index, name in enumerate(MONTH_NAMES.values(), start=1)}

FIELD_DEFAULTS = {
    "Компонент": "—",
    "Направление": "—",
    "Группа проектов": "—",
    "Проект": "—",
    "Статья": "—",
    "Документ": "Без документа",
    "Месяц": "Без месяца",
    "Льгота": TAX_BUCKET_NON_PRIVILEGED,
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
    if field == "Компонент":
        order = {name: index for index, name in enumerate(COMPONENT_ORDER)}
        return sorted(unique, key=lambda item: (order.get(item, 99), item))
    return sorted(unique)


def _component_for_section(section: str) -> str | None:
    for component, pq_section in PQ_SECTION_BY_COMPONENT.items():
        if section == pq_section:
            return component
    return None


def _operating_profit_rows_from_buh(all_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for row in all_rows:
        section = normalize_text(row.get("Раздел"))
        component = _component_for_section(section)
        if component is None:
            continue
        tax_type = normalize_text(row.get("Вид НО")) or "Общие условия налогообложения"
        if component in {"Коммерческие расходы", "Управленческие расходы"}:
            article = _label(row.get("Статья дохода расхода"), default="Прочее")
        else:
            article = _label(row.get("Статья дохода расхода"), default="—")
        rows.append(
            {
                "Месяц": _month_label(row.get("Дата")),
                "Льгота": tax_bucket(tax_type),
                "Компонент": component,
                "Направление": _label(row.get("Направление"), default="—"),
                "Группа проектов": _label(row.get("Группа проектов"), default="—"),
                "Проект": _label(row.get("Проект"), default="—"),
                "Статья": article,
                "Документ": normalize_text(row.get("Документ")),
                "Дата": row.get("Дата"),
                "Сумма БУ": float(row.get("Сумма БУ") or 0),
                "Вид НО": tax_type,
            }
        )
    return rows


def build_hierarchy(
    rows: list[dict[str, object]],
    level_specs: tuple[tuple[str, str], ...] | list[tuple[str, str]],
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
        amount = sum(float(item.get("Сумма БУ") or 0) for item in child_rows)
        node: dict[str, Any] = {
            "name": name,
            "level": level,
            "amount": amount,
            "row_count": len(child_rows),
            "children": [],
        }
        if len(level_specs) > 1:
            node["children"] = build_hierarchy(child_rows, level_specs[1:])
        tree.append(node)
    return tree


def build_operating_profit_hierarchy(rows: list[dict[str, object]]) -> list[dict[str, Any]]:
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
            month_totals[bucket] += float(row.get("Сумма БУ") or 0)

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


def _tax_totals(rows: list[dict[str, object]]) -> dict[str, float]:
    totals = {TAX_BUCKET_PRIVILEGED: 0.0, TAX_BUCKET_NON_PRIVILEGED: 0.0}
    for row in rows:
        bucket = _field_value(row, "Льгота")
        if bucket in totals:
            totals[bucket] += float(row.get("Сумма БУ") or 0)
    return totals


def _component_totals(rows: list[dict[str, object]]) -> dict[str, float]:
    totals = {name: 0.0 for name in COMPONENT_ORDER}
    for row in rows:
        component = _field_value(row, "Компонент")
        if component in totals:
            totals[component] += float(row.get("Сумма БУ") or 0)
    return totals


def build_operating_profit_report(
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
    rows = _operating_profit_rows_from_buh(all_rows)
    total = sum(float(row.get("Сумма БУ") or 0) for row in rows)
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
            "month_count": len(months),
            "amount_column": "Сумма БУ",
            "columns": list(DETAIL_COLUMNS),
        },
    }
