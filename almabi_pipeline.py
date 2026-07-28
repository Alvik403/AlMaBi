from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from almabi_excel_utils import MONTH_NAMES, analytics_value, document_match_keys, tax_bucket
from almabi_export_parsers import (
    BuhRow,
    CostRow,
    ParsedExports,
    RealizationRow,
    classify_buh_section,
    parse_exports,
)
from almabi_project_index import ProjectMeta, build_project_index, lookup_project
from almabi_realization_lookup import build_realization_index, resolve_realization_match

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
    expense_article: str = ""
    tax_type: str = ""
    contractor: str = ""
    quantity: float = 0.0


@dataclass
class PipelineResult:
    facts: list[Fact] = field(default_factory=list)
    months: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


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
            keys.add((row.document, row.month, section))
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

    if section_has_nu is not None and (row.document, row.month, section) not in section_has_nu:
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
        and (row.document, row.month, "Прочие доходы") not in section_has_nu
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
        and (row.document, row.month, "Прочие доходы") not in section_has_nu
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
        if candidate.document != row.document or candidate.month != row.month:
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
        if cost_match is not None:
            cost_amount = abs(cost_match.amount or 0)
            buh_amount = abs(row.amount_buh or 0)
            if duplicate_cost_key and buh_amount and cost_amount < buh_amount:
                return -(buh_amount + cost_amount)
            if cost_match.amount:
                return -cost_match.amount
            return 0.0
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
    return _lookup_cost_quantity(document, nomenclature, lookup)


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
    amount_buh: float,
    amount_nu: float | None = None,
    direction: str = "",
    project_group: str = "",
    project: str = "",
    contract: str = "",
    nomenclature: str = "",
    cost_section: str = "",
    expense_article: str = "",
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
            expense_article=expense_article,
            tax_type=tax_type or "Общие условия налогообложения",
            contractor=contractor,
            quantity=float(quantity or 0),
        )
    )


def _append_other_pnl_fact(
    facts: list[Fact],
    *,
    kpi_l1: str,
    month: str | None,
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
                amount_buh=row.revenue,
                amount_nu=row.revenue,
                direction=project.direction,
                project_group=project.project_group,
                project=project.project,
                contract=_lookup_contract(row.document, doc_contract),
                nomenclature=row.nomenclature,
                tax_type=doc_tax.get(row.document, "Общие условия налогообложения"),
                contractor=_lookup_contractor(row.document, doc_contractor),
                quantity=resolve_quantity_from_cost(
                    document=row.document,
                    nomenclature=row.nomenclature,
                    qty_lookup=cost_qty_lookup,
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
                amount_buh=-abs(row.amount),
                amount_nu=-abs(row.amount),
                direction=project.direction,
                project_group=project.project_group,
                project=project.project,
                contract=_lookup_contract(row.document, doc_contract),
                nomenclature=row.nomenclature,
                cost_section=row.cost_section,
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

        rev_match = None
        if exports.realization and section in {"Выручка", "Себестоимость"}:
            buh_contract = analytics_value(row.contract, default="") or _lookup_contract(row.document, doc_contract)
            rev_match = resolve_realization_match(
                buh_row=row,
                cost_match=cost_match,
                buh_contract=buh_contract,
                index=realization_index,
                prefer_cost_chain=section == "Себестоимость",
            )

        amount_buh = _amount_buh_for_section(
            section,
            row,
            cost_match,
            duplicate_cost_key=_is_duplicate_cost_buh_key(duplicate_cost_buh_keys, row),
        )
        amount_nu = _amount_nu_for_section(section, row.amount_nu_dt, row.amount_nu_kt)

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
        if cost_match and cost_match.nomenclature:
            nomenclature = cost_match.nomenclature
        elif rev_match and rev_match.nomenclature:
            nomenclature = rev_match.nomenclature

        contract = analytics_value(row.contract, default="") or _lookup_contract(row.document, doc_contract)
        if cost_match and cost_match.contract:
            contract = cost_match.contract or contract
        contractor = row.contractor or _lookup_contractor(row.document, doc_contractor)

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
            "amount_buh": amount_buh,
            "amount_nu": amount_nu,
            "direction": analytics.direction,
            "project_group": analytics.project_group,
            "project": analytics.project,
            "contract": contract,
            "nomenclature": nomenclature,
            "cost_section": cost_match.cost_section if cost_match else "",
            "expense_article": (
                cost_match.calc_article
                if cost_match and section == "Себестоимость" and cost_match.calc_article
                else row.expense_article
            ),
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
            _append_other_pnl_fact(
                facts,
                buh_tax_type=resolved_tax_type,
                nu_tax_type=resolved_nu_tax_type,
                **fact_kwargs,
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

    month_order = list(MONTH_NAMES.values())
    months = sorted({fact.month for fact in facts}, key=month_order.index)
    if not facts:
        warnings.append("После обработки выгрузок не найдено строк с суммами по месяцам.")

    return PipelineResult(facts=facts, months=months, warnings=warnings)


def run_pipeline(paths: dict[str, Path]) -> PipelineResult:
    exports = parse_exports(paths)
    return build_facts(exports)
