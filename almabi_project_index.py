from __future__ import annotations

from dataclasses import dataclass

from almabi_excel_utils import EMPTY_ANALYTICS, analytics_value, document_match_keys
from almabi_export_parsers import ParsedExports


@dataclass(frozen=True)
class ProjectMeta:
    direction: str = "Без направления"
    project_group: str = "Без группы"
    project: str = "Без проекта"


def _is_meaningful(value: str) -> bool:
    return value.casefold() not in EMPTY_ANALYTICS


def _merge_meta(current: ProjectMeta | None, new: ProjectMeta) -> ProjectMeta:
    if current is None:
        return new
    return ProjectMeta(
        direction=new.direction if _is_meaningful(new.direction) else current.direction,
        project_group=new.project_group if _is_meaningful(new.project_group) else current.project_group,
        project=new.project if _is_meaningful(new.project) else current.project,
    )


def build_project_index(exports: ParsedExports) -> tuple[dict[str, ProjectMeta], dict[str, str]]:
    by_document: dict[str, ProjectMeta] = {}
    key_to_document: dict[str, str] = {}

    def register(document: str, direction: str, project_group: str, project: str) -> None:
        document = document.strip()
        if not document:
            return
        meta = ProjectMeta(
            direction=analytics_value(direction, default="Без направления"),
            project_group=analytics_value(project_group, default="Без группы"),
            project=analytics_value(project, default="Без проекта"),
        )
        by_document[document] = _merge_meta(by_document.get(document), meta)
        for key in document_match_keys(document):
            key_to_document.setdefault(key, document)
            canonical = key_to_document[key]
            by_document[canonical] = _merge_meta(by_document.get(canonical), meta)

    for row in exports.realization:
        register(row.document, row.direction, row.project_group, row.project)
    for row in exports.cost:
        register(row.document, row.direction, row.project_group, row.project)

    return by_document, key_to_document


def lookup_project(
    document: str,
    by_document: dict[str, ProjectMeta],
    key_to_document: dict[str, str],
    *,
    fallback_project: str = "",
) -> ProjectMeta:
    document = document.strip()
    if document in by_document:
        return by_document[document]

    for key in document_match_keys(document):
        canonical = key_to_document.get(key)
        if canonical and canonical in by_document:
            return by_document[canonical]

    document_keys = document_match_keys(document)
    for canonical, meta in by_document.items():
        if document_keys & document_match_keys(canonical):
            return meta

    return ProjectMeta(
        direction="Без направления",
        project_group="Без группы",
        project=analytics_value(fallback_project, default="Без проекта"),
    )
