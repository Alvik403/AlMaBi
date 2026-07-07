"""Запрос «Проекты» — все строки реализации с Раздел = «Выручка» (как в Power Query)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from almabi_excel_utils import normalize_header, normalize_text, parse_amount, read_workbook_rows
from almabi_pq_common import cell_value, find_header_row_index, remove_column_indices, resolve_header_index

PQ_PROJECTS_SKIP_ROWS = 7
PQ_PROJECTS_REMOVE_LAST = 1
PQ_PROJECTS_REMOVE_COLUMN_INDICES = frozenset({1, 2, 4, 5})
PQ_PROJECTS_SECTION = "Выручка"

REVENUE_AMOUNT_HEADERS = ("выручка",)

PROJECT_OUTPUT_COLUMNS = (
    "Документ",
    "Номенклатура",
    "Проект",
    "Группа проектов",
    "Направление",
    "Сумма",
    "Раздел",
    "Валовая прибыль",
)


@dataclass(frozen=True)
class PqProjectRow:
    document: str
    nomenclature: str
    project: str
    project_group: str
    direction: str
    amount: float | None
    section: str
    gross_profit: float | None

    def to_dict(self) -> dict[str, object]:
        return {
            "Документ": self.document,
            "Номенклатура": self.nomenclature,
            "Проект": self.project,
            "Группа проектов": self.project_group,
            "Направление": self.direction,
            "Сумма": self.amount,
            "Раздел": self.section,
            "Валовая прибыль": self.gross_profit,
        }


def _is_realization_header(headers: list[str]) -> bool:
    joined = " | ".join(normalize_header(header) for header in headers if header)
    return "выручка" in joined and (
        "номенклатура" in joined or "заказ клиента" in joined or "группа проектов" in joined
    )


def _parse_project_rows(rows: list[tuple[object, ...]]) -> list[PqProjectRow] | None:
    if not rows:
        return []

    header_index = find_header_row_index(rows, matcher=_is_realization_header) or 0
    headers = [normalize_text(value) for value in rows[header_index]]
    if not _is_realization_header(headers):
        return None

    document_idx = resolve_header_index(
        headers,
        ("заказ клиента / реализация", "заказ клиента", "реализация", "документ"),
    )
    nomenclature_idx = resolve_header_index(headers, ("номенклатура", "sku", "продукция"))
    project_idx = resolve_header_index(headers, ("проект", "project"))
    group_idx = resolve_header_index(headers, ("группа проектов", "project group"))
    direction_idx = resolve_header_index(headers, ("направление", "направление деятельности", "direction"))
    revenue_idx = resolve_header_index(headers, REVENUE_AMOUNT_HEADERS)
    gross_idx = resolve_header_index(headers, ("валовая прибыль", "gross profit"))
    if document_idx is None or revenue_idx is None:
        return None

    parsed: list[PqProjectRow] = []
    for row in rows[header_index + 1 :]:
        document = normalize_text(cell_value(row, document_idx))
        if not document:
            continue
        raw_amount = cell_value(row, revenue_idx)
        amount = parse_amount(raw_amount) if raw_amount not in (None, "") else None
        raw_gross = cell_value(row, gross_idx)
        gross = parse_amount(raw_gross) if raw_gross not in (None, "") else None
        parsed.append(
            PqProjectRow(
                document=document,
                nomenclature=normalize_text(cell_value(row, nomenclature_idx)),
                project=normalize_text(cell_value(row, project_idx)),
                project_group=normalize_text(cell_value(row, group_idx)),
                direction=normalize_text(cell_value(row, direction_idx)),
                amount=amount,
                section=PQ_PROJECTS_SECTION,
                gross_profit=gross,
            )
        )
    return parsed


def _prepare_raw_rows(raw_rows: list[tuple[object, ...]]) -> list[tuple[object, ...]]:
    if len(raw_rows) <= PQ_PROJECTS_SKIP_ROWS:
        return []
    rows = list(raw_rows[PQ_PROJECTS_SKIP_ROWS :])
    if len(rows) > PQ_PROJECTS_REMOVE_LAST:
        rows = rows[: -PQ_PROJECTS_REMOVE_LAST]
    return rows


def build_pq_projects_table(path: Path) -> list[dict[str, object]]:
    rows = _prepare_raw_rows(read_workbook_rows(path))
    if not rows:
        return []

    for variant in (
        [remove_column_indices(row, PQ_PROJECTS_REMOVE_COLUMN_INDICES) for row in rows],
        rows,
    ):
        parsed = _parse_project_rows(variant)
        if parsed is not None:
            return [row.to_dict() for row in parsed]
    return []


def table_summary(rows: list[dict[str, object]]) -> dict[str, object]:
    total = sum(float(row.get("Сумма") or 0) for row in rows)
    return {
        "row_count": len(rows),
        "total_amount": total,
        "columns": list(PROJECT_OUTPUT_COLUMNS),
    }
