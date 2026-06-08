from __future__ import annotations

from dataclasses import dataclass, field

from pathlib import Path

from almabi_excel_utils import MONTH_NAMES, analytics_value, document_match_keys, tax_bucket
from almabi_export_parsers import (
    BuhRow,
    ParsedExports,
    classify_buh_section,
    parse_exports,
)
from almabi_project_index import build_project_index, lookup_project


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


@dataclass
class PipelineResult:
    facts: list[Fact] = field(default_factory=list)
    months: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _amount_nu(amount_dt: float, amount_kt: float) -> float:
    return abs(amount_dt) + abs(amount_kt)


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


def _lookup_contractor(document: str, doc_contractor: dict[str, str]) -> str:
    if document in doc_contractor:
        return doc_contractor[document]
    document_keys = document_match_keys(document)
    for contractor_document, contractor_value in doc_contractor.items():
        if document_keys & document_match_keys(contractor_document):
            return contractor_value
    return ""


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
) -> None:
    if not month or not amount_buh:
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
        )
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

    project_by_document, project_key_index = build_project_index(exports)

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

    if exports.realization:
        for row in exports.realization:
            project = lookup_project(row.document, project_by_document, project_key_index)
            tax_type = doc_tax.get(row.document, "Общие условия налогообложения")
            contract = _lookup_contract(row.document, doc_contract)
            _append_fact(
                facts,
                kpi_l1="Выручка",
                month=row.month,
                amount_buh=row.revenue,
                amount_nu=row.revenue,
                direction=project.direction,
                project_group=project.project_group,
                project=project.project,
                contract=contract,
                nomenclature=row.nomenclature,
                tax_type=tax_type,
                contractor=_lookup_contractor(row.document, doc_contractor),
            )
    else:
        warnings.append("Файл реализации не загружен — выручка будет взята из бухрегистра.")

    if exports.cost:
        for row in exports.cost:
            project = lookup_project(row.document, project_by_document, project_key_index)
            tax_type = doc_tax.get(row.document, "Общие условия налогообложения")
            _append_fact(
                facts,
                kpi_l1="Себестоимость",
                month=row.month,
                amount_buh=abs(row.amount),
                amount_nu=abs(row.amount),
                direction=project.direction,
                project_group=project.project_group,
                project=project.project,
                contract=_lookup_contract(row.document, doc_contract),
                nomenclature=row.nomenclature,
                cost_section=row.cost_section,
                tax_type=tax_type,
                contractor=_lookup_contractor(row.document, doc_contractor),
            )
    else:
        warnings.append("Файл себестоимости не загружен — себестоимость будет взята из бухрегистра.")

    used_revenue_keys: set[str] = set()
    used_cost_keys: set[tuple[str, str]] = set()
    if exports.realization:
        for row in exports.realization:
            used_revenue_keys |= document_match_keys(row.document)
    if exports.cost:
        used_cost_keys = {(row.document, row.nomenclature.casefold()) for row in exports.cost if row.nomenclature}

    for row in exports.buh:
        section = classify_buh_section(row.account_dt, row.account_kt)
        if not section or not row.month:
            continue

        if section == "Выручка" and exports.realization and document_match_keys(row.document) & used_revenue_keys:
            continue
        if section == "Себестоимость" and exports.cost:
            key = (row.document, row.nomenclature_kt.casefold())
            if row.nomenclature_kt and key in used_cost_keys:
                continue

        project = lookup_project(
            row.document,
            project_by_document,
            project_key_index,
            fallback_project=row.project,
        )
        amount_buh = abs(row.amount_buh)
        amount_nu = _amount_nu(row.amount_nu_dt, row.amount_nu_kt) or amount_buh

        _append_fact(
            facts,
            kpi_l1=section,
            month=row.month,
            amount_buh=amount_buh,
            amount_nu=amount_nu,
            direction=project.direction,
            project_group=project.project_group,
            project=project.project,
            contract=analytics_value(row.contract, default=""),
            nomenclature=row.nomenclature_kt,
            expense_article=row.expense_article,
            tax_type=row.tax_type,
            contractor=row.contractor,
        )

    month_order = list(MONTH_NAMES.values())
    months = sorted({fact.month for fact in facts}, key=month_order.index)
    if not facts:
        warnings.append("После обработки выгрузок не найдено строк с суммами по месяцам.")

    return PipelineResult(facts=facts, months=months, warnings=warnings)


def run_pipeline(paths: dict[str, Path]) -> PipelineResult:
    exports = parse_exports(paths)
    return build_facts(exports)
