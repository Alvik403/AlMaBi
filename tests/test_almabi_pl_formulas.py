from __future__ import annotations

import pytest

from almabi_dashboard_builder import _build_summary_rows
from almabi_pipeline import Fact


def _rows_by_name(facts: list[Fact]) -> dict[str, dict]:
    return {row["name"]: row for row in _build_summary_rows(facts)}


def test_pbt_and_tax_match_excel_style_example():
    """Проверка формул на эталонных цифрах пользователя (руб., один период)."""
    facts = [
        Fact(kpi_l1="Выручка", month="Январь", amount_buh=46_719.88, amount_nu=46_719.88),
        Fact(kpi_l1="Себестоимость", month="Январь", amount_buh=-37_154.61, amount_nu=-37_154.61),
        Fact(kpi_l1="Коммерческие расходы", month="Январь", amount_buh=-23.67, amount_nu=-23.67),
        Fact(kpi_l1="Управленческие расходы", month="Январь", amount_buh=-12_121.65, amount_nu=-12_121.65),
        Fact(kpi_l1="Прочие доходы", month="Январь", amount_buh=23_667.80, amount_nu=23_667.80),
        Fact(kpi_l1="Прочие расходы", month="Январь", amount_buh=-4_372.00, amount_nu=-4_372.00),
    ]
    rows = _rows_by_name(facts)

    operating = rows["Операционная прибыль"]["total_fact"]
    pbt = rows["Прибыль/убыток до налогообложения"]["total_fact"]
    taxes = rows["Налоги"]["total_fact"]
    net = rows["Чистая прибыль"]["total_fact"]

    assert operating == pytest.approx(46_719.88 - 37_154.61 - 23.67 - 12_121.65, abs=0.02)
    assert pbt == pytest.approx(operating + 23_667.80 - 4_372.00, abs=0.02)
    assert pbt == pytest.approx(16_715.75, abs=0.02)
    assert taxes == pytest.approx(-pbt * 0.25, abs=0.02)
    assert net == pytest.approx(pbt + taxes, abs=0.02)


def test_expense_kpis_stored_negative_in_summary():
    facts = [
        Fact(kpi_l1="Себестоимость", month="Январь", amount_buh=-100.0, amount_nu=-100.0),
    ]
    rows = _rows_by_name(facts)
    assert rows["Себестоимость"]["total_fact"] == -100.0
