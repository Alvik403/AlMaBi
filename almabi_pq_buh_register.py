"""Запрос «Бух.регистр» — логика Power Query с join к «Себестоимость» и «Выручка»."""
from __future__ import annotations

from pathlib import Path

from almabi_excel_utils import normalize_header, normalize_text, parse_amount, parse_date, read_workbook_rows
from almabi_pq_common import (
    build_cost_pq_lookup,
    cell_value,
    find_header_row_index,
    lookup_cost_pq_rows,
    nomenclature_key,
    remove_column_indices,
    resolve_header_index,
)
from almabi_pq_cost import build_pq_cost_table
from almabi_pq_revenue import build_pq_revenue_table

PQ_BUH_SKIP_ROWS = 8
PQ_BUH_REMOVE_LAST = 1
PQ_BUH_REMOVE_COLUMN_INDICES = frozenset({1, 2, 5, 26})

DEFAULT_TAX_TYPE = "Общие условия налогообложения"

OUTPUT_COLUMNS = (
    "Документ",
    "Дата",
    "Счет Дт",
    "Счет Кт",
    "Субконто1 Кт",
    "Раздел",
    "Основной раздел",
    "Вид НО",
    "Сумма",
    "Сумма НУ",
    "Сумма БУ",
    "Статья дохода расхода",
    "Себестоимость.Счет",
    "Себестоимость.Сумма",
    "Себестоимость.Раздел",
    "Проект",
    "Группа проектов",
    "Направление",
)


def _is_buh_header(headers: list[str]) -> bool:
    joined = " | ".join(normalize_header(header) for header in headers if header)
    return "документ" in joined and "сумма" in joined and "счет дт" in joined


def _prepare_raw_rows(raw_rows: list[tuple[object, ...]]) -> list[tuple[object, ...]]:
    if len(raw_rows) <= PQ_BUH_SKIP_ROWS:
        return []
    rows = list(raw_rows[PQ_BUH_SKIP_ROWS :])
    if len(rows) > PQ_BUH_REMOVE_LAST:
        rows = rows[: -PQ_BUH_REMOVE_LAST]
    return rows


def classify_pq_buh_section(account_dt: str, account_kt: str) -> str | None:
    if account_dt == "90.02.1":
        return "Себестоимость"
    if account_kt == "90.01.3":
        return "Выручка"
    if account_kt == "91.01":
        return "Прочие доходы"
    if account_dt == "91.02":
        return "Прочие расходы"
    if account_dt == "90.07.1":
        return "Расходы на продажу"
    if account_dt == "90.08.1":
        return "Управленческие расходы"
    return None


def classify_pq_main_section(section: str | None) -> str | None:
    if section in {"Выручка", "Прочие доходы"}:
        return "Доходы"
    if section == "Себестоимость":
        return "Расходы"
    if section and "расходы" in section.casefold():
        return "Расходы"
    return None


def _extract_tax_type(
    *,
    kind_subconto2_dt: str,
    subconto2_dt: str,
    kind_subconto3_kt: str,
    subconto3_kt: str,
    kind_subconto3_dt: str,
    subconto3_dt: str,
    kind_subconto1_dt: str,
    subconto1_dt: str,
) -> str:
    if kind_subconto2_dt == "Варианты налогообложения прибыли" and subconto2_dt:
        return subconto2_dt
    if kind_subconto3_kt == "Варианты налогообложения прибыли" and subconto3_kt:
        return subconto3_kt
    if kind_subconto3_dt == "Варианты налогообложения прибыли" and subconto3_dt:
        return subconto3_dt
    if kind_subconto1_dt == "Варианты налогообложения прибыли" and subconto1_dt:
        return subconto1_dt
    return DEFAULT_TAX_TYPE


def _expense_article(
    account_dt: str,
    account_kt: str,
    *,
    subconto1_dt: str,
    subconto1_kt: str,
    subconto2_kt: str,
    kind_subconto1_kt: str,
) -> str | None:
    if account_dt == "91.02":
        return subconto1_dt or None
    if account_kt == "91.01":
        return subconto1_kt or None
    if account_dt == "90.07.1":
        if kind_subconto1_kt == "Статьи затрат":
            return subconto1_kt or None
        return subconto2_kt or None
    if account_dt == "90.08.1":
        if kind_subconto1_kt == "Статьи затрат":
            return subconto1_kt or None
        return subconto2_kt or None
    return None


