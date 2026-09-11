from __future__ import annotations

from almabi_drill_matching import (
    build_drill_cost_lookup,
    drill_analytics_compatible,
    drill_document_identity_key,
    drill_operation_key,
    lookup_drill_cost,
    scope_realization_rows_for_drill,
    should_exclude_rev_fact_from_drill_fallback,
)
from almabi_export_parsers import RealizationRow
from almabi_pipeline import Fact


def _fact(**kwargs: object) -> Fact:
    defaults = {
        "kpi_l1": "Выручка",
        "month": "Июль",
        "period": "2026-07",
        "amount_buh": 100.0,
        "amount_nu": 100.0,
    }
    defaults.update(kwargs)
    return Fact(**defaults)  # type: ignore[arg-type]


def test_drill_document_identity_key_ignores_document_date():
    left = "Реализация товаров и услуг 00АМ-000205 от 10.07.2026 21:00:00"
    right = "Реализация товаров и услуг 00АМ-000205 от 16.07.2026 21:00:00"
    assert drill_document_identity_key(left) == drill_document_identity_key(right)


def test_drill_analytics_treats_placeholders_as_wildcards():
    assert drill_analytics_compatible("Без направления", "Производство (Слаботочка)")
    assert drill_analytics_compatible("Перепродажа", "Без группы")
    assert not drill_analytics_compatible("Перепродажа", "Услуги")


def test_scope_realization_rows_matches_by_document_not_name():
    document_buh = "Реализация товаров и услуг 00АМ-000205 от 10.07.2026 21:00:00"
    document_real = "Реализация товаров и услуг 00АМ-000205 от 16.07.2026 21:00:00"
    rev_subset = [
        _fact(
            nomenclature='Программно-аппаратный комплекс "Око"',
            document=document_buh,
            direction="Без направления",
            project_group="Без группы",
            project="Без проекта",
            quantity=0,
            amount_nu=10_063_508,
        )
    ]
    realization_rows = [
        RealizationRow(
            document=document_real,
            nomenclature='Программно-аппаратный комплекс "Око" (длинное наименование)',
            direction="Без направления",
            project_group="Без группы",
            project="Без проекта",
            revenue=34_329_350.0,
            month="Июль",
            period="2026-07",
            quantity=1.0,
        )
    ]
    scoped = scope_realization_rows_for_drill(realization_rows, rev_subset)
    assert len(scoped) == 1
    assert scoped[0].quantity == 1.0


def test_should_exclude_aggregated_buh_line_when_document_covered():
    fact = _fact(
        nomenclature='Программно-аппаратный комплекс "Око"',
        document="Реализация товаров и услуг 00АМ-000205 от 10.07.2026 21:00:00",
    )
    covered = {"00ам-000205"}
    assert should_exclude_rev_fact_from_drill_fallback(
        fact,
        covered_document_keys=covered,
    )


def test_lookup_drill_cost_matches_when_document_dates_differ():
    nom = 'Программно-аппаратный комплекс «Око» Тип 1 Исполнение 16 (модиф.№08/12/25-ОЛ8-С2321_В_Т1И16)'
    cost_lookup = build_drill_cost_lookup(
        [
            _fact(
                kpi_l1="Себестоимость",
                nomenclature=nom,
                document="Реализация товаров и услуг 00АМ-000205 от 10.07.2026 21:00:00",
                amount_buh=-1_000,
                amount_nu=-1_000,
            )
        ],
        period_for_fact=lambda fact: fact.period or "",
        display_name_for_fact=lambda fact: fact.nomenclature or "",
    )
    cost = lookup_drill_cost(
        cost_lookup,
        period="2026-07",
        document="Реализация товаров и услуг 00АМ-000205 от 16.07.2026 21:00:00",
        nomenclature=nom,
    )
    assert cost["nu"] == 1_000


def test_drill_operation_key_uses_document_identity():
    left = drill_operation_key(
        period="2026-07",
        document="Реализация товаров и услуг 00АМ-000205 от 10.07.2026 21:00:00",
        nomenclature="Комплект А",
    )
    right = drill_operation_key(
        period="2026-07",
        document="Реализация товаров и услуг 00АМ-000205 от 16.07.2026 21:00:00",
        nomenclature="Комплект А",
    )
    assert left == right
