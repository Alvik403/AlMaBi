from __future__ import annotations

from almabi_contractor_builder import build_contractor_cards, build_contractor_details
from almabi_pipeline import Fact


def _revenue_fact(**overrides) -> Fact:
    defaults = {
        "kpi_l1": "Выручка",
        "month": "Январь",
        "amount_buh": 100_000,
        "amount_nu": 100_000,
        "direction": "Услуги",
        "project_group": "Обслуживание",
        "project": "Проект А",
        "contract": "Д-001",
        "tax_type": "Льготное налогообложение",
        "contractor": "ООО Альфа",
    }
    defaults.update(overrides)
    return Fact(**defaults)


def test_build_contractor_details_groups_revenue_only():
    facts = [
        _revenue_fact(contractor="ООО Альфа", amount_buh=120_000),
        _revenue_fact(contractor="ООО Бета", amount_buh=80_000, tax_type="Общие условия налогообложения"),
        Fact(kpi_l1="Себестоимость", month="Январь", amount_buh=50_000, amount_nu=50_000, contractor="ООО Альфа"),
    ]

    details = build_contractor_details(facts)

    assert len(details) == 2
    assert {item["contractor"] for item in details} == {"ООО Альфа", "ООО Бета"}
    assert details[0]["tax_bucket"] == "Льготные проекты"
    assert details[1]["tax_bucket"] == "Нельготные проекты"


def test_build_contractor_cards_sorts_and_splits_by_tax_bucket():
    details = build_contractor_details(
        [
            _revenue_fact(contractor="ООО Альфа", amount_buh=300_000),
            _revenue_fact(contractor="ООО Бета", amount_buh=100_000),
            _revenue_fact(
                contractor="ООО Гамма",
                amount_buh=200_000,
                tax_type="Общие условия налогообложения",
            ),
        ]
    )

    cards = build_contractor_cards(details)

    assert len(cards) == 2
    privileged = next(card for card in cards if card["title"] == "Реализация льгота")
    non_privileged = next(card for card in cards if card["title"] == "Реализация нельгота")
    assert privileged["rows"][0]["name"] == "ООО Альфа"
    assert privileged["total"] == 400_000
    assert non_privileged["rows"][0]["name"] == "ООО Гамма"
    assert non_privileged["total"] == 200_000
