from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from almabi_excel_utils import (
    analytics_value,
    document_match_keys,
    normalize_text,
    period_sort_key,
)
from almabi_export_parsers import (
    CostRow,
    ParsedExports,
    RealizationRow,
    classify_buh_section,
    classify_cost_section_pq,
    parse_exports,
)
from almabi_pipeline import (
    Fact,
    OTHER_PNL_SECTIONS,
    PipelineResult,
    _amount_buh_for_section,
    _amount_nu_for_section,
    _append_fact,
    _append_other_pnl_fact,
    _build_cost_quantity_lookup,
    _build_duplicate_cost_buh_keys,
    _build_other_pnl_nu_storno_groups,
    _build_other_pnl_section_has_nu,
    _build_other_pnl_storno_groups,
    _is_duplicate_cost_buh_key,
    _lookup_contract,
    _lookup_contractor,
    _merge_doc_tax,
    _other_pnl_nu_mismatch_documents,
    _resolve_fact_tax_type,
    _resolve_other_pnl_nu_tax_type,
    _resolve_row_tax_type,
    _same_period,
    _skip_other_expense_inventory_non_deductible,
    _apply_cost_nu_to_buh_facts,
    resolve_quantity_from_cost,
)
from almabi_pipeline_audit import (
    PipelineAuditLog,
    _match_payload_cost,
    _match_payload_realization,
)
from almabi_project_index import ProjectMeta, build_project_index, lookup_project
from almabi_pq_common import (
    build_cost_pq_lookup,
    is_black_metal_scrap_nomenclature,
    is_buh_revenue_activity_nomenclature,
    lookup_cost_pq_rows,
    nomenclature_key,
)
from almabi_realization_lookup import (
    build_realization_index,
    lookup_exact_realization_operation,
    lookup_realization_for_revenue_amount,
    resolve_realization_match,
)

INCOME_SECTIONS = frozenset({"Выручка", "Прочие доходы"})


@dataclass
class TestPipelineResult:
    result: PipelineResult
    audit: PipelineAuditLog
    audit_path: Path | None = None
    pq_cost_rows: list[dict[str, object]] | None = None


def classify_main_section(section: str) -> str | None:
    """Основной раздел как в Power Query «Свод_нов»."""
    if section in INCOME_SECTIONS:
        return "Доходы"
    if section:
        return "Расходы"
    return None


def _is_meaningful_analytic(value: str) -> bool:
    return value.casefold() not in {"", "без направления", "без группы", "без проекта"}


def _coalesce_pq_value(cost_value: str, rev_value: str) -> str:
    """PQ: один источник; при конфликте — реализация (направление из «Проекты»)."""
    cost = cost_value.strip()
    rev = rev_value.strip()
    cost_ok = _is_meaningful_analytic(cost)
    rev_ok = _is_meaningful_analytic(rev)
    if not cost_ok and rev_ok:
        return rev
    if cost_ok and not rev_ok:
        return cost
    if cost_ok and rev_ok:
        if cost == rev:
            return cost
        return rev
    return ""


def _resolve_analytics_pq(
    *,
    cost_match: CostRow | None,
    rev_match: RealizationRow | None,
    project_meta: ProjectMeta | None = None,
) -> tuple[str, str, str]:
    direction = _coalesce_pq_value(
        cost_match.direction if cost_match else "",
        rev_match.direction if rev_match else "",
    )
    project_group = _coalesce_pq_value(
        cost_match.project_group if cost_match else "",
        rev_match.project_group if rev_match else "",
    )
    project = _coalesce_pq_value(
        cost_match.project if cost_match else "",
        rev_match.project if rev_match else "",
    )
    if project_meta is not None:
        if not _is_meaningful_analytic(direction) and _is_meaningful_analytic(project_meta.direction):
            direction = project_meta.direction
        if not _is_meaningful_analytic(project_group) and _is_meaningful_analytic(project_meta.project_group):
            project_group = project_meta.project_group
        if not _is_meaningful_analytic(project) and _is_meaningful_analytic(project_meta.project):
            project = project_meta.project
    return (
        analytics_value(direction, default="Без направления"),
        analytics_value(project_group, default="Без группы"),
        analytics_value(project, default="Без проекта"),
    )


def _analytics_from_pq(item: dict[str, object], field: str) -> str:
    return normalize_text(item.get(field))