def _amount_nu(section: str | None, amount_nu_dt: float, amount_nu_kt: float) -> float:
    if section == "Себестоимость":
        return amount_nu_kt * -1
    if section == "Прочие расходы":
        return amount_nu_dt * -1
    if section == "Прочие доходы":
        return amount_nu_kt
    if section == "Расходы на продажу":
        return amount_nu_dt * -1
    if section == "Управленческие расходы":
        return amount_nu_dt * -1
    return amount_nu_kt


def _amount_buh(
    section: str | None,
    amount: float,
    *,
    cost_section: object,
    cost_amount: float | None,
) -> float:
    if section == "Себестоимость" and cost_section not in (None, ""):
        return float(cost_amount or 0) * -1
    if section == "Прочие расходы":
        return amount * -1
    if section == "Прочие доходы":
        return amount
    if section == "Управленческие расходы":
        return amount * -1
    if section == "Расходы на продажу":
        return amount * -1
    return amount


def _coalesce_pq(cost_value: object, rev_value: object) -> str | None:
    cost = normalize_text(cost_value)
    rev = normalize_text(rev_value)
    if not cost and rev:
        return rev
    if cost and not rev:
        return cost
    return None


def _build_cost_lookup(cost_rows: list[dict[str, object]]) -> tuple[
    dict[tuple[str, str, str], list[dict[str, object]]],
    dict[tuple[str, str], list[dict[str, object]]],
]:
    return build_cost_pq_lookup(cost_rows)


def _build_revenue_lookup(revenue_rows: list[dict[str, object]]) -> dict[tuple[str, str], list[dict[str, object]]]:
    lookup: dict[tuple[str, str], list[dict[str, object]]] = {}
    for row in revenue_rows:
        document = normalize_text(row.get("Документ"))
        section = normalize_text(row.get("Раздел"))
        if not document:
            continue
        lookup.setdefault((document, section), []).append(row)
    return lookup


def _left_expand_join(
    rows: list[dict[str, object]],
    lookup: dict[tuple[str, ...], list[dict[str, object]]],
    *,
    key_fn: object,
    match_field: str,
) -> list[dict[str, object]]:
    """NestedJoin + ExpandTableColumn: каждое совпадение — отдельная строка."""
    expanded: list[dict[str, object]] = []
    for row in rows:
        key = key_fn(row)
        matches = lookup.get(key, []) if key is not None else []
        if not matches:
            expanded.append({**row, match_field: None})
            continue
        for match in matches:
            expanded.append({**row, match_field: match})
    return expanded


def _resolve_amount_index(headers: list[str]) -> int | None:
    """Колонка «Сумма» — точное имя, не «Сумма НУ Дт/Кт»."""
    for index, header in enumerate(headers):
        if normalize_header(header) == "сумма":
            return index
    return resolve_header_index(headers, ("сумма",))


