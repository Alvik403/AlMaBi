from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field, replace
from pathlib import Path

from almabi_excel_utils import (
    MONTH_NAMES,
    analytics_value,
    document_match_keys,
    normalize_text,
    period_or_month,
    period_sort_key,
    tax_bucket,
)
from almabi_export_parsers import (
    BuhRow,
    CostNuRow,
    CostRow,
    ParsedExports,
    RealizationRow,
    classify_buh_section,
    classify_cost_section_pq,
    parse_exports,
)
from almabi_project_index import ProjectMeta, build_project_index, lookup_project
from almabi_pq_common import is_buh_revenue_activity_nomenclature, nomenclature_key
from almabi_realization_lookup import (
    build_realization_index,
    lookup_exact_realization_operation,
    lookup_realization_for_revenue_amount,
    resolve_realization_match,
    resolve_revenue_analytics_match,
)

OTHER_PNL_SECTIONS = frozenset({"Прочие доходы", "Прочие расходы"})
COST_ROUNDING_ARTICLE = "Погрешность расчета себестоимости"
# Положительное списание ТМЦ (Кт 10.*) на эту статью не входит в анализ 91.02
# по вариантам НО. Отрицательное сторно сохраняется как межпериодная корректировка.
NON_DEDUCTIBLE_INVENTORY_ARTICLE = "Расходы, не принимаемые в НУ (НЕ)"


def _skip_other_expense_inventory_non_deductible(row: BuhRow, section: str) -> bool:
    """Пропускать исходное списание запасов, сохраняя его последующее сторно."""
    if section != "Прочие расходы":
        return False
    if (row.expense_article or "") != NON_DEDUCTIBLE_INVENTORY_ARTICLE:
        return False
    if not (row.account_kt or "").startswith("10"):
        return False
    return float(row.amount_buh or 0) > 0


@dataclass(frozen=True)
class Fact:
    kpi_l1: str
    month: str
    amount_buh: float
    amount_nu: float
    direction: str = ""
    project_group: str = ""
    project: str = ""
    contract: str = ""
    nomenclature: str = ""
    cost_section: str = ""
    cost_account: str = ""
    expense_article: str = ""
    document: str = ""
    tax_type: str = ""
    contractor: str = ""
    quantity: float = 0.0
    period: str | None = None


def _same_period(left: object, right: object) -> bool:
    """Сравнить фактический период, сохранив fallback для старых объектов."""
    left_period = normalize_text(getattr(left, "period", ""))
    right_period = normalize_text(getattr(right, "period", ""))
    if left_period and right_period:
        return left_period == right_period
    return normalize_text(getattr(left, "month", "")) == normalize_text(getattr(right, "month", ""))


@dataclass
class PipelineResult:
    facts: list[Fact] = field(default_factory=list)
    months: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    realization_rows: list = field(default_factory=list)


def _lookup_contract(document: str, doc_contract: dict[str, str]) -> str:
    if document in doc_contract:
        return doc_contract[document]
    document_keys = document_match_keys(document)
    for contract_document, contract_value in doc_contract.items():
        if document_keys & document_match_keys(contract_document):
            return contract_value
    return ""


def _merge_doc_tax(doc_tax: dict[str, str], row: BuhRow) -> None:
    if not row.document or not row.tax_type:
        return

    document = row.document
    incoming = row.tax_type
    current = doc_tax.get(document)
    if not current:
        doc_tax[document] = incoming
        return
    if tax_bucket(incoming) == "Льготные проекты":
        doc_tax[document] = incoming
        return
    if tax_bucket(current) == "Льготные проекты":
        return
    if row.account_kt == "90.01.3":
        doc_tax[document] = incoming


def _resolve_fact_tax_type(doc_tax: dict[str, str], document: str, row_tax_type: str) -> str:
    """Вид НО документа: из doc_tax (выручка перебивает cost), иначе с текущей строки."""
    fallback = row_tax_type or "Общие условия налогообложения"
    if not document:
        return fallback
    return doc_tax.get(document, fallback)


def _other_pnl_nu_mismatch_documents(exports: ParsedExports) -> frozenset[str]:
    """Документы с расхождением БУ и НУ в прочих доходах/расходах (курсовые стorno)."""
    documents: set[str] = set()
    for row in exports.buh:
        if not row.month:
            continue
        section = classify_buh_section(row.account_dt, row.account_kt)
        if section not in OTHER_PNL_SECTIONS:
            continue
        amount_buh = abs(row.amount_buh or 0)
        amount_nu = abs(_amount_nu_for_section(section, row.amount_nu_dt, row.amount_nu_kt))
        if amount_buh > 0.01 and amount_nu > 0.01 and abs(amount_buh - amount_nu) > 0.01:
            documents.add(row.document)
    return frozenset(documents)


def _build_other_pnl_section_has_nu(exports: ParsedExports) -> frozenset[tuple[str, str, str]]:
    """Документ/месяц/раздел прочих P&L, где в разделе есть ненулевой НУ."""
    keys: set[tuple[str, str, str]] = set()
    for row in exports.buh:
        if not row.month:
            continue
        section = classify_buh_section(row.account_dt, row.account_kt)
        if section not in OTHER_PNL_SECTIONS:
            continue
        amount_nu = _amount_nu_for_section(section, row.amount_nu_dt, row.amount_nu_kt)
        if abs(amount_nu) >= 0.01:
            keys.add((row.document, period_or_month(row), section))
    return frozenset(keys)


def _other_pnl_expense_amounts_mismatch(row: BuhRow, section: str) -> bool:
    """Строка прочих расходов, где |БУ| и |НУ| оба ненулевые и не совпадают."""
    if section != "Прочие расходы":
        return False
    amount_buh = abs(_amount_buh_for_section(section, row, None))
    amount_nu = abs(_amount_nu_for_section(section, row.amount_nu_dt, row.amount_nu_kt))
    return amount_buh >= 0.01 and amount_nu >= 0.01 and abs(amount_buh - amount_nu) > 0.01


def _build_other_pnl_storno_groups(
    exports: ParsedExports,
) -> dict[tuple[str, str, float], list[BuhRow]]:
    groups: dict[tuple[str, str, float], list[BuhRow]] = defaultdict(list)
    for row in exports.buh:
        if not row.month:
            continue
        section = classify_buh_section(row.account_dt, row.account_kt)
        if section not in OTHER_PNL_SECTIONS:
            continue
        amount = abs(row.amount_buh or 0)
        if amount < 0.01:
            continue
        groups[(row.document, section, round(amount, 2))].append(row)
    return groups


def _resolve_other_pnl_tax_type(
    row: BuhRow,
    *,
    storno_groups: dict[tuple[str, str, float], list[BuhRow]],
    nu_mismatch_docs: frozenset[str],
    section_has_nu: frozenset[tuple[str, str, str]] | None = None,
) -> str:
    """Стorno-строка с «Общие условия» наследует льготный НО от зеркальной проводки документа."""
    if row.expense_article and COST_ROUNDING_ARTICLE in row.expense_article:
        return row.tax_type or "Общие условия налогообложения"
    fallback = row.tax_type or "Общие условия налогообложения"
    if tax_bucket(fallback) == "Льготные проекты":
        return fallback
    if row.document not in nu_mismatch_docs:
        return fallback

    section = classify_buh_section(row.account_dt, row.account_kt)
    if section not in OTHER_PNL_SECTIONS:
        return fallback

    if section_has_nu is not None and (row.document, period_or_month(row), section) not in section_has_nu:
        return fallback

    amount_buh = abs(_amount_buh_for_section(section, row, None))
    amount_nu = abs(_amount_nu_for_section(section, row.amount_nu_dt, row.amount_nu_kt))
    if _other_pnl_expense_amounts_mismatch(row, section):
        return fallback
    if (
        section == "Прочие расходы"
        and amount_buh >= 0.01
        and amount_nu >= 0.01
        and abs(amount_buh - amount_nu) <= 0.01
        and section_has_nu is not None
        and (row.document, period_or_month(row), "Прочие доходы") not in section_has_nu
    ):
        return fallback

    key = (row.document, section, round(abs(row.amount_buh or 0), 2))
    for candidate in storno_groups.get(key, []):
        if candidate is row:
            continue
        if tax_bucket(candidate.tax_type) != "Льготные проекты":
            continue
        if (row.amount_buh or 0) * (candidate.amount_buh or 0) < 0:
            return candidate.tax_type
    return fallback