def _cost_row_from_pq_dict(item: dict[str, object]) -> CostRow:
    account = normalize_text(item.get("Счет")) or "20"
    calc_article = normalize_text(item.get("Статья калькуляции")) or "Сырье и материалы"
    section = normalize_text(item.get("Раздел")) or classify_cost_section_pq(calc_article, account)
    return CostRow(
        document=normalize_text(item.get("Документ")),
        nomenclature=normalize_text(item.get("Номенклатура")),
        account=account,
        calc_article=calc_article,
        quantity=float(item.get("Количество") or 0),
        amount=float(item.get("Сумма") or 0),
        month=None,
        cost_section=section,
        direction=_analytics_from_pq(item, "Направление"),
        project_group=_analytics_from_pq(item, "Группа проектов"),
        project=_analytics_from_pq(item, "Проект"),
    )


def _build_raw_cost_lookup(
    cost_rows: list[CostRow],
) -> tuple[
    dict[tuple[str, str, str], list[CostRow]],
    dict[tuple[str, str], list[CostRow]],
]:
    """Lookup для сырой выгрузки себестоимости (без PQ GROUP BY)."""
    by_full: dict[tuple[str, str, str], list[CostRow]] = {}
    by_doc_section: dict[tuple[str, str], list[CostRow]] = {}
    for row in cost_rows:
        document = normalize_text(row.document)
        nomenclature = nomenclature_key(row.nomenclature)
        if not document or not nomenclature:
            continue
        for doc_key in document_match_keys(document):
            by_full.setdefault((doc_key, "Расходы", nomenclature), []).append(row)
            by_doc_section.setdefault((doc_key, "Расходы"), []).append(row)
    return by_full, by_doc_section


def _build_pq_cost_lookup(
    *,
    cost_path: Path,
    projects_path: Path | None,
) -> tuple[
    dict[tuple[str, str, str], list[dict[str, object]]],
    dict[tuple[str, str], list[dict[str, object]]],
]:
    """Lookup как в PQ «Бух.регистр»: сгруппированная себестоимость + «Основной раздел»."""
    from almabi_pq_cost import build_pq_cost_table

    return build_cost_pq_lookup(
        build_pq_cost_table(cost_path, projects_path=projects_path),
    )


def _prepare_cost_lookup(
    *,
    cost_path: Path | None,
    projects_path: Path | None,
    fallback_rows: list[CostRow],
) -> tuple[
    dict[tuple[str, str, str], list[object]],
    dict[tuple[str, str], list[object]],
    bool,
]:
    if cost_path is not None and cost_path.exists():
        by_full, by_doc_section = _build_pq_cost_lookup(
            cost_path=cost_path,
            projects_path=projects_path,
        )
        return by_full, by_doc_section, True
    by_full, by_doc_section = _build_raw_cost_lookup(fallback_rows)
    return by_full, by_doc_section, False


def _lookup_cost_rows_pq(
    document: str,
    main_section: str,
    nomenclature_kt: str,
    *,
    by_full_key: dict[tuple[str, str, str], list[object]],
    by_doc_section: dict[tuple[str, str], list[object]],
    pq_cost_lookup: bool,
) -> list[CostRow]:
    matches = lookup_cost_pq_rows(
        by_full_key,
        by_doc_section,
        document=document,
        main_section=main_section,
        nomenclature=nomenclature_kt,
    )
    if pq_cost_lookup:
        return [_cost_row_from_pq_dict(row) for row in matches if isinstance(row, dict)]
    return [row for row in matches if isinstance(row, CostRow)]


def _pq_cost_section(cost_match: CostRow | None) -> str:
    if cost_match is None:
        return ""
    if cost_match.cost_section:
        return cost_match.cost_section
    return classify_cost_section_pq(cost_match.calc_article, cost_match.account)


def _amount_buh_for_test_section(
    section: str,
    row,
    cost_match: CostRow | None,
    *,
    duplicate_cost_key: bool,
) -> float:
    """Сумма БУ для «Тест BI»: buh-регистр при duplicate key, иначе как PQ."""
    if section != "Себестоимость":
        return _amount_buh_for_section(section, row, cost_match)

    if duplicate_cost_key:
        return -row.amount_buh if row.amount_buh else 0.0

    if cost_match is not None:
        cost_section = _pq_cost_section(cost_match)
        if cost_section and cost_match.amount:
            return -cost_match.amount
    return -row.amount_buh if row.amount_buh else 0.0


