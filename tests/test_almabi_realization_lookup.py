from __future__ import annotations

from almabi_realization_lookup import build_realization_index, lookup_realization_row, resolve_realization_match
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