def _resolve_other_pnl_nu_tax_type(
    row: BuhRow,
    *,
    exports: ParsedExports,
    doc_tax: dict[str, str],
    buh_storno_groups: dict[tuple[str, str, float], list[BuhRow]],
    nu_storno_groups: dict[tuple[str, str, float], list[BuhRow]],
    nu_mismatch_docs: frozenset[str],
    section_has_nu: frozenset[tuple[str, str, str]] | None = None,
) -> str:
    """Вид НО для разреза «Факт НУ»: nu-only строки наследуют tax с buh-стороны сторно."""
    section = classify_buh_section(row.account_dt, row.account_kt)
    if section not in OTHER_PNL_SECTIONS:
        return row.tax_type or doc_tax.get(row.document, "Общие условия налогообложения")

    if _other_pnl_expense_amounts_mismatch(row, section):
        return row.tax_type or doc_tax.get(row.document, "Общие условия налогообложения")

    amount_buh = abs(_amount_buh_for_section(section, row, None))
    amount_nu = abs(_amount_nu_for_section(section, row.amount_nu_dt, row.amount_nu_kt))
    if (
        section == "Прочие расходы"
        and amount_buh >= 0.01
        and amount_nu >= 0.01
        and abs(amount_buh - amount_nu) <= 0.01
        and section_has_nu is not None
        and (row.document, period_or_month(row), "Прочие доходы") not in section_has_nu
    ):
        return row.tax_type or doc_tax.get(row.document, "Общие условия налогообложения")

    buh_tax = _resolve_row_tax_type(
        section,
        row,
        doc_tax,
        other_pnl_storno_groups=buh_storno_groups,
        other_pnl_nu_mismatch_docs=nu_mismatch_docs,
        other_pnl_section_has_nu=section_has_nu,
    )
    if row.expense_article and COST_ROUNDING_ARTICLE in row.expense_article:
        return row.tax_type or doc_tax.get(row.document, "Общие условия налогообложения")
    if row.document not in nu_mismatch_docs:
        return buh_tax

    buh_raw = abs(row.amount_buh or 0)
    nu_amount = _amount_nu_for_section(section, row.amount_nu_dt, row.amount_nu_kt)
    nu_raw = abs(nu_amount)
    if buh_raw >= 0.01 or nu_raw < 0.01:
        return buh_tax

    for candidate in exports.buh:
        if candidate.document != row.document or not _same_period(candidate, row):
            continue
        cand_section = classify_buh_section(candidate.account_dt, candidate.account_kt)
        if cand_section != section:
            continue
        if round(abs(candidate.amount_buh or 0), 2) != round(nu_raw, 2):
            continue
        return _resolve_row_tax_type(
            section,
            candidate,
            doc_tax,
            other_pnl_storno_groups=buh_storno_groups,
            other_pnl_nu_mismatch_docs=nu_mismatch_docs,
            other_pnl_section_has_nu=section_has_nu,
        )

    fallback = row.tax_type or doc_tax.get(row.document, "Общие условия налогообложения")
    if tax_bucket(fallback) == "Льготные проекты":
        return fallback

    key = (row.document, section, round(nu_raw, 2))
    for candidate in nu_storno_groups.get(key, []):
        if candidate is row:
            continue
        if tax_bucket(candidate.tax_type) != "Льготные проекты":
            continue
        cand_nu = _amount_nu_for_section(section, candidate.amount_nu_dt, candidate.amount_nu_kt)
        if nu_amount * cand_nu < 0:
            return candidate.tax_type
    return fallback


def _resolve_row_tax_type(
    section: str,
    row: BuhRow,
    doc_tax: dict[str, str],
    *,
    other_pnl_storno_groups: dict[tuple[str, str, float], list[BuhRow]] | None = None,
    other_pnl_nu_mismatch_docs: frozenset[str] | None = None,
    other_pnl_section_has_nu: frozenset[tuple[str, str, str]] | None = None,
) -> str:
    if section == "Себестоимость":
        return _resolve_fact_tax_type(doc_tax, row.document, row.tax_type)
    if (
        section in OTHER_PNL_SECTIONS
        and other_pnl_storno_groups is not None
        and other_pnl_nu_mismatch_docs is not None
    ):
        return _resolve_other_pnl_tax_type(
            row,
            storno_groups=other_pnl_storno_groups,
            nu_mismatch_docs=other_pnl_nu_mismatch_docs,
            section_has_nu=other_pnl_section_has_nu,
        )
    return row.tax_type or doc_tax.get(row.document, "Общие условия налогообложения")


def _build_other_pnl_nu_storno_groups(
    exports: ParsedExports,
) -> dict[tuple[str, str, float], list[BuhRow]]:
    groups: dict[tuple[str, str, float], list[BuhRow]] = defaultdict(list)
    for row in exports.buh:
        if not row.month:
            continue
        section = classify_buh_section(row.account_dt, row.account_kt)
        if section not in OTHER_PNL_SECTIONS:
            continue
        amount_nu = abs(_amount_nu_for_section(section, row.amount_nu_dt, row.amount_nu_kt))
        if amount_nu < 0.01:
            continue
        groups[(row.document, section, round(amount_nu, 2))].append(row)
    return groups


def _lookup_contractor(document: str, doc_contractor: dict[str, str]) -> str:
    if document in doc_contractor:
        return doc_contractor[document]
    document_keys = document_match_keys(document)
    for contractor_document, contractor_value in doc_contractor.items():
        if document_keys & document_match_keys(contractor_document):
            return contractor_value
    return ""


def _amount_nu_for_section(section: str, amount_nu_dt: float, amount_nu_kt: float) -> float:
    """Сумма НУ по правилам Power Query «Свод_нов» (со знаком)."""
    if section == "Себестоимость":
        return -amount_nu_kt if amount_nu_kt else 0.0
    if section in {"Прочие расходы", "Коммерческие расходы", "Управленческие расходы"}:
        return -amount_nu_dt if amount_nu_dt else 0.0
    if section == "Прочие доходы":
        return amount_nu_kt
    return amount_nu_kt


def _amount_buh_for_section(
    section: str,
    row: BuhRow,
    cost_match: CostRow | None,
    *,
    duplicate_cost_key: bool = False,
) -> float:
    """Сумма БУ по правилам Power Query «Свод_нов» (со знаком)."""
    if section == "Себестоимость":
        # Бухрегистр — источник суммы БУ; cost_match даёт только аналитику.
        return -row.amount_buh if row.amount_buh else 0.0
    if section in {"Прочие расходы", "Коммерческие расходы", "Управленческие расходы"}:
        return -row.amount_buh if row.amount_buh else 0.0
    return row.amount_buh if row.amount_buh else 0.0


