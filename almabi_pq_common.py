"""Общие утилиты для повторения логики Power Query."""
from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from almabi_excel_utils import document_match_keys, header_matches, normalize_header, normalize_text

RowT = TypeVar("RowT")


def remove_column_indices(row: tuple[object, ...], indices: frozenset[int]) -> tuple[object, ...]:
    return tuple(value for index, value in enumerate(row) if index not in indices)


def nomenclature_key(value: object) -> str:
    return normalize_text(value).casefold()


def register_document_lookup(
    lookup: dict[tuple[str, ...], list[RowT]],
    *,
    document: str,
    key_suffix: tuple[str, ...],
    row: RowT,
) -> None:
    document = normalize_text(document)
    if not document:
        return
    for doc_key in document_match_keys(document):
        lookup.setdefault((doc_key, *key_suffix), []).append(row)


def lookup_document_rows(
    lookup: dict[tuple[str, ...], list[RowT]],
    *,
    document: str,
    key_suffix: tuple[str, ...],
) -> list[RowT]:
    for doc_key in document_match_keys(document):
        matches = lookup.get((doc_key, *key_suffix))
        if matches:
            return list(matches)
    return []


def pick_project_row(
    matches: list[dict[str, object]],
    *,
    nomenclature: str = "",
) -> dict[str, object] | None:
    if not matches:
        return None
    nom = nomenclature_key(nomenclature)
    if nom:
        for match in matches:
            if nomenclature_key(match.get("Номенклатура")) == nom:
                return match
    return matches[0]


def build_projects_document_index(
    project_rows: list[dict[str, object]],
) -> dict[str, list[dict[str, object]]]:
    index: dict[str, list[dict[str, object]]] = {}
    for project in project_rows:
        document = normalize_text(project.get("Документ"))
        if not document:
            continue
        for doc_key in document_match_keys(document):
            index.setdefault(doc_key, []).append(project)
    return index


def lookup_projects_for_document(
    index: dict[str, list[dict[str, object]]],
    document: str,
    *,
    nomenclature: str = "",
) -> dict[str, object] | None:
    for doc_key in document_match_keys(document):
        match = pick_project_row(index.get(doc_key, []), nomenclature=nomenclature)
        if match is not None:
            return match
    return None


def build_cost_pq_lookup(
    cost_rows: list[dict[str, object]],
) -> tuple[
    dict[tuple[str, str, str], list[dict[str, object]]],
    dict[tuple[str, str], list[dict[str, object]]],
]:
    """Индекс себестоимости: (doc_key, основной раздел, номенклатура) и (doc_key, раздел)."""
    by_full_key: dict[tuple[str, str, str], list[dict[str, object]]] = {}
    by_doc_section: dict[tuple[str, str], list[dict[str, object]]] = {}
    for row in cost_rows:
        document = normalize_text(row.get("Документ"))
        main_section = normalize_text(row.get("Основной раздел"))
        nomenclature = nomenclature_key(row.get("Номенклатура"))
        if not document or not main_section or not nomenclature:
            continue
        for doc_key in document_match_keys(document):
            by_full_key.setdefault((doc_key, main_section, nomenclature), []).append(row)
            by_doc_section.setdefault((doc_key, main_section), []).append(row)
    return by_full_key, by_doc_section


def _row_nomenclature_key(row: object) -> str:
    if isinstance(row, dict):
        return nomenclature_key(row.get("Номенклатура"))
    return nomenclature_key(getattr(row, "nomenclature", ""))


def lookup_cost_pq_rows(
    by_full_key: dict[tuple[str, str, str], list[object]],
    by_doc_section: dict[tuple[str, str], list[object]],
    *,
    document: str,
    main_section: str,
    nomenclature: str,
) -> list[object]:
    main_section = normalize_text(main_section)
    nomenclature = nomenclature_key(nomenclature)
    if not main_section or not nomenclature:
        return []

    for doc_key in document_match_keys(document):
        matches = by_full_key.get((doc_key, main_section, nomenclature))
        if matches:
            return list(matches)

    for doc_key in document_match_keys(document):
        candidates = by_doc_section.get((doc_key, main_section), [])
        if not candidates:
            continue
        same_nom = [row for row in candidates if _row_nomenclature_key(row) == nomenclature]
        if same_nom:
            return same_nom
    return []


def resolve_header_index(headers: list[str], candidates: tuple[str, ...]) -> int | None:
    """Сначала приоритет alias, затем точное совпадение header_matches (не «% от себестоимости»)."""
    normalized_headers = [normalize_header(header) for header in headers]
    for candidate in candidates:
        candidate_value = candidate.casefold()
        for index, header in enumerate(normalized_headers):
            if header_matches(header, candidate_value):
                return index
    return None


def find_header_row_index(
    rows: list[tuple[object, ...]],
    *,
    matcher: Callable[[list[str]], bool],
    scan_limit: int = 40,
) -> int | None:
    for index, row in enumerate(rows[:scan_limit]):
        headers = [normalize_text(value) for value in row]
        if matcher(headers):
            return index
    return None


def cell_value(row: tuple[object, ...], index: int | None) -> object:
    if index is None or index >= len(row):
        return None
    return row[index]
