"""Многоуровневое сопоставление строк для расшифровки выручки/себестоимости.

Приоритет ключей (от точного к общему):
1. период + идентификатор документа + номенклатура;
2. период + идентификатор документа + совпадение начала наименования;
3. период + идентификатор документа (только если кандидат один).

Наименование из бухгалтерии не используется как первичный ключ, если есть
строки «Реализация проекты» по тому же документу.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from almabi_excel_utils import document_match_keys, normalize_text
from almabi_export_parsers import RealizationRow
from almabi_pq_common import is_buh_revenue_activity_nomenclature, nomenclature_key

_DRILL_ANALYTICS_PLACEHOLDERS = frozenset(
    {
        "",
        "без направления",
        "без группы",
        "без проекта",
    }
)

_DOC_ID_PATTERN = re.compile(r"\d{2}[a-zа-я]{2}-\d+", re.IGNORECASE)
_COST_MERGE_OEZ_KEY = "__оэз__"
_NOMENCLATURE_PREFIX_LEN = 40
_MIN_PREFIX_LEN = 20


def drill_document_identity_key(document: str) -> str:
    """Стабильный идентификатор документа для расшифровки (номер отгрузки и т.п.)."""
    keys = document_match_keys(document)
    numbered = sorted(
        (key for key in keys if _DOC_ID_PATTERN.fullmatch(key)),
        key=len,
    )
    if numbered:
        return numbered[0]
    non_generic = sorted(
        (
            key
            for key in keys
            if key
            and not key.startswith("реализация")
            and " от " not in key
        ),
        key=len,
    )
    if non_generic:
        return non_generic[0]
    return min(keys, default="")


def drill_analytics_compatible(left: object, right: object) -> bool:
    """Аналитика совместима, если одна из сторон — заглушка «Без …»."""
    left_key = normalize_text(left).casefold()
    right_key = normalize_text(right).casefold()
    if left_key in _DRILL_ANALYTICS_PLACEHOLDERS or right_key in _DRILL_ANALYTICS_PLACEHOLDERS:
        return True
    return left_key == right_key


def drill_row_matches_rev_fact(row: RealizationRow, fact: Any, *, period: str) -> bool:
    """Строка реализации относится к факту выручки внутри клетки."""
    fact_period = normalize_text(getattr(fact, "period", ""))
    if fact_period != period:
        return False
    row_keys = document_match_keys(row.document)
    fact_keys = document_match_keys(getattr(fact, "document", ""))
    if not (row_keys & fact_keys):
        return False
    if not drill_analytics_compatible(getattr(fact, "direction", ""), row.direction):
        return False
    if not drill_analytics_compatible(getattr(fact, "project_group", ""), row.project_group):
        return False
    if not drill_analytics_compatible(getattr(fact, "project", ""), row.project):
        return False
    return True


def scope_realization_rows_for_drill(
    realization_rows: list[RealizationRow],
    rev_subset: list[Any],
) -> list[RealizationRow]:
    """Строки «Реализация проекты» для текущей клетки расшифровки."""
    if not realization_rows or not rev_subset:
        return []

    scoped: list[RealizationRow] = []
    seen: set[tuple[str, str, str]] = set()
    for row in realization_rows:
        period = normalize_text(row.period) or ""
        if not period:
            continue
        matched = any(
            drill_row_matches_rev_fact(row, fact, period=period) for fact in rev_subset
        )
        if not matched:
            continue
        dedupe_key = (
            period,
            drill_document_identity_key(row.document),
            nomenclature_key(row.nomenclature),
        )
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        scoped.append(row)
    return scoped


def covered_document_keys_for_realization_rows(rows: list[RealizationRow]) -> set[str]:
    keys: set[str] = set()
    for row in rows:
        keys.update(document_match_keys(row.document))
    return keys


def should_exclude_rev_fact_from_drill_fallback(
    fact: Any,
    *,
    covered_document_keys: set[str],
) -> bool:
    """Не дублировать в расшифровке агрегированную строку бухгалтерии."""
    fact_keys = document_match_keys(getattr(fact, "document", ""))
    if fact_keys & covered_document_keys:
        return True
    if is_buh_revenue_activity_nomenclature(getattr(fact, "nomenclature", "")):
        return True
    return False


def revenue_cost_drill_group_key(display_name: str) -> str:
    text = nomenclature_key(display_name)
    if text.startswith("оэз"):
        return _COST_MERGE_OEZ_KEY
    return text


@dataclass
class DrillCostLookup:
    by_doc_nomenclature: dict[tuple[str, str, str], dict[str, float]] = field(
        default_factory=dict
    )


def _merge_amounts(target: dict[str, float], buh: float, nu: float) -> None:
    target["buh"] = target.get("buh", 0.0) + buh
    target["nu"] = target.get("nu", 0.0) + nu


def build_drill_cost_lookup(
    cost_facts: list[Any],
    *,
    period_for_fact: Any,
    display_name_for_fact: Any,
) -> DrillCostLookup:
    lookup = DrillCostLookup()
    for fact in cost_facts:
        period = period_for_fact(fact)
        document = getattr(fact, "document", "")
        doc_id = drill_document_identity_key(document)
        if not period or not doc_id:
            continue
        name = display_name_for_fact(fact)
        nom_key = revenue_cost_drill_group_key(name)
        buh = abs(float(getattr(fact, "amount_buh", 0) or 0))
        nu = abs(float(getattr(fact, "amount_nu", 0) or 0))
        bucket = lookup.by_doc_nomenclature.setdefault(
            (period, doc_id, nom_key),
            {"buh": 0.0, "nu": 0.0},
        )
        _merge_amounts(bucket, buh, nu)
    return lookup


def lookup_drill_cost(
    lookup: DrillCostLookup,
    *,
    period: str,
    document: str,
    nomenclature: str,
) -> dict[str, float]:
    doc_id = drill_document_identity_key(document)
    if not period or not doc_id:
        return {"buh": 0.0, "nu": 0.0}

    nom_key = revenue_cost_drill_group_key(nomenclature)
    direct = lookup.by_doc_nomenclature.get((period, doc_id, nom_key))
    if direct is not None:
        return dict(direct)

    prefix = nom_key[:_NOMENCLATURE_PREFIX_LEN]
    if len(prefix) >= _MIN_PREFIX_LEN:
        prefix_candidates: list[dict[str, float]] = []
        for (p, d, candidate_key), bucket in lookup.by_doc_nomenclature.items():
            if p != period or d != doc_id:
                continue
            candidate_prefix = candidate_key[:_NOMENCLATURE_PREFIX_LEN]
            if candidate_key.startswith(prefix) or prefix.startswith(candidate_prefix):
                prefix_candidates.append(bucket)
        if len(prefix_candidates) == 1:
            return dict(prefix_candidates[0])

    doc_only: list[dict[str, float]] = [
        bucket
        for (p, d, _), bucket in lookup.by_doc_nomenclature.items()
        if p == period and d == doc_id
    ]
    if len(doc_only) == 1:
        return dict(doc_only[0])

    return {"buh": 0.0, "nu": 0.0}


def drill_operation_key(*, period: str, document: str, nomenclature: str) -> tuple[str, str, str]:
    """Ключ операции расшифровки: период, идентификатор документа, номенклатура."""
    return (
        period,
        drill_document_identity_key(document),
        revenue_cost_drill_group_key(nomenclature),
    )