def _parse_buh_rows(rows: list[tuple[object, ...]]) -> list[dict[str, object]] | None:
    if not rows:
        return []

    header_index = 0
    headers = [normalize_text(value) for value in rows[header_index]]
    if not _is_buh_header(headers):
        header_index = find_header_row_index(rows, matcher=_is_buh_header)
        if header_index is None:
            return None
        headers = [normalize_text(value) for value in rows[header_index]]

    document_idx = resolve_header_index(headers, ("документ", "document"))
    account_dt_idx = resolve_header_index(headers, ("счет дт", "account dt"))
    account_kt_idx = resolve_header_index(headers, ("счет кт", "account kt"))
    amount_idx = _resolve_amount_index(headers)
    amount_nu_dt_idx = resolve_header_index(headers, ("сумма ну дт",))
    amount_nu_kt_idx = resolve_header_index(headers, ("сумма ну кт",))
    date_idx = resolve_header_index(headers, ("дата", "date"))
    subconto1_dt_idx = resolve_header_index(headers, ("субконто1 дт",))
    subconto1_kt_idx = resolve_header_index(headers, ("субконто1 кт",))
    subconto2_dt_idx = resolve_header_index(headers, ("субконто2 дт",))
    subconto2_kt_idx = resolve_header_index(headers, ("субконто2 кт",))
    subconto3_dt_idx = resolve_header_index(headers, ("субконто3 дт",))
    subconto3_kt_idx = resolve_header_index(headers, ("субконто3 кт",))
    kind_subconto1_dt_idx = resolve_header_index(headers, ("вид субконто1 дт",))
    kind_subconto1_kt_idx = resolve_header_index(headers, ("вид субконто1 кт",))
    kind_subconto2_dt_idx = resolve_header_index(headers, ("вид субконто2 дт",))
    kind_subconto3_dt_idx = resolve_header_index(headers, ("вид субконто3 дт",))
    kind_subconto3_kt_idx = resolve_header_index(headers, ("вид субконто3 кт",))

    if document_idx is None or amount_idx is None:
        return None

    parsed: list[dict[str, object]] = []
    for row in rows[header_index + 1 :]:
        document = normalize_text(cell_value(row, document_idx))
        account_dt = normalize_text(cell_value(row, account_dt_idx))
        account_kt = normalize_text(cell_value(row, account_kt_idx))
        amount = parse_amount(cell_value(row, amount_idx))
        amount_nu_dt = parse_amount(cell_value(row, amount_nu_dt_idx))
        amount_nu_kt = parse_amount(cell_value(row, amount_nu_kt_idx))

        subconto1_dt = normalize_text(cell_value(row, subconto1_dt_idx))
        subconto1_kt = normalize_text(cell_value(row, subconto1_kt_idx))
        subconto2_kt = normalize_text(cell_value(row, subconto2_kt_idx))
        kind_subconto1_kt = normalize_text(cell_value(row, kind_subconto1_kt_idx))

        section = classify_pq_buh_section(account_dt, account_kt)
        main_section = classify_pq_main_section(section)
        tax_type = _extract_tax_type(
            kind_subconto2_dt=normalize_text(cell_value(row, kind_subconto2_dt_idx)),
            subconto2_dt=normalize_text(cell_value(row, subconto2_dt_idx)),
            kind_subconto3_kt=normalize_text(cell_value(row, kind_subconto3_kt_idx)),
            subconto3_kt=normalize_text(cell_value(row, subconto3_kt_idx)),
            kind_subconto3_dt=normalize_text(cell_value(row, kind_subconto3_dt_idx)),
            subconto3_dt=normalize_text(cell_value(row, subconto3_dt_idx)),
            kind_subconto1_dt=normalize_text(cell_value(row, kind_subconto1_dt_idx)),
            subconto1_dt=subconto1_dt,
        )
        expense_article = _expense_article(
            account_dt,
            account_kt,
            subconto1_dt=subconto1_dt,
            subconto1_kt=subconto1_kt,
            subconto2_kt=subconto2_kt,
            kind_subconto1_kt=kind_subconto1_kt,
        )
        amount_nu = _amount_nu(section, amount_nu_dt, amount_nu_kt)

        raw_date = cell_value(row, date_idx)
        date_value = parse_date(raw_date)
        date_text = date_value.isoformat() if date_value else normalize_text(raw_date)

        parsed.append(
            {
                "Документ": document,
                "Дата": date_text,
                "Счет Дт": account_dt,
                "Счет Кт": account_kt,
                "Субконто1 Кт": subconto1_kt,
                "Раздел": section,
                "Основной раздел": main_section,
                "Вид НО": tax_type,
                "Сумма": amount,
                "Сумма НУ": amount_nu,
                "Статья дохода расхода": expense_article,
                "_subconto1_kt": subconto1_kt,
            }
        )
    return parsed



def _revenue_join_key(row: dict[str, object]) -> tuple[str, str] | None:
    main_section = normalize_text(row.get("Основной раздел"))
    if not main_section:
        return None
    return (normalize_text(row.get("Документ")), main_section)


