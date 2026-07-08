from __future__ import annotations

from almabi_charts_builder import build_analytics_charts, build_expense_kpi_chart
from almabi_pipeline import Fact


def _fact(**kwargs: object) -> Fact:
    defaults = {
        "kpi_l1": "Выручка",
        "month": "Январь",
        "amount_buh": 100.0,
        "amount_nu": 100.0,
        "direction": "Север",
    }
    defaults.update(kwargs)
    return Fact(**defaults)  # type: ignore[arg-type]


def test_build_analytics_charts_groups_revenue_by_direction():
    charts = build_analytics_charts(
        [
            _fact(direction="Север", amount_buh=100),
            _fact(direction="Юг", amount_buh=50),
        ],
        [{"name": "Выручка", "values": {"Факт БУ": {"Январь": 150}, "План": {"Январь": 160}}}],
    )

    assert len(charts["revenue_by_direction"]) == 2
    assert charts["revenue_by_direction"][0]["name"] == "Север"
    assert charts["revenue_by_direction"][0]["fact"] == 100


def test_build_expense_kpi_chart_sums_months():
    rows = build_expense_kpi_chart(
        {
            "Себестоимость": {
                "values": {
                    "Факт БУ": {"Январь": -100, "Февраль": -50},
                    "План": {"Январь": -90, "Февраль": -40},
                }
            }
        }
    )

    assert rows[0]["name"] == "Себестоимость"
    assert rows[0]["fact"] == 150
    assert rows[0]["plan"] == 130
