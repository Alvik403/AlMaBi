"""Формирование запроса «Себестоимость» — логика Power Query для выгрузки себестоимости."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from almabi_excel_utils import header_matches, normalize_header, normalize_text, parse_amount, read_workbook_rows
from almabi_pq_common import (
    build_projects_document_index,
    cell_value,
    find_header_row_index,
    lookup_projects_for_document,
    remove_column_indices,
    resolve_header_index,
)

PQ_COST_REMOVE_LAST = 38
PQ_COST_HEADER_SCAN_ROWS = 40

PQ_COST_REMOVE_COLUMN_INDICES = frozenset(
    {
        1, 2, 3, 4, 5, 7, 9, 11, 12, 14, 15, 16, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28,
        29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42,
    }
)

COST_AMOUNT_HEADERS = (
    "себестоимость (регл. учет)",
    "себестоимость (бухг. учет)",
)

COST_AMOUNT_EXCLUDED_FRAGMENTS = (
    "%",
    "на единиц",
    "полная",
    "единиц",
)

OUTPUT_COLUMNS = (
    "Раздел",
    "Номенклатура",
    "Документ",
    "Проект",
    "Группа проектов",
    "Направление",
    "Счет",
    "Сумма",
    "Основной раздел",
)

GROUP_COLUMNS = (
    "Раздел",
    "Номенклатура",
    "Документ",
    "Проект",
    "Группа проектов",
    "Направление",
    "Счет",
)


@dataclass
class _CostPreparedRow:
    nomenclature: str
    account: int
    calc_article: str
    document: str
    quantity: float
    amount: float | None
    section: str


def _resolve_cost_amount_index(headers: list[str]) -> int | None:
    """Как в PQ: «Себестоимость (регл. учет)», иначе бухг.; без % и «полная»."""
    normalized = [normalize_header(header) for header in headers]
    for target in COST_AMOUNT_HEADERS:
        for index, header in enumerate(normalized):
            if header == target:
                return index
    for index, header in enumerate(normalized):
        if "себестоимость" not in header:
            continue
        if any(fragment in header for fragment in COST_AMOUNT_EXCLUDED_FRAGMENTS):
            continue
        if any(header_matches(header, candidate) for candidate in COST_AMOUNT_HEADERS):
            return index
    return None


def _is_cost_header(headers: list[str]) -> bool:
    joined = " | ".join(normalize_header(header) for header in headers if header)
    return ("документ отгрузки" in joined or "продукция" in joined) and "себестоимость" in joined


def _account_value(raw: object) -> int:
    if raw is None or raw == "":
        return 20
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float):
        return int(raw)
    text = normalize_text(raw)
    if not text:
        return 20
    try:
        return int(float(text.replace(",", ".")))
    except ValueError:
        return 20


def _classify_section(calc_article: str, account: int) -> str:
    article = calc_article or "Сырье и материалы"
    if account != 20:
        return "Прочие производственные расходы"
    if article == "Сырье и материалы":
        return "Материальные затраты"
    if article == "Прочие производственные расходы":
        return "Материальные затраты"
    if article == "Оплата труда":
        return "ФОТ"
    if article == "Страховые взносы":
        return "ФОТ"
    if article == "Аренда":
        return "Аренда"
    if article == "Амортизация":
        return "Амортизация"
    return "Прочие производственные расходы"


def _main_section(section: str) -> str:
    if section == "Выручка":
        return "Доходы"
    return "Расходы"


def _trim_cost_footer(rows: list[tuple[object, ...]]) -> list[tuple[object, ...]]:
    """Убираем хвост 1С: пустые строки, «Итого», блок padding (как PQ RemoveLastN)."""
    trimmed = list(rows)
    while trimmed:
        cells = [normalize_text(value) for value in trimmed[-1]]
        if not any(cells):
            trimmed.pop()
            continue
        if cells[0].casefold().startswith("итого"):
            trimmed.pop()
            continue
        break
    if len(trimmed) > PQ_COST_REMOVE_LAST + 1:
        tail = trimmed[-PQ_COST_REMOVE_LAST:]
        if all(not any(normalize_text(value) for value in row) for row in tail):
            trimmed = trimmed[: -PQ_COST_REMOVE_LAST]
    return trimmed


def _prepare_raw_rows(raw_rows: list[tuple[object, ...]]) -> list[tuple[object, ...]]:
    if not raw_rows:
        return []
    header_index = find_header_row_index(
        raw_rows,
        matcher=_is_cost_header,
        scan_limit=PQ_COST_HEADER_SCAN_ROWS,
    )
    if header_index is not None:
        rows = list(raw_rows[header_index:])
    else:
        # Legacy PQ: первые 5 строк — служебный заголовок отчёта.
        rows = list(raw_rows[5:] if len(raw_rows) > 5 else raw_rows)
    return _trim_cost_footer(rows)


def _parse_cost_rows(rows: list[tuple[object, ...]]) -> list[_CostPreparedRow] | None:
    if not rows:
        return []

    header_index = find_header_row_index(rows, matcher=_is_cost_header) or 0
    header_row = [normalize_text(value) for value in rows[header_index]]
    if not _is_cost_header(header_row):
        return None

    nomenclature_idx = resolve_header_index(header_row, ("продукция", "номенклатура", "sku"))
    account_idx = resolve_header_index(header_row, ("счет", "account"))
    calc_idx = resolve_header_index(header_row, ("статья калькуляции", "calc article"))
    document_idx = resolve_header_index(
        header_row,
        ("документ отгрузки", "документ", "document", "реализация"),
    )
    quantity_idx = resolve_header_index(header_row, ("количество продаж", "количество", "quantity"))
    amount_idx = _resolve_cost_amount_index(header_row)
    if nomenclature_idx is None or document_idx is None or amount_idx is None:
        return None

    parsed: list[_CostPreparedRow] = []
    for row in rows[header_index + 1 :]:
        document = normalize_text(cell_value(row, document_idx))
        if not document:
            continue
        raw_amount = cell_value(row, amount_idx)
        amount = parse_amount(raw_amount) if raw_amount not in (None, "") else None
        account = _account_value(cell_value(row, account_idx))
        calc_article = normalize_text(cell_value(row, calc_idx)) or "Сырье и материалы"
        parsed.append(
            _CostPreparedRow(
                nomenclature=normalize_text(cell_value(row, nomenclature_idx)),
                account=account,
                calc_article=calc_article,
                document=document,
                quantity=parse_amount(cell_value(row, quantity_idx)),
                amount=amount,
                section=_classify_section(calc_article, account),
            )
        )
    return parsed


def _apply_column_removal(rows: list[tuple[object, ...]]) -> list[tuple[object, ...]]:
    return [remove_column_indices(row, PQ_COST_REMOVE_COLUMN_INDICES) for row in rows]


def _load_cost_prepared_rows(rows: list[tuple[object, ...]]) -> list[_CostPreparedRow] | None:
    for variant in (_apply_column_removal(rows), rows):
        parsed = _parse_cost_rows(variant)
        if parsed is not None:
            return parsed
    return None


def _cost_row_with_project(cost: _CostPreparedRow, project: dict[str, object] | None) -> dict[str, object]:
    project = project or {}
    return {
        "Номенклатура": cost.nomenclature,
        "Счет": cost.account,
        "Документ": cost.document,
        "Количество": cost.quantity,
        "Сумма": cost.amount,
        "Раздел": cost.section,
        "Проект": normalize_text(project.get("Проект")),
        "Группа проектов": normalize_text(project.get("Группа проектов")),
        "Направление": normalize_text(project.get("Направление")),
    }


def _join_projects(
    cost_rows: list[_CostPreparedRow],
    project_rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    """PQ: NestedJoin → AddIndex → ExpandTableColumn → Distinct(Индекс)."""
    projects_index = build_projects_document_index(project_rows)

    joined: list[dict[str, object]] = []
    for cost in cost_rows:
        project = lookup_projects_for_document(
            projects_index,
            cost.document,
            nomenclature=cost.nomenclature,
        )
        joined.append(_cost_row_with_project(cost, project))
    return joined


def _combine_with_projects(
    joined_rows: list[dict[str, object]],
    project_rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    from almabi_pq_projects import PQ_PROJECTS_SECTION

    combined = list(joined_rows)
    for project in project_rows:
        raw_amount = project.get("Сумма")
        amount = parse_amount(raw_amount) if raw_amount not in (None, "") else None
        combined.append(
            {
                "Номенклатура": normalize_text(project.get("Номенклатура")),
                "Счет": None,
                "Документ": normalize_text(project.get("Документ")),
                "Количество": None,
                "Сумма": amount,
                "Раздел": normalize_text(project.get("Раздел")) or PQ_PROJECTS_SECTION,
                "Проект": normalize_text(project.get("Проект")),
                "Группа проектов": normalize_text(project.get("Группа проектов")),
                "Направление": normalize_text(project.get("Направление")),
            }
        )
    return combined


def _sum_amounts(values: list[object]) -> float | None:
    total = 0.0
    saw_value = False
    for value in values:
        if value is None or value == "":
            continue
        total += parse_amount(value)
        saw_value = True
    return total if saw_value else None


def _group_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    grouped: dict[tuple[object, ...], list[dict[str, object]]] = {}
    for row in rows:
        key = tuple(row.get(column) for column in GROUP_COLUMNS)
        grouped.setdefault(key, []).append(row)

    result: list[dict[str, object]] = []
    for key, items in sorted(grouped.items(), key=lambda item: item[0]):
        values = dict(zip(GROUP_COLUMNS, key, strict=True))
        section = normalize_text(values.get("Раздел"))
        summed = _sum_amounts([row.get("Сумма") for row in items])
        quantity = 0.0
        for row in items:
            raw = row.get("Количество")
            if raw in (None, ""):
                continue
            quantity = max(quantity, float(parse_amount(raw)))
        result.append(
            {
                **values,
                "Сумма": summed if summed is not None else 0.0,
                "Количество": quantity if quantity > 0 else None,
                "Основной раздел": _main_section(section),
            }
        )
    return result


def build_pq_cost_table(cost_path: Path, *, projects_path: Path | None = None) -> list[dict[str, object]]:
    prepared = _load_cost_prepared_rows(_prepare_raw_rows(read_workbook_rows(cost_path)))
    if prepared is None:
        return []

    project_rows: list[dict[str, object]] = []
    if projects_path is not None and projects_path.exists():
        from almabi_pq_projects import build_pq_projects_table

        project_rows = build_pq_projects_table(projects_path)

    joined = _join_projects(prepared, project_rows)
    combined = _combine_with_projects(joined, project_rows)
    return _group_rows(combined)


def table_summary(rows: list[dict[str, object]]) -> dict[str, object]:
    total = sum(float(row.get("Сумма") or 0) for row in rows)
    return {
        "row_count": len(rows),
        "total_amount": total,
        "columns": list(OUTPUT_COLUMNS),
    }
