from __future__ import annotations

from almabi_dashboard_builder import COST_STRUCTURE_SECTIONS, _chart_cost_structure
from almabi_pipeline import Fact


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