def _cost_buh_amounts_for_iterations(
    section: str,
    row,
    cost_iterations: list[CostRow | None],
    *,
    duplicate_cost_key: bool,
) -> list[float]:
    """БУ — из регистра; cost-строки задают только пропорции детализации."""
    if section != "Себестоимость":
        return [
            _amount_buh_for_test_section(
                section,
                row,
                cost_match,
                duplicate_cost_key=duplicate_cost_key,
            )
            for cost_match in cost_iterations
        ]
    buh_total = -float(row.amount_buh or 0)
    if len(cost_iterations) <= 1 or duplicate_cost_key:
        return [buh_total]
    weights = [abs(float(cost_match.amount or 0)) if cost_match else 0.0 for cost_match in cost_iterations]
    weight_sum = sum(weights)
    if weight_sum <= 0:
        weights = [1.0] * len(cost_iterations)
        weight_sum = float(len(cost_iterations))
    amounts: list[float] = []
    assigned = 0.0
    for position, weight in enumerate(weights):
        if position == len(weights) - 1:
            amount = buh_total - assigned
        else:
            amount = buh_total * weight / weight_sum
            assigned += amount
        amounts.append(amount)
    return amounts


def _cost_iterations_for_buh_row(
    section: str,
    cost_matches: list[CostRow],
    *,
    duplicate_cost_key: bool,
) -> list[CostRow | None]:
    if section != "Себестоимость":
        return [cost_matches[0] if cost_matches else None]
    if duplicate_cost_key:
        return [cost_matches[0] if cost_matches else None]
    return cost_matches or [None]


def _raw_cost_rows_for_buh(buh_row, cost_rows: list[CostRow]) -> list[CostRow]:
    """Сырые строки cost — по документу и обязательно по номенклатуре."""
    doc_keys = document_match_keys(buh_row.document)
    nom = nomenclature_key(buh_row.nomenclature_kt)
    if not doc_keys or not nom:
        return []
    matched: list[CostRow] = []
    for row in cost_rows:
        if not (document_match_keys(row.document) & doc_keys):
            continue
        if nomenclature_key(row.nomenclature) != nom:
            continue
        if not _same_period(buh_row, row):
            continue
        matched.append(row)
    return matched


def _prefer_raw_cost_matches(
    pq_matches: list[CostRow],
    raw_matches: list[CostRow],
) -> list[CostRow]:
    if not raw_matches:
        return pq_matches
    if not pq_matches:
        return raw_matches
    if len(raw_matches) > len(pq_matches):
        return raw_matches
    return pq_matches


