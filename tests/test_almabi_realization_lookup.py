from __future__ import annotations

from almabi_realization_lookup import (
    build_realization_index,
    lookup_exact_realization_operation,
    lookup_realization_for_revenue_amount,
    lookup_realization_row,
    resolve_realization_match,
)
from almabi_export_parsers import BuhRow, CostRow, RealizationRow


def _buh(**kwargs) -> BuhRow:
    defaults = {
        "document": "Реализация товаров и услуг 00АМ-000017 от 31.01.2026 21:00:00",
        "account_dt": "90.02.1",
        "account_kt": "43",
        "amount_buh": 400_000,
        "amount_nu_dt": 400_000,
        "amount_nu_kt": 0,
        "month": "Январь",
        "tax_type": "Общие условия налогообложения",
        "expense_article": "",
        "contract": "Д-001",
        "project": "",
        "nomenclature_kt": "Лицензия ПО",
        "contractor": "",
    }
    defaults.update(kwargs)
    return BuhRow(**defaults)


def test_lookup_by_contract_and_nomenclature():
    doc = "Реализация товаров и услуг 00АМ-000017 от 31.01.2026 21:00:00"
    realization = [
        RealizationRow(
            document=doc,
            nomenclature="Лицензия ПО",
            project="Обслуживание Долго",
            project_group="Обслуживание",
            direction="Услуги",
            revenue=1_000_000,
            month="Январь",
            contract="Д-001",
        )
    ]
    index = build_realization_index(realization, {doc: "Д-001"})
    match = lookup_realization_row(
        document=doc,
        nomenclature="Лицензия ПО",
        contract="Д-001",
        index=index,
    )
    assert match is not None
    assert match.direction == "Услуги"


def test_cost_chain_prefers_contract_from_cost_row():
    doc = "Реализация товаров и услуг 00АМ-000017 от 31.01.2026 21:00:00"
    realization = [
        RealizationRow(
            document=doc,
            nomenclature="Лицензия ПО",
            project="Обслуживание Долго",
            project_group="Обслуживание",
            direction="Услуги",
            revenue=1_000_000,
            month="Январь",
        )
    ]
    index = build_realization_index(realization, {doc: "Д-001"})
    cost_match = CostRow(
        document=doc,
        nomenclature="Лицензия ПО",
        account="20",
        calc_article="Материальные затраты",
        quantity=1,
        amount=400_000,
        month="Январь",
        cost_section="Материальные затраты",
        contract="Д-001",
    )
    match = resolve_realization_match(
        buh_row=_buh(contract=""),
        cost_match=cost_match,
        buh_contract="",
        index=index,
        prefer_cost_chain=True,
    )
    assert match is not None
    assert match.project == "Обслуживание Долго"


def test_lookup_realization_for_revenue_amount_matches_document_and_sum():
    doc = "Реализация товаров и услуг 00АМ-000017 от 31.01.2026 21:00:00"
    target = RealizationRow(
        document=doc,
        nomenclature="Комплект ЭПР Матриц реактивной моторной лодки Г11779-4",
        project="Проект",
        project_group="Группа",
        direction="Товары",
        revenue=1_000_000,
        month="Январь",
        quantity=2,
    )
    other = RealizationRow(
        document=doc,
        nomenclature="Другой товар",
        project="Проект",
        project_group="Группа",
        direction="Товары",
        revenue=250_000,
        month="Январь",
        quantity=1,
    )
    match = lookup_realization_for_revenue_amount(
        document=doc,
        amount_buh=1_220_000,
        amount_nu=1_000_000,
        rows=[target, other],
    )
    assert match is target


def test_exact_operation_lookup_does_not_fall_back_to_contract():
    first = RealizationRow(
        document="Реализация А от 01.01.2026",
        nomenclature="Товар А",
        project="Проект А",
        project_group="Группа",
        direction="Товары",
        revenue=100,
        month="Январь",
        quantity=2,
        contract="Д-001",
    )
    second = RealizationRow(
        document="Реализация Б от 02.01.2026",
        nomenclature="Товар Б",
        project="Проект Б",
        project_group="Группа",
        direction="Товары",
        revenue=200,
        month="Январь",
        quantity=3,
        contract="Д-001",
    )
    index = build_realization_index([first, second], {})

    assert (
        lookup_exact_realization_operation(
            document=second.document,
            nomenclature=second.nomenclature,
            index=index,
        )
        is second
    )
    assert (
        lookup_exact_realization_operation(
            document=second.document,
            nomenclature=first.nomenclature,
            index=index,
        )
        is None
    )
