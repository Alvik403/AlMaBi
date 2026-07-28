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


def test_operating_profit_equals_components_with_tax_split():
    facts = [
        Fact(
            kpi_l1="Выручка",
            month="Апрель",
            amount_buh=100.0,
            amount_nu=200.0,
            tax_type="Доходы по льготируемым видам деятельности",
        ),
        Fact(
            kpi_l1="Выручка",
            month="Апрель",
            amount_buh=50.0,
            amount_nu=80.0,
            tax_type="Общие условия налогообложения",
        ),
        Fact(
            kpi_l1="Себестоимость",
            month="Апрель",
            amount_buh=-30.0,
            amount_nu=-25.0,
            tax_type="Доходы по льготируемым видам деятельности",
        ),
        Fact(
            kpi_l1="Коммерческие расходы",
            month="Апрель",
            amount_buh=-10.0,
            amount_nu=-10.0,
            tax_type="Общие условия налогообложения",
        ),
        Fact(
            kpi_l1="Управленческие расходы",
            month="Апрель",
            amount_buh=-5.0,
            amount_nu=-5.0,
            tax_type="Доходы по льготируемым видам деятельности",
        ),
    ]
    rows = _rows_by_name(facts)
    month = "Апрель"
    components = [
        "Выручка",
        "Себестоимость",
        "Коммерческие расходы",
        "Управленческие расходы",
    ]
    operating = rows["Операционная прибыль"]

    for scenario in ("Факт БУ", "Факт НУ"):
        component_sum = sum(float(rows[name]["values"][scenario][month]) for name in components)
        operating_value = float(operating["values"][scenario][month])
        child_sum = sum(float(child["values"][scenario][month]) for child in operating["children"])
        assert operating_value == pytest.approx(component_sum, abs=0.01)
        assert child_sum == pytest.approx(operating_value, abs=0.01)

    privileged = next(child for child in operating["children"] if child["name"] == "Льготные проекты")
    non_privileged = next(child for child in operating["children"] if child["name"] == "Нельготные проекты")
    assert privileged.get("signed_amounts") is True
    assert non_privileged.get("signed_amounts") is True
    assert float(privileged["values"]["Факт БУ"][month]) == pytest.approx(200.0 - 30.0 - 5.0, abs=0.01)
    assert float(non_privileged["values"]["Факт БУ"][month]) == pytest.approx(80.0 - 10.0, abs=0.01)


def test_taxes_are_zero_when_pbt_base_is_not_positive():
    facts = [
        Fact(kpi_l1="Выручка", month="Январь", amount_buh=100.0, amount_nu=100.0),
        Fact(kpi_l1="Себестоимость", month="Январь", amount_buh=-500.0, amount_nu=-500.0),
    ]
    rows = _rows_by_name(facts)
    assert rows["Прибыль/убыток до налогообложения"]["total_fact"] == -400.0
    assert rows["Налоги"]["total_fact"] == 0.0
    assert rows["Чистая прибыль"]["total_fact"] == -400.0


def test_tax_loss_carryforward_offsets_future_profit():
    """Убытки накапливаются и уменьшают базу в следующих месяцах (2% / 25%)."""
    privileged = "Доходы по льготируемым видам деятельности"
    non_privileged = "Общие условия налогообложения"
    facts = [
        Fact(kpi_l1="Выручка", month="Январь", amount_buh=5000, amount_nu=5000, tax_type=privileged),
        Fact(kpi_l1="Себестоимость", month="Февраль", amount_buh=-3000, amount_nu=-3000, tax_type=privileged),
        Fact(kpi_l1="Себестоимость", month="Март", amount_buh=-2000, amount_nu=-2000, tax_type=privileged),
        Fact(kpi_l1="Выручка", month="Апрель", amount_buh=10000, amount_nu=10000, tax_type=privileged),
        Fact(kpi_l1="Выручка", month="Январь", amount_buh=5000, amount_nu=5000, tax_type=non_privileged),
        Fact(kpi_l1="Себестоимость", month="Февраль", amount_buh=-3000, amount_nu=-3000, tax_type=non_privileged),
        Fact(kpi_l1="Себестоимость", month="Март", amount_buh=-2000, amount_nu=-2000, tax_type=non_privileged),
        Fact(kpi_l1="Выручка", month="Апрель", amount_buh=10000, amount_nu=10000, tax_type=non_privileged),
    ]
    rows = _rows_by_name(facts)
    taxes = rows["Налоги"]["values"]["Факт НУ"]
    assert float(taxes["Январь"]) == pytest.approx(-5000 * 0.02 - 5000 * 0.25, abs=0.01)
    assert float(taxes["Февраль"]) == 0.0
    assert float(taxes["Март"]) == 0.0
    assert float(taxes["Апрель"]) == pytest.approx(-5000 * 0.02 - 5000 * 0.25, abs=0.01)