def _build_cost_lookup(cost_rows: list[CostRow]) -> dict[tuple[str, str], CostRow]:
    lookup: dict[tuple[str, str], CostRow] = {}
    for row in cost_rows:
        nomenclature = row.nomenclature.casefold()
        if not nomenclature:
            continue
        for key in document_match_keys(row.document):
            pair = (key, nomenclature)
            current = lookup.get(pair)
            if current is None or float(row.quantity or 0) > float(current.quantity or 0):
                lookup[pair] = row
    return lookup


def _build_duplicate_cost_buh_keys(exports: ParsedExports) -> frozenset[tuple[str, str]]:
    """Строки бухрегистра с одинаковыми документом и номенклатурой Кт (90.02.1)."""
    counts: dict[tuple[str, str], int] = {}
    for row in exports.buh:
        section = classify_buh_section(row.account_dt, row.account_kt)
        if section != "Себестоимость" or not row.month:
            continue
        nomenclature = row.nomenclature_kt.casefold()
        if not nomenclature:
            continue
        pair = (row.document, nomenclature)
        counts[pair] = counts.get(pair, 0) + 1
    return frozenset(key for key, count in counts.items() if count > 1)


def _is_duplicate_cost_buh_key(duplicate_keys: frozenset[tuple[str, str]], row: BuhRow) -> bool:
    nomenclature = row.nomenclature_kt.casefold()
    if not nomenclature:
        return False
    return (row.document, nomenclature) in duplicate_keys


def _build_cost_quantity_lookup(cost_rows: list[CostRow]) -> dict[tuple[str, str], float]:
    """Макс. «Количество продаж» по ключу (document_key, nomenclature)."""
    lookup: dict[tuple[str, str], float] = {}
    for row in cost_rows:
        nomenclature = row.nomenclature.casefold()
        if not nomenclature:
            continue
        qty = float(row.quantity or 0)
        if qty <= 0:
            continue
        for key in document_match_keys(row.document):
            pair = (key, nomenclature)
            lookup[pair] = max(lookup.get(pair, 0.0), qty)
    return lookup


def _lookup_cost_quantity(
    document: str,
    nomenclature: str,
    qty_lookup: dict[tuple[str, str], float],
) -> float:
    name = (nomenclature or "").casefold()
    if not name or not document:
        return 0.0
    best = 0.0
    for key in document_match_keys(document):
        best = max(best, float(qty_lookup.get((key, name), 0.0)))
    return best


def _lookup_cost_quantity_by_nomenclature(
    nomenclature: str,
    qty_lookup: dict[tuple[str, str], float],
) -> float:
    name = (nomenclature or "").casefold()
    if not name:
        return 0.0
    return max((qty for (_doc, nom), qty in qty_lookup.items() if nom == name), default=0.0)


@dataclass
class CostNuAllocator:
    """Построчное сопоставление выгрузки «Себестоимость НУ» без суммирования в lookup."""

    _rows: list[CostNuRow]
    _pool: dict[tuple[str, str], list[int]]
    _consumed: set[int] = field(default_factory=set)

    @classmethod
    def from_rows(cls, rows: list[CostNuRow]) -> CostNuAllocator:
        pool: dict[tuple[str, str], list[int]] = defaultdict(list)
        for index, row in enumerate(rows):
            nom = nomenclature_key(row.nomenclature)
            if not nom:
                continue
            if float(row.amount_nu or 0) <= 0:
                continue
            for key in document_match_keys(row.document):
                pool[(key, nom)].append(index)
        return cls(_rows=list(rows), _pool=dict(pool))

    def _available_indices(self, document: str, nomenclature: str) -> list[int]:
        name = nomenclature_key(nomenclature)
        if not name or not document:
            return []
        seen: set[int] = set()
        indices: list[int] = []
        for key in document_match_keys(document):
            for index in self._pool.get((key, name), []):
                if index not in self._consumed and index not in seen:
                    seen.add(index)
                    indices.append(index)
        return indices

    def allocate_for_cost_match(
        self,
        *,
        document: str,
        nomenclature: str,
        cost_match: CostRow | None,
        cost_matches: list[CostRow | None],
        amount_buh: float,
    ) -> float:
        lookup_doc = normalize_text(cost_match.document if cost_match and cost_match.document else document)
        nom = normalize_text(
            (cost_match.nomenclature if cost_match and cost_match.nomenclature else nomenclature) or ""
        )
        available = self._available_indices(lookup_doc, nom)
        if not available:
            return 0.0

        active_matches = [match for match in cost_matches if match is not None]
        if cost_match is not None and len(active_matches) > 1:
            sorted_matches = sorted(
                active_matches,
                key=lambda match: (
                    -abs(float(match.amount or 0)),
                    normalize_text(match.document),
                    nomenclature_key(match.nomenclature),
                ),
            )
            try:
                slot = sorted_matches.index(cost_match)
            except ValueError:
                slot = 0
            sorted_indices = sorted(available, key=lambda index: -float(self._rows[index].amount_nu))
            if slot >= len(sorted_indices):
                return 0.0
            chosen = sorted_indices[slot]
        elif len(available) == 1:
            chosen = available[0]
        else:
            hint = abs(float(cost_match.amount if cost_match else amount_buh or 0))
            if hint > 0:
                chosen = min(available, key=lambda index: abs(float(self._rows[index].amount_nu) - hint))
            else:
                chosen = max(available, key=lambda index: float(self._rows[index].amount_nu))

        self._consumed.add(chosen)
        return float(self._rows[chosen].amount_nu)

    def allocate_for_cost_row(self, row: CostRow) -> float:
        amount = self.allocate_for_cost_match(
            document=row.document,
            nomenclature=row.nomenclature,
            cost_match=row,
            cost_matches=[row],
            amount_buh=-abs(float(row.amount or 0)),
        )
        return -amount if amount > 0 else 0.0


def _cost_nu_match_defaults(account: str, calc_article: str) -> tuple[str, str]:
    return (
        normalize_text(account or "20").casefold(),
        normalize_text(calc_article or "Сырье и материалы").casefold(),
    )