def build_test_facts(
    exports: ParsedExports,
    *,
    audit: PipelineAuditLog | None = None,
    cost_path: Path | None = None,
    projects_path: Path | None = None,
) -> PipelineResult:
    """Сбор фактов для «Тест BI» — join аналитики как в Power Query «Свод_нов»."""
    facts: list[Fact] = []
    warnings: list[str] = []
    audit_log = audit or PipelineAuditLog()

    doc_tax: dict[str, str] = {}
    doc_contract: dict[str, str] = {}
    doc_contractor: dict[str, str] = {}
    for row in exports.buh:
        _merge_doc_tax(doc_tax, row)
        if row.contract and row.document not in doc_contract:
            doc_contract[row.document] = row.contract
        if row.contractor and row.document not in doc_contractor:
            doc_contractor[row.document] = row.contractor

    cost_by_full, cost_by_doc_section, pq_cost_lookup = _prepare_cost_lookup(
        cost_path=cost_path,
        projects_path=projects_path,
        fallback_rows=exports.cost,
    )
    cost_qty_lookup = _build_cost_quantity_lookup(exports.cost)
    duplicate_cost_buh_keys = _build_duplicate_cost_buh_keys(exports)
    other_pnl_storno_groups = _build_other_pnl_storno_groups(exports)
    other_pnl_nu_storno_groups = _build_other_pnl_nu_storno_groups(exports)
    other_pnl_nu_mismatch_docs = _other_pnl_nu_mismatch_documents(exports)
    other_pnl_section_has_nu = _build_other_pnl_section_has_nu(exports)
    project_by_document, project_key_to_document, project_meta_by_key = build_project_index(exports)
    realization_index = build_realization_index(exports.realization, doc_contract)

    if not exports.realization:
        warnings.append(
            "Файл реализации не загружен — направление будет искаться только в себестоимости."
        )
    if not exports.cost:
        warnings.append(
            "Файл себестоимости не загружен — направление будет искаться только в реализации."
        )
    elif not pq_cost_lookup and exports.cost:
        warnings.append(
            "Файл себестоимости не сгруппирован по правилам PQ — используется сырая выгрузка."
        )
    if exports.cost and not exports.cost_nu:
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

        main_section = classify_main_section(section)
        cost_matches = (
            _lookup_cost_rows_pq(
                row.document,
                main_section or "",
                row.nomenclature_kt,
                by_full_key=cost_by_full,
                by_doc_section=cost_by_doc_section,
                pq_cost_lookup=pq_cost_lookup,
            )
            if exports.cost and main_section
            else []
        )
        if section == "Себестоимость" and exports.cost:
            raw_matches = _raw_cost_rows_for_buh(row, exports.cost)
            cost_matches = _prefer_raw_cost_matches(cost_matches, raw_matches)
        duplicate_cost_key = _is_duplicate_cost_buh_key(duplicate_cost_buh_keys, row)
        cost_iterations = _cost_iterations_for_buh_row(
            section,
            cost_matches,
            duplicate_cost_key=duplicate_cost_key,
        )
        cost_buh_amounts = _cost_buh_amounts_for_iterations(
            section,
            row,
            cost_iterations,
            duplicate_cost_key=duplicate_cost_key,
        )

        for cost_match, amount_buh in zip(cost_iterations, cost_buh_amounts):
            rev_match = None
            if exports.realization:
                buh_contract = analytics_value(row.contract, default="") or _lookup_contract(row.document, doc_contract)
                if section == "Себестоимость":
                    rev_match = resolve_realization_match(
                        buh_row=row,
                        cost_match=cost_match,
                        buh_contract=buh_contract,
                        index=realization_index,
                        prefer_cost_chain=True,
                    )
                elif section in INCOME_SECTIONS:
                    rev_match = resolve_realization_match(
                        buh_row=row,
                        cost_match=None,
                        buh_contract=buh_contract,
                        index=realization_index,
                        prefer_cost_chain=False,
                    )
                else:
                    rev_match = resolve_realization_match(
                        buh_row=row,
                        cost_match=cost_match,
                        buh_contract=buh_contract,
                        index=realization_index,
                        prefer_cost_chain=bool(cost_match),
                    )

            if section == "Себестоимость":
                amount_nu = 0.0
            else:
                amount_nu = _amount_nu_for_section(section, row.amount_nu_dt, row.amount_nu_kt)
            lookup_document = (
                cost_match.document
                if cost_match and cost_match.document
                else row.document
            )
            project_meta = lookup_project(
                lookup_document,
                project_by_document,
                project_key_to_document,
                meta_by_key=project_meta_by_key,
            )
            direction, project_group, project = _resolve_analytics_pq(
                cost_match=cost_match,
                rev_match=rev_match,
                project_meta=project_meta,
            )

            nomenclature = row.nomenclature_kt
            if section == "Выручка" and is_buh_revenue_activity_nomenclature(nomenclature):
                nomenclature = ""
            if section != "Выручка" and cost_match and cost_match.nomenclature:
                nomenclature = cost_match.nomenclature
            elif not nomenclature and rev_match and rev_match.nomenclature:
                nomenclature = rev_match.nomenclature

            if section == "Себестоимость" and is_black_metal_scrap_nomenclature(nomenclature):
                continue

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

            audit_log.log_buh_line(
                section=section,
                row=row,
                main_section=main_section,
                amount_buh=amount_buh,
                amount_nu=amount_nu,
                cost_match=_match_payload_cost(cost_match),
                rev_match=_match_payload_realization(rev_match),
                analytics={
                    "direction": direction,
                    "project_group": project_group,
                    "project": project,
                },
                nomenclature=nomenclature,
            )

            if exact_revenue_operation is not None and exact_revenue_operation.quantity is not None:
                quantity = float(exact_revenue_operation.quantity or 0)
            else:
                quantity = resolve_quantity_from_cost(
                    document=lookup_document,
                    nomenclature=nomenclature,
                    cost_match=cost_match,
                    qty_lookup=cost_qty_lookup,
                )
                # Старые выгрузки без колонки «Количество» сохраняют прежний fallback.
                if quantity <= 0 and section in INCOME_SECTIONS and exports.cost:
                    qty_matches = _lookup_cost_rows_pq(
                        lookup_document,
                        "Расходы",
                        nomenclature_kt=nomenclature or row.nomenclature_kt,
                        by_full_key=cost_by_full,
                        by_doc_section=cost_by_doc_section,
                        pq_cost_lookup=pq_cost_lookup,
                    )
                    if qty_matches:
                        quantity = max(float(item.quantity or 0) for item in qty_matches)
                    if quantity <= 0:
                        quantity = resolve_quantity_from_cost(
                            document=row.document,
                            nomenclature=nomenclature or row.nomenclature_kt,
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
                "direction": direction,
                "project_group": project_group,
                "project": project,
                "contract": contract,
                "nomenclature": nomenclature,
                "cost_section": _pq_cost_section(cost_match),
                "cost_account": normalize_text(getattr(cost_match, "account", "") or "") if cost_match else "",
                "expense_article": (
                    normalize_text(getattr(cost_match, "calc_article", "") or "")
                    or row.expense_article
                ),
                "document": lookup_document,
                "contractor": contractor,
                "quantity": quantity,
            }
            fact_count_before = len(facts)
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
            for fact in facts[fact_count_before:]:
                audit_log.record_fact(fact)

            if section == "Выручка":
                saw_revenue = True
            if section == "Себестоимость":
                saw_cost = True

    if not saw_revenue and exports.realization:
        for row in exports.realization:
            _append_fact(
                facts,
                kpi_l1="Выручка",
                month=row.month,
                period=row.period,
                amount_buh=row.revenue,
                amount_nu=row.revenue,
                direction=row.direction,
                project_group=row.project_group,
                project=row.project,
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
            audit_log.record_fact(facts[-1])
            audit_log.log_fallback_line(
                {
                    "source": "realization_file",
                    "section": "Выручка",
                    "document": row.document,
                    "month": row.month,
                    "amount_buh": row.revenue,
                    "direction": row.direction,
                    "project_group": row.project_group,
                    "project": row.project,
                    "nomenclature": row.nomenclature,
                }
            )

    if not saw_cost and exports.cost:
        for row in exports.cost:
            if is_black_metal_scrap_nomenclature(row.nomenclature):
                continue
            _append_fact(
                facts,
                kpi_l1="Себестоимость",
                month=row.month,
                period=row.period,
                amount_buh=-abs(row.amount),
                amount_nu=0.0,
                direction=row.direction,
                project_group=row.project_group,
                project=row.project,
                contract=_lookup_contract(row.document, doc_contract),
                nomenclature=row.nomenclature,
                document=row.document,
                cost_section=classify_cost_section_pq(row.calc_article, row.account),
                cost_account=row.account,
                expense_article=row.calc_article,
                tax_type=doc_tax.get(row.document, "Общие условия налогообложения"),
                contractor=_lookup_contractor(row.document, doc_contractor),
                quantity=float(row.quantity or 0),
            )
            audit_log.record_fact(facts[-1])
            audit_log.log_fallback_line(
                {
                    "source": "cost_file",
                    "section": "Себестоимость",
                    "document": row.document,
                    "month": row.month,
                    "amount_buh": abs(row.amount),
                    "direction": row.direction,
                    "project_group": row.project_group,
                    "project": row.project,
                    "nomenclature": row.nomenclature,
                    "cost_section": classify_cost_section_pq(row.calc_article, row.account),
                }
            )

    if exports.cost_nu:
        _apply_cost_nu_to_buh_facts(facts, exports.cost_nu, exports.buh)

    audit_log.analyze_duplicates(facts, exports.buh)

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


def run_test_pipeline(
    paths: dict[str, Path],
    *,
    logs_dir: Path | None = None,
    write_audit: bool = True,
) -> TestPipelineResult:
    audit = PipelineAuditLog()
    exports = parse_exports(paths)
    pq_cost_rows: list[dict[str, object]] | None = None
    cost_path = paths.get("cost")
    projects_path = paths.get("realization")
    if cost_path is not None and cost_path.exists():
        from almabi_pq_cost import build_pq_cost_table

        pq_cost_rows = build_pq_cost_table(cost_path, projects_path=projects_path)
    result = build_test_facts(
        exports,
        audit=audit,
        cost_path=cost_path,
        projects_path=projects_path,
    )
    audit_path = audit.write_report(logs_dir) if logs_dir and write_audit else None
    return TestPipelineResult(result=result, audit=audit, audit_path=audit_path, pq_cost_rows=pq_cost_rows)
