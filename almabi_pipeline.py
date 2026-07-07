from __future__ import annotations

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


def _amount_nu_for_section(section: str, amount_nu_dt: float, amount_nu_kt: float) -> float:
    """Сумма НУ по правилам Power Query «Свод_нов» (со знаком)."""
    if section == "Себестоимость":
        return -amount_nu_kt if amount_nu_kt else 0.0
    if section in {"Прочие расходы", "Коммерческие расходы", "Управленческие расходы"}:
        return -amount_nu_dt if amount_nu_dt else 0.0
    if section == "Прочие доходы":
        return amount_nu_kt
    return amount_nu_kt


def _amount_buh_for_section(section: str, row: BuhRow, cost_match: CostRow | None) -> float:
    """Сумма БУ по правилам Power Query «Свод_нов» (со знаком)."""
    if section == "Себестоимость":
        if cost_match is not None:
            return -cost_match.amount if cost_match.amount else 0.0
        # Как в PQ «Бух.регистр»: без join к файлу себестоимости — «Сумма» без инверсии.
        return row.amount_buh if row.amount_buh else 0.0
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
            lookup.setdefault((key, nomenclature), row)
    return lookup


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
        )
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

        amount_buh = _amount_buh_for_section(section, row, cost_match)
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

        _append_fact(
            facts,
            kpi_l1=section,
            month=row.month,
            amount_buh=amount_buh,
            amount_nu=amount_nu,
            direction=analytics.direction,
            project_group=analytics.project_group,
            project=analytics.project,
            contract=contract,
            nomenclature=nomenclature,
            cost_section=cost_match.cost_section if cost_match else "",
            expense_article=(
                cost_match.calc_article
                if cost_match and section == "Себестоимость" and cost_match.calc_article
                else row.expense_article
            ),
            tax_type=row.tax_type,
            contractor=contractor,
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