def _dedupe_cost_nu_rows(rows: list[CostNuRow]) -> list[CostNuRow]:
    """Исключить точные дубли строк файла «Себестоимость НУ» (включая отрицательные/сторno)."""
    seen: set[tuple] = set()
    deduped: list[CostNuRow] = []
    for row in rows:
        amount = float(row.amount_nu or 0)
        if not row.month or amount == 0:
            continue
        nom = nomenclature_key(row.nomenclature)
        if not nom:
            continue
        acct, article = _cost_nu_match_defaults(row.account, row.calc_article)
        key = (
            period_or_month(row),
            tuple(sorted(document_match_keys(row.document))),
            nom,
            acct,
            article,
            round(amount, 2),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def _build_cost_nu_exact_pool(rows: list[CostNuRow]) -> dict[tuple[str, str, str, str, str], list[int]]:
    """Пул строк НУ по ключу (период, документ, продукция, счёт, статья) для 1:1."""
    pool: dict[tuple[str, str, str, str, str], list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        amount = float(row.amount_nu or 0)
        if amount == 0 or not row.month:
            continue
        nom = nomenclature_key(row.nomenclature)
        if not nom:
            continue
        acct, article = _cost_nu_match_defaults(row.account, row.calc_article)
        for doc_key in document_match_keys(row.document):
            pool[(period_or_month(row), doc_key, nom, acct, article)].append(index)
    return dict(pool)


def _consume_cost_nu_exact(
    pool: dict[tuple[str, str, str, str, str], list[int]],
    rows: list[CostNuRow],
    consumed: set[int],
    *,
    month: str,
    period: str | None = None,
    document: str,
    nomenclature: str,
    account: str,
    calc_article: str,
) -> float | None:
    nom = nomenclature_key(nomenclature)
    match_period = period or month
    if not nom or not document or not match_period:
        return None
    acct, article = _cost_nu_match_defaults(account, calc_article)
    for doc_key in document_match_keys(document):
        key = (match_period, doc_key, nom, acct, article)
        for index in pool.get(key, []):
            if index not in consumed:
                consumed.add(index)
                return float(rows[index].amount_nu or 0)
    return None


def _consume_cost_nu_by_doc_nom(
    pool: dict[tuple[str, str, str, str, str], list[int]],
    rows: list[CostNuRow],
    consumed: set[int],
    *,
    month: str,
    period: str | None = None,
    document: str,
    nomenclature: str,
    amount_hint: float,
) -> float | None:
    """Fallback: период + документ + продукция, выбор строки НУ по близости суммы к БУ."""
    nom = nomenclature_key(nomenclature)
    match_period = period or month
    if not nom or not document or not match_period:
        return None
    candidates: list[int] = []
    for doc_key in document_match_keys(document):
        for key, indices in pool.items():
            if key[0] != match_period or key[1] != doc_key or key[2] != nom:
                continue
            for index in indices:
                if index not in consumed:
                    candidates.append(index)
    if not candidates:
        return None
    candidates = sorted(set(candidates))
    hint = abs(float(amount_hint or 0))
    if hint > 0 and len(candidates) > 1:
        chosen = min(
            candidates,
            key=lambda index: abs(abs(float(rows[index].amount_nu or 0)) - hint),
        )
    else:
        chosen = candidates[0]
    consumed.add(chosen)
    return float(rows[chosen].amount_nu or 0)


def _monthly_deduped_cost_nu_totals(rows: list[CostNuRow]) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    for row in _dedupe_cost_nu_rows(rows):
        if row.month:
            totals[period_or_month(row)] += float(row.amount_nu or 0)
    return dict(totals)


def _monthly_buh_cost_nu_targets(buh_rows: list[BuhRow]) -> dict[str, float]:
    """Эталон: себестoимость НУ из бухрегистра (90.02) по фактическим периодам."""
    totals: dict[str, float] = defaultdict(float)
    for row in buh_rows:
        section = classify_buh_section(row.account_dt, row.account_kt)
        if section != "Себестоимость" or not row.month:
            continue
        totals[period_or_month(row)] += _amount_nu_for_section(section, row.amount_nu_dt, row.amount_nu_kt)
    return {period: abs(value) for period, value in totals.items()}


def _add_signed_nu_to_fact(facts: list[Fact], index: int, raw_nu: float) -> None:
    fact = facts[index]
    facts[index] = replace(fact, amount_nu=float(fact.amount_nu or 0) + _signed_cost_nu_amount(raw_nu))


def _assign_orphan_nu_by_document(
    facts: list[Fact],
    deduped: list[CostNuRow],
    consumed: set[int],
    cost_indices: list[int],
    matched_pairs: list[tuple[int, int]] | None = None,
) -> int:
    """Нераспределённые строки НУ → факты того же документа (суммирование на факт)."""
    assigned = 0
    for nu_index, nu_row in enumerate(deduped):
        if nu_index in consumed or not nu_row.month:
            continue
        doc_keys = document_match_keys(nu_row.document)
        fact_candidates = [
            index
            for index in cost_indices
            if _same_period(facts[index], nu_row)
            and document_match_keys(facts[index].document) & doc_keys
        ]
        if not fact_candidates:
            continue
        nu_nom = nomenclature_key(nu_row.nomenclature)
        nu_acct, nu_article = _cost_nu_match_defaults(nu_row.account, nu_row.calc_article)
        best_index = fact_candidates[0]
        best_score = (-1, -1.0)
        for index in fact_candidates:
            fact = facts[index]
            fact_nom = nomenclature_key(fact.nomenclature)
            fact_acct, fact_article = _cost_nu_match_defaults(fact.cost_account, fact.expense_article)
            nom_match = int(fact_nom == nu_nom)
            article_match = int(fact_article == nu_article)
            acct_match = int(fact_acct == nu_acct or fact_acct in {"20", "25"} and nu_acct == "20")
            score = (nom_match + article_match + acct_match, abs(float(fact.amount_buh or 0)))
            if score > best_score:
                best_score = score
                best_index = index
        # Внутри одного документа совпадение номенклатуры уже однозначно;
        # пустые счёт/статья в buh не должны оставлять строку NU сиротой.
        if best_score[0] < 1 and len(fact_candidates) != 1:
            continue
        _add_signed_nu_to_fact(facts, best_index, float(nu_row.amount_nu or 0))
        consumed.add(nu_index)
        if matched_pairs is not None:
            matched_pairs.append((nu_index, best_index))
        assigned += 1
    return assigned


def _reconcile_cost_nu_monthly_totals(
    facts: list[Fact],
    deduped: list[CostNuRow],
    cost_indices: list[int],
) -> dict[str, float]:
    """Добить сумму НУ по документам до файла «Себестoимость НУ» (только где есть факты БУ)."""
    nu_by_doc_month: dict[tuple[str, frozenset[str]], float] = defaultdict(float)
    for row in deduped:
        if not row.month:
            continue
        amount = float(row.amount_nu or 0)
        if amount == 0:
            continue
        doc_keys = document_match_keys(row.document)
        if not doc_keys:
            continue
        nu_by_doc_month[(period_or_month(row), doc_keys)] += amount

    facts_by_doc_month: dict[tuple[str, frozenset[str]], list[int]] = defaultdict(list)
    for index in cost_indices:
        fact = facts[index]
        if not fact.month or not fact.document:
            continue
        doc_keys = document_match_keys(fact.document)
        if not doc_keys:
            continue
        facts_by_doc_month[(period_or_month(fact), doc_keys)].append(index)

    adjustments: dict[str, float] = defaultdict(float)
    for group, indices in facts_by_doc_month.items():
        month, _doc_keys = group
        file_total = nu_by_doc_month.get(group, 0.0)
        if abs(file_total) < 0.01:
            continue
        unique_indices = sorted(set(indices))
        bi_total = sum(-float(facts[index].amount_nu or 0) for index in unique_indices)
        gap = float(file_total) - bi_total
        if abs(gap) < 0.01:
            continue
        weights = [abs(float(facts[index].amount_buh or 0)) for index in unique_indices]
        weight_sum = sum(weights)
        if weight_sum <= 0:
            weights = [1.0] * len(unique_indices)
            weight_sum = float(len(unique_indices))
        assigned = 0.0
        for pos, index in enumerate(unique_indices):
            if pos == len(unique_indices) - 1:
                share = gap - assigned
            else:
                share = gap * (weights[pos] / weight_sum)
                assigned += share
            fact = facts[index]
            facts[index] = replace(fact, amount_nu=float(fact.amount_nu or 0) - share)
        adjustments[month] += gap
    return dict(adjustments)


def _reconcile_cost_nu_to_buh_register(
    facts: list[Fact],
    cost_indices: list[int],
    buh_targets: dict[str, float],
) -> dict[str, float]:
    """Финальная сверка с бухрегистром 90.02 — только по фактам, где NU уже назначен."""
    adjustments: dict[str, float] = defaultdict(float)
    for period, target in buh_targets.items():
        indices = [index for index in cost_indices if period_or_month(facts[index]) == period]
        if not indices:
            continue
        bi_total = sum(-float(facts[index].amount_nu or 0) for index in indices)
        gap = float(target) - bi_total
        if abs(gap) < 0.01:
            continue
        weighted = [
            index
            for index in indices
            if abs(float(facts[index].amount_nu or 0)) >= 0.01
        ]
        if not weighted:
            continue
        weights = [abs(float(facts[index].amount_buh or 0)) for index in weighted]
        weight_sum = sum(weights)
        if weight_sum <= 0:
            weights = [abs(float(facts[index].amount_nu or 0)) for index in weighted]
            weight_sum = sum(weights)
        if weight_sum <= 0:
            weights = [1.0] * len(weighted)
            weight_sum = float(len(weighted))
        assigned = 0.0
        for pos, index in enumerate(weighted):
            if pos == len(weighted) - 1:
                share = gap - assigned
            else:
                share = gap * (weights[pos] / weight_sum)
                assigned += share
            fact = facts[index]
            facts[index] = replace(fact, amount_nu=float(fact.amount_nu or 0) - share)
        adjustments[period] = gap
    return dict(adjustments)


def _append_cost_nu_register_residuals(
    facts: list[Fact],
    cost_indices: list[int],
    buh_targets: dict[str, float],
) -> dict[str, float]:
    """Сверка 90.02 отдельной строкой, без изменения matched-фактов."""
    residuals: dict[str, float] = {}
    for period, target in buh_targets.items():
        matching_indices = [
            index for index in cost_indices if period_or_month(facts[index]) == period
        ]
        current = sum(
            -float(facts[index].amount_nu or 0)
            for index in matching_indices
        )
        gap = float(target) - current
        if abs(gap) < 0.01:
            continue
        facts.append(
            Fact(
                kpi_l1="Себестоимость",
                month=(
                    facts[matching_indices[0]].month
                    if matching_indices
                    else next(
                        (
                            name
                            for number, name in MONTH_NAMES.items()
                            if period.endswith(f"-{number:02d}")
                        ),
                        period,
                    )
                    if len(period) == 7 and period[4] == "-" and period[:4].isdigit()
                    else period
                ),
                amount_buh=0.0,
                amount_nu=-gap,
                direction="Без направления",
                project_group="Без группы",
                project="Без проекта",
                nomenclature="Сверка НУ с бухрегистром 90.02",
                cost_section="Корректировка НУ",
                expense_article="Сверка НУ с бухрегистром 90.02",
                tax_type="Общие условия налогообложения",
                period=(
                    period
                    if len(period) == 7 and period[4] == "-" and period[:4].isdigit()
                    else None
                ),
            )
        )
        cost_indices.append(len(facts) - 1)
        residuals[period] = gap
    return residuals


def _signed_cost_nu_amount(raw_amount: float) -> float:
    """Сумма НУ на факте себестoимости — отрицательная для расхода, как amount_buh."""
    return -float(raw_amount or 0)


def _apply_cost_nu_to_buh_facts(
    facts: list[Fact],
    cost_nu_rows: list[CostNuRow],
    buh_rows: list[BuhRow] | None = None,
) -> dict[str, int | float | dict[str, float]]:
    """НУ: 1:1 → fallback → orphan по документу → файл НУ → бухрегистр 90.02."""
    deduped = _dedupe_cost_nu_rows(cost_nu_rows)
    pool = _build_cost_nu_exact_pool(deduped)
    consumed: set[int] = set()
    cost_indices = [index for index, fact in enumerate(facts) if fact.kpi_l1 == "Себестоимость"]
    original_cost_indices = list(cost_indices)
    matched_pairs: list[tuple[int, int]] = []
    stats: dict[str, int | float | dict[str, float]] = {
        "matched_exact": 0,
        "matched_fallback": 0,
        "matched_orphan_doc": 0,
        "unmatched": 0,
        "orphan_nu": 0,
        "monthly_adjustments": {},
        "buh_register_adjustments": {},
    }

    for index in cost_indices:
        facts[index] = replace(facts[index], amount_nu=0.0)

    for index in cost_indices:
        fact = facts[index]
        consumed_before = set(consumed)
        raw_nu = _consume_cost_nu_exact(
            pool,
            deduped,
            consumed,
            month=fact.month,
            period=fact.period,
            document=fact.document,
            nomenclature=fact.nomenclature,
            account=fact.cost_account,
            calc_article=fact.expense_article,
        )
        if raw_nu is None and fact.cost_account.strip() == "25":
            raw_nu = _consume_cost_nu_exact(
                pool,
                deduped,
                consumed,
                month=fact.month,
                period=fact.period,
                document=fact.document,
                nomenclature=fact.nomenclature,
                account="20",
                calc_article=fact.expense_article,
            )
        if raw_nu is not None:
            facts[index] = replace(fact, amount_nu=_signed_cost_nu_amount(raw_nu))
            matched_row_indices = consumed - consumed_before
            if len(matched_row_indices) == 1:
                matched_pairs.append((matched_row_indices.pop(), index))
            stats["matched_exact"] += 1

    # Fallback запускается только после всех exact-сопоставлений, чтобы не
    # забрать строку НУ, предназначенную следующему точному факту.
    for index in cost_indices:
        fact = facts[index]
        if abs(float(fact.amount_nu or 0)) >= 0.01:
            continue
        consumed_before = set(consumed)
        raw_nu = _consume_cost_nu_by_doc_nom(
            pool,
            deduped,
            consumed,
            month=fact.month,
            period=fact.period,
            document=fact.document,
            nomenclature=fact.nomenclature,
            amount_hint=fact.amount_buh,
        )
        if raw_nu is not None:
            facts[index] = replace(fact, amount_nu=_signed_cost_nu_amount(raw_nu))
            matched_row_indices = consumed - consumed_before
            if len(matched_row_indices) == 1:
                matched_pairs.append((matched_row_indices.pop(), index))
            stats["matched_fallback"] += 1

    stats["matched_orphan_doc"] = _assign_orphan_nu_by_document(
        facts, deduped, consumed, cost_indices, matched_pairs
    )
    # Расхождения с файлом не размазываются по matched-фактам.
    stats["monthly_adjustments"] = {}
    if buh_rows:
        stats["buh_register_adjustments"] = _append_cost_nu_register_residuals(
            facts,
            cost_indices,
            _monthly_buh_cost_nu_targets(buh_rows),
        )

    for index in cost_indices:
        if abs(float(facts[index].amount_nu or 0)) < 0.01:
            stats["unmatched"] += 1

    stats["orphan_nu"] = len(deduped) - len(consumed)
    unallocated_by_month: dict[str, float] = defaultdict(float)
    for row_index, row in enumerate(deduped):
        if row_index not in consumed and row.month:
            unallocated_by_month[period_or_month(row)] += float(row.amount_nu or 0)
    stats["unallocated_by_month"] = dict(unallocated_by_month)
    stats["matched"] = (
        int(stats["matched_exact"])
        + int(stats["matched_fallback"])
        + int(stats["matched_orphan_doc"])
    )

    # Вариант А: БУ остаётся на канонических фактах 90.02, а НУ хранится
    # отдельными строками в исходном разрезе файла «Себестоимость НУ».
    # Аналитика направления/проекта наследуется от сопоставленного факта БУ.
    for index in original_cost_indices:
        facts[index] = replace(facts[index], amount_nu=0.0)
    for row_index, fact_index in matched_pairs:
        row = deduped[row_index]
        matched_fact = facts[fact_index]
        facts.append(
            Fact(
                kpi_l1="Себестоимость",
                month=row.month or matched_fact.month,
                amount_buh=0.0,
                amount_nu=_signed_cost_nu_amount(float(row.amount_nu or 0)),
                direction=matched_fact.direction,
                project_group=matched_fact.project_group,
                project=matched_fact.project,
                contract=matched_fact.contract,
                nomenclature=row.nomenclature or matched_fact.nomenclature,
                cost_section=classify_cost_section_pq(row.calc_article, row.account),
                cost_account=row.account,
                expense_article=row.calc_article,
                document=row.document or matched_fact.document,
                tax_type=matched_fact.tax_type,
                contractor=matched_fact.contractor,
                quantity=float(row.quantity or matched_fact.quantity or 0),
                period=row.period or matched_fact.period,
            )
        )
    return stats


def _build_cost_nu_amount_lookup(cost_nu_rows: list[CostNuRow]) -> dict[tuple[str, str], float]:
    lookup: dict[tuple[str, str], float] = {}
    for row in cost_nu_rows:
        nomenclature = nomenclature_key(row.nomenclature)
        if not nomenclature:
            continue
        amount = float(row.amount_nu or 0)
        if amount <= 0:
            continue
        for key in document_match_keys(row.document):
            pair = (key, nomenclature)
            lookup[pair] = lookup.get(pair, 0.0) + amount
    return lookup


def _lookup_cost_nu_amount(
    document: str,
    nomenclature: str,
    lookup: dict[tuple[str, str], float],
) -> float:
    name = nomenclature_key(nomenclature)
    if not name or not document:
        return 0.0
    best = 0.0
    for key in document_match_keys(document):
        best = max(best, float(lookup.get((key, name), 0.0)))
    if best > 0:
        return best
    return 0.0


def _resolve_cost_nu_via_cost_rows(
    *,
    document: str,
    nomenclature: str,
    cost_rows: list[CostRow],
    cost_nu_lookup: dict[tuple[str, str], float],
) -> float:
    """Подбор суммы только из файла НУ через строки себестоимости (документ + номенклатура)."""
    buh_keys = document_match_keys(document)
    buh_nom = nomenclature_key(nomenclature)
    seen: set[tuple[str, str]] = set()
    candidates: list[float] = []
    for cost_row in cost_rows:
        if not (document_match_keys(cost_row.document) & buh_keys):
            continue
        if buh_nom and nomenclature_key(cost_row.nomenclature) != buh_nom:
            continue
        pair = (normalize_text(cost_row.document), nomenclature_key(cost_row.nomenclature))
        if pair in seen:
            continue
        seen.add(pair)
        nu_amount = _lookup_cost_nu_amount(cost_row.document, cost_row.nomenclature, cost_nu_lookup)
        if nu_amount > 0:
            candidates.append(nu_amount)
    if not candidates:
        return 0.0
    if len(candidates) == 1:
        return candidates[0]
    if buh_nom:
        return sum(candidates)
    return 0.0


def resolve_cost_fact_amount_nu(
    *,
    amount_buh: float,
    document: str,
    nomenclature: str,
    cost_match: CostRow | None,
    cost_matches: list[CostRow | None],
    cost_nu_allocator: CostNuAllocator | None = None,
    cost_nu_lookup: dict[tuple[str, str], float] | None = None,
    cost_rows: list[CostRow] | None = None,
) -> float:
    """Факт НУ по себестоимости — только из выгрузки «Себестоимость НУ»."""
    if cost_nu_allocator is None and not cost_nu_lookup:
        return 0.0

    if cost_nu_allocator is not None:
        amount = cost_nu_allocator.allocate_for_cost_match(
            document=document,
            nomenclature=nomenclature,
            cost_match=cost_match,
            cost_matches=cost_matches,
            amount_buh=amount_buh,
        )
        if amount <= 0 and cost_rows:
            buh_keys = document_match_keys(document)
            buh_nom = nomenclature_key(nomenclature)
            seen_pairs: set[tuple[str, str]] = set()
            for cost_row in cost_rows:
                if not (document_match_keys(cost_row.document) & buh_keys):
                    continue
                if buh_nom and nomenclature_key(cost_row.nomenclature) != buh_nom:
                    continue
                pair = (normalize_text(cost_row.document), nomenclature_key(cost_row.nomenclature))
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                amount = cost_nu_allocator.allocate_for_cost_match(
                    document=document,
                    nomenclature=nomenclature,
                    cost_match=cost_row,
                    cost_matches=[cost_row],
                    amount_buh=amount_buh,
                )
                if amount > 0:
                    break
        return -amount if amount > 0 else 0.0

    lookup_doc = normalize_text(cost_match.document if cost_match and cost_match.document else document)
    nom = normalize_text(
        (cost_match.nomenclature if cost_match and cost_match.nomenclature else nomenclature) or ""
    )
    total_nu = _lookup_cost_nu_amount(lookup_doc, nom, cost_nu_lookup or {})
    if total_nu <= 0 and cost_rows:
        total_nu = _resolve_cost_nu_via_cost_rows(
            document=document,
            nomenclature=nomenclature,
            cost_rows=cost_rows,
            cost_nu_lookup=cost_nu_lookup or {},
        )
    if total_nu <= 0:
        return 0.0
    active_matches = [match for match in cost_matches if match is not None]
    if cost_match is not None and len(active_matches) > 1:
        total_buh = sum(abs(float(match.amount or 0)) for match in active_matches)
        if total_buh > 0:
            share = abs(float(cost_match.amount or 0)) / total_buh
            return -total_nu * share
    return -total_nu


def _cost_nu_amount_for_cost_row(
    row: CostRow,
    cost_nu_allocator: CostNuAllocator | None = None,
    cost_nu_lookup: dict[tuple[str, str], float] | None = None,
) -> float:
    if cost_nu_allocator is not None:
        return cost_nu_allocator.allocate_for_cost_row(row)
    if not cost_nu_lookup:
        return 0.0
    total_nu = _lookup_cost_nu_amount(row.document, row.nomenclature, cost_nu_lookup)
    return -total_nu if total_nu > 0 else 0.0


def resolve_quantity_from_cost(
    *,
    document: str,
    nomenclature: str,
    cost_match: CostRow | None = None,
    qty_lookup: dict[tuple[str, str], float] | None = None,
    cost_rows: list[CostRow] | None = None,
) -> float:
    """Количество продаж из cost: сначала из join-строки, иначе lookup по документу+номенклатуре."""
    if cost_match is not None:
        matched = float(cost_match.quantity or 0)
        if matched > 0:
            return matched
    lookup = qty_lookup
    if lookup is None and cost_rows is not None:
        lookup = _build_cost_quantity_lookup(cost_rows)
    if not lookup:
        return 0.0
    by_document = _lookup_cost_quantity(document, nomenclature, lookup)
    if by_document > 0:
        return by_document
    return _lookup_cost_quantity_by_nomenclature(nomenclature, lookup)


def _lookup_cost_row(
    document: str,
    nomenclature_kt: str,
    lookup: dict[tuple[str, str], CostRow],
) -> CostRow | None:
    nomenclature = nomenclature_kt.casefold()
    if not nomenclature:
        return None
    for key in document_match_keys(document):
        match = lookup.get((key, nomenclature))
        if match is not None:
            return match
    return None


def _is_meaningful_analytic(value: str) -> bool:
    return value.casefold() not in {"", "без направления", "без группы", "без проекта"}


def _coalesce_analytics(
    *,
    cost_match: CostRow | None,
    rev_match: RealizationRow | None,
    fallback: ProjectMeta,
) -> ProjectMeta:
    def pick(cost_value: str, rev_value: str, default: str) -> str:
        if _is_meaningful_analytic(cost_value):
            return cost_value
        if _is_meaningful_analytic(rev_value):
            return rev_value
        return default

    cost_direction = cost_match.direction if cost_match else ""
    rev_direction = rev_match.direction if rev_match else ""
    cost_group = cost_match.project_group if cost_match else ""
    rev_group = rev_match.project_group if rev_match else ""
    cost_project = cost_match.project if cost_match else ""
    rev_project = rev_match.project if rev_match else ""

    return ProjectMeta(
        direction=pick(cost_direction, rev_direction, fallback.direction),
        project_group=pick(cost_group, rev_group, fallback.project_group),
        project=pick(cost_project, rev_project, fallback.project),
    )


def _append_fact(
    facts: list[Fact],
    *,
    kpi_l1: str,
    month: str | None,
    period: str | None = None,
    amount_buh: float,
    amount_nu: float | None = None,
    direction: str = "",
    project_group: str = "",
    project: str = "",
    contract: str = "",
    nomenclature: str = "",
    cost_section: str = "",
    cost_account: str = "",
    expense_article: str = "",
    document: str = "",
    tax_type: str = "",
    contractor: str = "",
    quantity: float = 0.0,
) -> None:
    if not month:
        return
    effective_nu = amount_nu if amount_nu is not None else amount_buh
    if amount_buh == 0 and effective_nu == 0:
        return
    facts.append(
        Fact(
            kpi_l1=kpi_l1,
            month=month,
            amount_buh=amount_buh,
            amount_nu=amount_nu if amount_nu is not None else amount_buh,
            direction=direction,
            project_group=project_group,
            project=project,
            contract=contract,
            nomenclature=nomenclature,
            cost_section=cost_section,
            cost_account=cost_account,
            expense_article=expense_article,
            document=document,
            tax_type=tax_type or "Общие условия налогообложения",
            contractor=contractor,
            quantity=float(quantity or 0),
            period=period,
        )
    )


def _append_other_pnl_fact(
    facts: list[Fact],
    *,
    kpi_l1: str,
    month: str | None,
    period: str | None = None,
    amount_buh: float,
    amount_nu: float,
    buh_tax_type: str,
    nu_tax_type: str,
    direction: str = "",
    project_group: str = "",
    project: str = "",
    contract: str = "",
    nomenclature: str = "",
    cost_section: str = "",
    expense_article: str = "",
    contractor: str = "",
    quantity: float = 0.0,
) -> None:
    """Прочие доходы/расходы: БУ и НУ могут попадать в разные налоговые корзины."""
    shared = {
        "kpi_l1": kpi_l1,
        "month": month,
        "period": period,
        "direction": direction,
        "project_group": project_group,
        "project": project,
        "contract": contract,
        "nomenclature": nomenclature,
        "cost_section": cost_section,
        "expense_article": expense_article,
        "contractor": contractor,
        "quantity": quantity,
    }
    if tax_bucket(buh_tax_type) != tax_bucket(nu_tax_type):
        if amount_buh:
            _append_fact(
                facts,
                amount_buh=amount_buh,
                amount_nu=0.0,
                tax_type=buh_tax_type,
                **shared,
            )
        if amount_nu:
            _append_fact(
                facts,
                amount_buh=0.0,
                amount_nu=amount_nu,
                tax_type=nu_tax_type,
                **shared,
            )
        return
    _append_fact(
        facts,
        amount_buh=amount_buh,
        amount_nu=amount_nu,
        tax_type=buh_tax_type,
        **shared,
    )


def _append_file_fallback_facts(
    facts: list[Fact],
    exports: ParsedExports,
    *,
    doc_tax: dict[str, str],
    doc_contract: dict[str, str],
    doc_contractor: dict[str, str],
    project_by_document: dict[str, ProjectMeta],
    project_key_index: dict[str, str],
    project_meta_by_key: dict[str, ProjectMeta],
    include_revenue: bool,
    include_cost: bool,
) -> None:
    cost_qty_lookup = _build_cost_quantity_lookup(exports.cost)
    if include_revenue and exports.realization:
        for row in exports.realization:
            project = lookup_project(
                row.document,
                project_by_document,
                project_key_index,
                meta_by_key=project_meta_by_key,
            )
            _append_fact(
                facts,
                kpi_l1="Выручка",
                month=row.month,
                period=row.period,
                amount_buh=row.revenue,
                amount_nu=row.revenue,
                direction=project.direction,
                project_group=project.project_group,
                project=project.project,
                contract=_lookup_contract(row.document, doc_contract),
                nomenclature=row.nomenclature,
                tax_type=doc_tax.get(row.document, "Общие условия налогообложения"),
                contractor=_lookup_contractor(row.document, doc_contractor),
                quantity=(
                    float(row.quantity or 0)
                    if row.quantity is not None
                    else resolve_quantity_from_cost(
                        document=row.document,
                        nomenclature=row.nomenclature,
                        qty_lookup=cost_qty_lookup,
                    )
                ),
            )

    if include_cost and exports.cost:
        for row in exports.cost:
            project = lookup_project(
                row.document,
                project_by_document,
                project_key_index,
                meta_by_key=project_meta_by_key,
            )
            _append_fact(
                facts,
                kpi_l1="Себестоимость",
                month=row.month,
                period=row.period,
                amount_buh=-abs(row.amount),
                amount_nu=0.0,
                direction=project.direction,
                project_group=project.project_group,
                project=project.project,
                contract=_lookup_contract(row.document, doc_contract),
                nomenclature=row.nomenclature,
                document=row.document,
                cost_section=row.cost_section,
                cost_account=row.account,
                expense_article=row.calc_article,
                tax_type=doc_tax.get(row.document, "Общие условия налогообложения"),
                contractor=_lookup_contractor(row.document, doc_contractor),
                quantity=row.quantity,
            )


def build_facts(exports: ParsedExports) -> PipelineResult:
    facts: list[Fact] = []
    warnings: list[str] = []

    doc_tax: dict[str, str] = {}
    doc_contract: dict[str, str] = {}
    doc_contractor: dict[str, str] = {}
    for row in exports.buh:
        _merge_doc_tax(doc_tax, row)
        if row.contract and row.document not in doc_contract:
            doc_contract[row.document] = row.contract
        if row.contractor and row.document not in doc_contractor:
            doc_contractor[row.document] = row.contractor

    project_by_document, project_key_index, project_meta_by_key = build_project_index(exports)
    cost_lookup = _build_cost_lookup(exports.cost)
    cost_qty_lookup = _build_cost_quantity_lookup(exports.cost)
    duplicate_cost_buh_keys = _build_duplicate_cost_buh_keys(exports)
    other_pnl_storno_groups = _build_other_pnl_storno_groups(exports)
    other_pnl_nu_storno_groups = _build_other_pnl_nu_storno_groups(exports)
    other_pnl_nu_mismatch_docs = _other_pnl_nu_mismatch_documents(exports)
    other_pnl_section_has_nu = _build_other_pnl_section_has_nu(exports)
    realization_index = build_realization_index(exports.realization, doc_contract)

    if exports.realization:
        missing_analytics = sum(
            1
            for row in exports.realization
            if row.direction == "Без направления" and row.project_group == "Без группы"
        )
        if missing_analytics and missing_analytics == len(exports.realization):
            warnings.append(
                "В файле реализации не найдены колонки «Проекты.Направление», "
                "«Проекты.Группа проектов», «Проекты.Проект» — проверьте шапку выгрузки."
            )
        elif missing_analytics > len(exports.realization) * 0.5:
            warnings.append(
                "Больше половины строк реализации без направления/группы — "
                "возможно, не совпадает ключ «Документ» между выгрузками."
            )
    else:
        warnings.append(
            "Файл реализации не загружен — аналитика проектов для выручки будет взята только из бухрегистра."
        )

    if not exports.cost:
        warnings.append("Файл себестоимости не загружен — себестоимость будет взята из бухрегистра.")
    elif not exports.cost_nu:
        warnings.append(
            "Файл «Себестоимость НУ» не загружен — факт НУ по себестоимости будет нулевым."
        )

    saw_revenue = False
    saw_cost = False

    for row in exports.buh:
        section = classify_buh_section(row.account_dt, row.account_kt)
        if not section or not row.month:
            continue
        if _skip_other_expense_inventory_non_deductible(row, section):
            continue

        cost_match = None
        if section == "Себестоимость" and exports.cost:
            cost_match = _lookup_cost_row(row.document, row.nomenclature_kt, cost_lookup)

        lookup_document = (
            cost_match.document
            if cost_match and cost_match.document
            else row.document
        )

        amount_buh = _amount_buh_for_section(
            section,
            row,
            cost_match,
            duplicate_cost_key=_is_duplicate_cost_buh_key(duplicate_cost_buh_keys, row),
        )
        if section == "Себестоимость":
            amount_nu = 0.0
        else:
            amount_nu = _amount_nu_for_section(section, row.amount_nu_dt, row.amount_nu_kt)

        rev_match = None
        if exports.realization and section in {"Выручка", "Себестоимость"}:
            buh_contract = analytics_value(row.contract, default="") or _lookup_contract(row.document, doc_contract)
            if section == "Выручка":
                rev_match = resolve_revenue_analytics_match(
                    buh_row=row,
                    buh_contract=buh_contract,
                    amount_buh=amount_buh,
                    amount_nu=amount_nu,
                    index=realization_index,
                    realization_rows=exports.realization,
                )
            else:
                rev_match = resolve_realization_match(
                    buh_row=row,
                    cost_match=cost_match,
                    buh_contract=buh_contract,
                    index=realization_index,
                    prefer_cost_chain=True,
                )

        fallback_project = lookup_project(
            row.document,
            project_by_document,
            project_key_index,
            meta_by_key=project_meta_by_key,
            fallback_project=row.project,
        )
        analytics = _coalesce_analytics(
            cost_match=cost_match,
            rev_match=rev_match,
            fallback=fallback_project,
        )

        nomenclature = row.nomenclature_kt
        if section == "Выручка" and is_buh_revenue_activity_nomenclature(nomenclature):
            nomenclature = ""
        if section != "Выручка" and cost_match and cost_match.nomenclature:
            nomenclature = cost_match.nomenclature
        elif not nomenclature and rev_match and rev_match.nomenclature:
            nomenclature = rev_match.nomenclature

        contract = analytics_value(row.contract, default="") or _lookup_contract(row.document, doc_contract)
        if cost_match and cost_match.contract:
            contract = cost_match.contract or contract
        contractor = row.contractor or _lookup_contractor(row.document, doc_contractor)

        exact_revenue_operation = None
        if section == "Выручка" and exports.realization:
            revenue_realization = lookup_realization_for_revenue_amount(
                document=row.document,
                amount_buh=amount_buh,
                amount_nu=amount_nu,
                rows=exports.realization,
            )
            if revenue_realization is not None and revenue_realization.nomenclature:
                nomenclature = revenue_realization.nomenclature
            exact_revenue_operation = lookup_exact_realization_operation(
                document=row.document,
                nomenclature=nomenclature,
                index=realization_index,
            )
            if exact_revenue_operation is None and revenue_realization is not None:
                exact_revenue_operation = revenue_realization
            if exact_revenue_operation is not None and exact_revenue_operation.nomenclature:
                nomenclature = exact_revenue_operation.nomenclature
            if exact_revenue_operation is not None:
                analytics = _coalesce_analytics(
                    cost_match=cost_match,
                    rev_match=exact_revenue_operation,
                    fallback=fallback_project,
                )
        if exact_revenue_operation is not None and exact_revenue_operation.quantity is not None:
            quantity = float(exact_revenue_operation.quantity or 0)
        else:
            quantity = resolve_quantity_from_cost(
                document=row.document,
                nomenclature=nomenclature,
                cost_match=cost_match,
                qty_lookup=cost_qty_lookup,
            )
            if quantity <= 0 and cost_match is not None and cost_match.document:
                quantity = resolve_quantity_from_cost(
                    document=cost_match.document,
                    nomenclature=nomenclature or cost_match.nomenclature,
                    cost_match=cost_match,
                    qty_lookup=cost_qty_lookup,
                )

        resolved_tax_type = _resolve_row_tax_type(
            section,
            row,
            doc_tax,
            other_pnl_storno_groups=other_pnl_storno_groups,
            other_pnl_nu_mismatch_docs=other_pnl_nu_mismatch_docs,
            other_pnl_section_has_nu=other_pnl_section_has_nu,
        )

        fact_kwargs = {
            "kpi_l1": section,
            "month": row.month,
            "period": row.period,
            "amount_buh": amount_buh,
            "amount_nu": amount_nu,
            "direction": analytics.direction,
            "project_group": analytics.project_group,
            "project": analytics.project,
            "contract": contract,
            "nomenclature": nomenclature,
            "cost_section": cost_match.cost_section if cost_match else "",
            "cost_account": normalize_text(getattr(cost_match, "account", "") or "") if cost_match else "",
            "expense_article": (
                cost_match.calc_article
                if cost_match and section == "Себестоимость" and cost_match.calc_article
                else row.expense_article
            ),
            "document": lookup_document,
            "contractor": contractor,
            "quantity": quantity,
        }
        if section in OTHER_PNL_SECTIONS:
            resolved_nu_tax_type = _resolve_other_pnl_nu_tax_type(
                row,
                exports=exports,
                doc_tax=doc_tax,
                buh_storno_groups=other_pnl_storno_groups,
                nu_storno_groups=other_pnl_nu_storno_groups,
                nu_mismatch_docs=other_pnl_nu_mismatch_docs,
                section_has_nu=other_pnl_section_has_nu,
            )
            pnl_kwargs = {
                key: value
                for key, value in fact_kwargs.items()
                if key not in ("cost_section", "cost_account", "document")
            }
            _append_other_pnl_fact(
                facts,
                buh_tax_type=resolved_tax_type,
                nu_tax_type=resolved_nu_tax_type,
                **pnl_kwargs,
            )
        else:
            _append_fact(
                facts,
                tax_type=resolved_tax_type,
                **fact_kwargs,
            )

        if section == "Выручка":
            saw_revenue = True
        if section == "Себестоимость":
            saw_cost = True

    _append_file_fallback_facts(
        facts,
        exports,
        doc_tax=doc_tax,
        doc_contract=doc_contract,
        doc_contractor=doc_contractor,
        project_by_document=project_by_document,
        project_key_index=project_key_index,
        project_meta_by_key=project_meta_by_key,
        include_revenue=not saw_revenue,
        include_cost=not saw_cost,
    )

    if exports.cost_nu:
        _apply_cost_nu_to_buh_facts(facts, exports.cost_nu, exports.buh)

    ordered_facts = sorted(facts, key=lambda fact: period_sort_key(fact.period, fallback=fact.month))
    months = list(dict.fromkeys(fact.month for fact in ordered_facts))
    if not facts:
        warnings.append("После обработки выгрузок не найдено строк с суммами по месяцам.")

    return PipelineResult(
        facts=facts,
        months=months,
        warnings=warnings,
        realization_rows=list(exports.realization),
    )


def run_pipeline(paths: dict[str, Path]) -> PipelineResult:
    exports = parse_exports(paths)
    return build_facts(exports)
