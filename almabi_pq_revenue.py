"""Формирование запроса «Выручка» — логика Power Query для выгрузки «Реализация проекты»."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from almabi_excel_utils import normalize_header, normalize_text, parse_amount, read_workbook_rows
from almabi_pq_common import cell_value, find_header_row_index, remove_column_indices, resolve_header_index

PQ_REVENUE_SKIP_ROWS = 7
PQ_REVENUE_REMOVE_LAST = 1
PQ_REVENUE_REMOVE_COLUMN_INDICES = frozenset({1, 2, 4, 5})
PQ_REVENUE_SECTION = "Доходы"

REVENUE_AMOUNT_HEADERS = ("выручка",)

OUTPUT_COLUMNS = (
    "Документ",
    "Проект",
    "Группа проектов",
    "Направление",
    "Раздел",
    "Сумма",
)


@dataclass(frozen=True)
class PqRevenueRow:
    document: str
    project: str
    project_group: str
    direction: str
    section: str
    amount: float

    def to_dict(self) -> dict[str, object]:
        return {
            "Документ": self.document,
            "Проект": self.project,
            "Группа проектов": self.project_group,
            "Направление": self.direction,
            "Раздел": self.section,
            "Сумма": self.amount,
        }


def _is_revenue_header(headers: list[str]) -> bool:
    return any("выручка" in normalize_header(header) for header in headers)


def _prepare_raw_rows(raw_rows: list[tuple[object, ...]]) -> list[tuple[object, ...]]:
    if len(raw_rows) <= PQ_REVENUE_SKIP_ROWS:
        return []
    rows = list(raw_rows[PQ_REVENUE_SKIP_ROWS :])
    if len(rows) > PQ_REVENUE_REMOVE_LAST:
        rows = rows[: -PQ_REVENUE_REMOVE_LAST]
    return rows


def _parse_rows(rows: list[tuple[object, ...]]) -> list[PqRevenueRow] | None:
    if not rows:
        return []

    header_index = find_header_row_index(rows, matcher=_is_revenue_header) or 0
    headers = [normalize_text(value) for value in rows[header_index]]
    if not _is_revenue_header(headers):
        return None

    document_idx = resolve_header_index(
        headers,
        ("заказ клиента / реализация", "заказ клиента", "реализация", "документ"),
    )
    project_idx = resolve_header_index(headers, ("проект", "project"))
    group_idx = resolve_header_index(headers, ("группа проектов", "project group"))
    direction_idx = resolve_header_index(headers, ("направление", "направление деятельности", "direction"))
    revenue_idx = resolve_header_index(headers, REVENUE_AMOUNT_HEADERS)
    if document_idx is None or revenue_idx is None:
        return None

    grouped: dict[tuple[str, str, str, str, str], float] = {}
    for row in rows[header_index + 1 :]:
        document = normalize_text(cell_value(row, document_idx))
        if not document:
            continue
        amount = parse_amount(cell_value(row, revenue_idx))
        project = normalize_text(cell_value(row, project_idx))
        project_group = normalize_text(cell_value(row, group_idx))
        direction = normalize_text(cell_value(row, direction_idx))
        key = (document, project, project_group, direction, PQ_REVENUE_SECTION)
        grouped[key] = grouped.get(key, 0.0) + amount

    return [
        PqRevenueRow(
            document=key[0],
            project=key[1],
            project_group=key[2],
            direction=key[3],
            section=key[4],
            amount=amount,
        )
        for key, amount in sorted(grouped.items(), key=lambda item: item[0])
    ]


def build_pq_revenue_table(path: Path) -> list[dict[str, object]]:
    rows = _prepare_raw_rows(read_workbook_rows(path))
    if not rows:
        return []

    for variant in (
        [remove_column_indices(row, PQ_REVENUE_REMOVE_COLUMN_INDICES) for row in rows],
        rows,
    ):
        parsed = _parse_rows(variant)
        if parsed is not None:
            return [row.to_dict() for row in parsed]
    return []


def table_summary(rows: list[dict[str, object]]) -> dict[str, object]:
    total = sum(float(row.get("Сумма") or 0) for row in rows)
    return {
        "row_count": len(rows),
        "total_amount": total,
        "columns": list(OUTPUT_COLUMNS),
    }