def _row_to_output(row: dict[str, object]) -> dict[str, object]:
    cost_match = row.get("_cost") if isinstance(row.get("_cost"), dict) else None
    revenue_match = row.get("_revenue") if isinstance(row.get("_revenue"), dict) else None
    section = normalize_text(row.get("Раздел")) or None

    cost_section = cost_match.get("Раздел") if cost_match else None
    cost_amount = cost_match.get("Сумма") if cost_match else None
    amount_buh = _amount_buh(
        section,
        float(row.get("Сумма") or 0),
        cost_section=cost_section,
        cost_amount=float(cost_amount) if cost_amount not in (None, "") else None,
    )

    return {
        "Документ": row.get("Документ"),
        "Дата": row.get("Дата"),
        "Счет Дт": row.get("Счет Дт"),
        "Счет Кт": row.get("Счет Кт"),
        "Субконто1 Кт": row.get("Субконто1 Кт"),
        "Раздел": row.get("Раздел"),
        "Основной раздел": row.get("Основной раздел"),
        "Вид НО": row.get("Вид НО"),
        "Сумма": row.get("Сумма"),
        "Сумма НУ": row.get("Сумма НУ"),
        "Сумма БУ": amount_buh,
        "Статья дохода расхода": row.get("Статья дохода расхода"),
        "Себестоимость.Счет": cost_match.get("Счет") if cost_match else None,
        "Себестоимость.Сумма": cost_match.get("Сумма") if cost_match else None,
        "Себестоимость.Раздел": cost_section,
        "Проект": _coalesce_pq(
            cost_match.get("Проект") if cost_match else None,
            revenue_match.get("Проект") if revenue_match else None,
        ),
        "Группа проектов": _coalesce_pq(
            cost_match.get("Группа проектов") if cost_match else None,
            revenue_match.get("Группа проектов") if revenue_match else None,
        ),
        "Направление": _coalesce_pq(
            cost_match.get("Направление") if cost_match else None,
            revenue_match.get("Направление") if revenue_match else None,
        ),
    }


def _join_cost_rows(
    buh_rows: list[dict[str, object]],
    *,
    by_full_key: dict[tuple[str, str, str], list[dict[str, object]]],
    by_doc_section: dict[tuple[str, str], list[dict[str, object]]],
) -> list[dict[str, object]]:
    expanded: list[dict[str, object]] = []
    for row in buh_rows:
        main_section = normalize_text(row.get("Основной раздел"))
        if not main_section:
            expanded.append({**row, "_cost": None})
            continue
        matches = lookup_cost_pq_rows(
            by_full_key,
            by_doc_section,
            document=normalize_text(row.get("Документ")),
            main_section=main_section,
            nomenclature=normalize_text(row.get("_subconto1_kt")),
        )
        if not matches:
            expanded.append({**row, "_cost": None})
            continue
        for match in matches:
            expanded.append({**row, "_cost": match})
    return expanded


def _apply_joins(
    buh_rows: list[dict[str, object]],
    *,
    cost_rows: list[dict[str, object]],
    revenue_rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    cost_by_full, cost_by_doc_section = _build_cost_lookup(cost_rows)
    revenue_lookup = _build_revenue_lookup(revenue_rows)

    after_cost = _join_cost_rows(
        buh_rows,
        by_full_key=cost_by_full,
        by_doc_section=cost_by_doc_section,
    )
    after_revenue = _left_expand_join(
        after_cost,
        revenue_lookup,
        key_fn=_revenue_join_key,
        match_field="_revenue",
    )
    return [_row_to_output(row) for row in after_revenue]


def build_pq_buh_register_table(
    buh_path: Path,
    *,
    cost_path: Path | None = None,
    revenue_path: Path | None = None,
    projects_path: Path | None = None,
) -> list[dict[str, object]]:
    raw_rows = _prepare_raw_rows(read_workbook_rows(buh_path))
    if not raw_rows:
        return []

    buh_rows: list[dict[str, object]] | None = None
    for variant in (
        [remove_column_indices(row, PQ_BUH_REMOVE_COLUMN_INDICES) for row in raw_rows],
        raw_rows,
    ):
        parsed = _parse_buh_rows(variant)
        if parsed is not None:
            buh_rows = parsed
            break
    if not buh_rows:
        return []

    cost_rows: list[dict[str, object]] = []
    if cost_path is not None and cost_path.exists():
        cost_rows = build_pq_cost_table(cost_path, projects_path=projects_path)

    revenue_rows: list[dict[str, object]] = []
    if revenue_path is not None and revenue_path.exists():
        revenue_rows = build_pq_revenue_table(revenue_path)

    return _apply_joins(buh_rows, cost_rows=cost_rows, revenue_rows=revenue_rows)


def table_summary(rows: list[dict[str, object]]) -> dict[str, object]:
    total = sum(float(row.get("Сумма БУ") or 0) for row in rows)
    return {
        "row_count": len(rows),
        "total_amount": total,
        "amount_column": "Сумма БУ",
        "columns": list(OUTPUT_COLUMNS),
    }
