from __future__ import annotations

from almabi_dashboard_builder import COST_STRUCTURE_SECTIONS, _chart_cost_structure, _chart_cost_structure_from_pq_rows
from almabi_pipeline import Fact


def test_chart_cost_structure_from_pq_rows_nets_return_waste():
    structure = _chart_cost_structure_from_pq_rows(
        [
            {
                "Документ": "Реализация товаров и услуг 00АМ-000001 от 31.03.2026 21:00:00",
                "Основной раздел": "Расходы",
                "Раздел": "Материальные затраты",
                "Сумма": 1_000.0,
            },
            {
                "Документ": "Реализация товаров и услуг 00АМ-000002 от 31.03.2026 21:00:00",
                "Основной раздел": "Расходы",
                "Раздел": "Материальные затраты",
                "Сумма": -200.0,
            },
        ]
    )
    march = structure["by_month"][2]
    assert march["sections"]["Материальные затраты"] == 800.0


def test_chart_cost_structure_from_pq_rows_ignores_large_davaltz_documents():
    structure = _chart_cost_structure_from_pq_rows(
        [
            {
                "Документ": "Реализация товаров и услуг 00АМ-000001 от 31.03.2026 21:00:00",
                "Основной раздел": "Расходы",
                "Раздел": "ФОТ",
                "Сумма": 100.0,
            },
            {
                "Документ": "Отчет давальцу 00АМ-000003 от 31.03.2026 9:17:22",
                "Основной раздел": "Расходы",
                "Раздел": "ФОТ",
                "Сумма": 12_086_975.45,
            },
        ]
    )
    march = structure["by_month"][2]
    assert march["sections"]["ФОТ"] == 100.0


def test_chart_cost_structure_from_pq_rows_includes_small_davaltz_fot():
    structure = _chart_cost_structure_from_pq_rows(
        [
            {
                "Документ": "Реализация товаров и услуг 00АМ-000001 от 30.06.2026 21:00:00",
                "Основной раздел": "Расходы",
                "Раздел": "ФОТ",
                "Сумма": 100.0,
            },
            {
                "Документ": "Отчет давальцу 00АМ-000006 от 15.06.2026 16:00:00",
                "Основной раздел": "Расходы",
                "Раздел": "ФОТ",
                "Сумма": 50.0,
            },
            {
                "Документ": "Отчет давальцу 00АМ-000003 от 31.03.2026 9:17:22",
                "Основной раздел": "Расходы",
                "Раздел": "ФОТ",
                "Сумма": 999.0,
            },
        ]
    )
    june = structure["by_month"][5]
    assert june["sections"]["ФОТ"] == 150.0


def test_chart_cost_structure_from_pq_rows_ignores_black_metal_scrap_nomenclature():
    structure = _chart_cost_structure_from_pq_rows(
        [
            {
                "Документ": "Реализация товаров и услуг 00АМ-000001 от 31.03.2026 21:00:00",
                "Основной раздел": "Расходы",
                "Раздел": "Материальные затраты",
                "Номенклатура": "Лом черных металлов. Лом черных м/л 12А (кг)",
                "Сумма": 59_762.0,
            },
            {
                "Документ": "Реализация товаров и услуг 00АМ-000002 от 31.03.2026 21:00:00",
                "Основной раздел": "Расходы",
                "Раздел": "Материальные затраты",
                "Номенклатура": "Болт М12",
                "Сумма": 1_000.0,
            },
        ]
    )
    march = structure["by_month"][2]
    assert march["sections"]["Материальные затраты"] == 1_000.0


def test_chart_cost_structure_from_pq_rows_uses_document_month():
    structure = _chart_cost_structure_from_pq_rows(
        [
            {
                "Документ": "Реализация товаров и услуг 00АМ-000057 от 31.03.2026 21:00:00",
                "Основной раздел": "Расходы",
                "Раздел": "Амортизация",
                "Сумма": 117_705.82,
            },
            {
                "Документ": "Реализация товаров и услуг 00АМ-000001 от 31.01.2026 21:00:00",
                "Основной раздел": "Расходы",
                "Раздел": "Амортизация",
                "Сумма": 50_000.0,
            },
            {
                "Документ": "Реализация товаров и услуг 00АМ-000002 от 31.03.2026 21:00:00",
                "Основной раздел": "Доходы",
                "Раздел": "Выручка",
                "Сумма": 999_999.0,
            },
        ]
    )
    march = structure["by_month"][2]
    jan = structure["by_month"][0]
    assert march["sections"]["Амортизация"] == 117_705.82
    assert jan["sections"]["Амортизация"] == 50_000.0


def test_chart_cost_structure_only_known_sections():
    structure = _chart_cost_structure(
        [
            Fact(
                kpi_l1="Себестоимость",
                month="Январь",
                amount_buh=-100,
                amount_nu=-100,
                cost_section="Материальные затраты",
            ),
            Fact(
                kpi_l1="Себестоимость",
                month="Январь",
                amount_buh=-50,
                amount_nu=-50,
                cost_section="ФОТ",
            ),
            Fact(
                kpi_l1="Себестоимость",
                month="Февраль",
                amount_buh=-30,
                amount_nu=-30,
                cost_section="ФОТ",
            ),
            Fact(
                kpi_l1="Себестоимость",
                month="Январь",
                amount_buh=-999,
                amount_nu=-999,
                cost_section="Служебная статья вне БДР",
            ),
        ]
    )

    assert structure["sections"] == list(COST_STRUCTURE_SECTIONS)

    jan = structure["by_month"][0]
    assert jan["total"] == 150
    assert jan["sections"]["Материальные затраты"] == 100
    assert jan["sections"]["ФОТ"] == 50
    assert jan["sections"]["Амортизация"] == 0

    feb = structure["by_month"][1]
    assert feb["sections"]["ФОТ"] == 30
