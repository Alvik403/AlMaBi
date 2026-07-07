from __future__ import annotations

from almabi_dashboard_builder import _build_kpi_node, _month_values
from almabi_pipeline import Fact


def test_month_values_use_nu_for_fact_nu_scenario():
    amounts = {"Январь": {"buh": 1000.0, "nu": 800.0}}
    values = _month_values(amounts, always_nu=False)

    assert values["Факт БУ"]["Январь"] == 1000.0
    assert values["Факт НУ"]["Январь"] == 800.0


def test_revenue_always_uses_nu_for_both_fact_scenarios():
    amounts = {"Январь": {"buh": 1000.0, "nu": 800.0}}
    values = _month_values(amounts, always_nu=True)

    assert values["Факт БУ"]["Январь"] == 800.0
    assert values["Факт НУ"]["Январь"] == 800.0


def test_revenue_kpi_node_scenarios_from_facts():
    facts = [
        Fact(
            kpi_l1="Выручка",
            month="Январь",
            amount_buh=1_000_000,
            amount_nu=900_000,
        )
    ]
    node = _build_kpi_node("Выручка", facts, always_nu=True)

    assert node["values"]["Факт БУ"]["Январь"] == 900_000
    assert node["values"]["Факт НУ"]["Январь"] == 900_000


def test_cost_kpi_node_switches_between_buh_and_nu():
    facts = [
        Fact(
            kpi_l1="Себестоимость",
            month="Январь",
            amount_buh=-400_000,
            amount_nu=-350_000,
        )
    ]
    node = _build_kpi_node("Себестоимость", facts, always_nu=False)

    assert node["values"]["Факт БУ"]["Январь"] == -400_000
    assert node["values"]["Факт НУ"]["Январь"] == -350_000


def test_other_income_with_zero_nu_does_not_use_buh_amount():
    from almabi_export_parsers import BuhRow, classify_buh_section
    from almabi_pipeline import _amount_buh_for_section, _amount_nu_for_section

    row = BuhRow(
        document="Операция 0001",
        account_dt="76.09",
        account_kt="91.01",
        amount_buh=156_762,
        amount_nu_dt=0,
        amount_nu_kt=0,
        month="Январь",
        tax_type="Общие условия налогообложения",
        expense_article="",
        contract="",
        project="",
        nomenclature_kt="",
        contractor="",
    )
    section = classify_buh_section(row.account_dt, row.account_kt)
    assert section == "Прочие доходы"
    assert _amount_buh_for_section(section, row, None) == 156_762
    assert _amount_nu_for_section(section, row.amount_nu_dt, row.amount_nu_kt) == 0
