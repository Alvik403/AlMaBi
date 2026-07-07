from __future__ import annotations

from almabi_dashboard_builder import (
    NON_PRIVILEGED_BUCKET,
    PRIVILEGED_BUCKET,
    _build_drill_data,
    _build_summary_rows,
)
from almabi_pipeline import Fact


def _fact(**kwargs: object) -> Fact:
    defaults = {
        "kpi_l1": "Прочие расходы",
        "month": "Январь",
        "amount_buh": -100.0,
        "amount_nu": -100.0,
        "expense_article": "Проценты",
        "tax_type": "Общие условия налогообложения",
    }
    defaults.update(kwargs)
    return Fact(**defaults)  # type: ignore[arg-type]


def test_build_drill_data_splits_articles_by_tax_bucket():
    drill = _build_drill_data(
        [
            _fact(
                expense_article="Проценты",
                tax_type="Доходы по льготируемым видам деятельности",
                amount_buh=-50,
                amount_nu=-40,
            ),
            _fact(
                expense_article="Проценты",
                tax_type="Общие условия налогообложения",
                amount_buh=-150,
                amount_nu=-120,
            ),
            _fact(
                expense_article="Штрафы",
                month="Февраль",
                amount_buh=-20,
                amount_nu=-20,
            ),
        ]
    )

    jan = drill["months"]["Январь"]["articles"]
    interest = next(item for item in jan if item["name"] == "Проценты")
    assert interest[PRIVILEGED_BUCKET]["buh"] == -50
    assert interest[NON_PRIVILEGED_BUCKET]["buh"] == -150

    feb = drill["months"]["Февраль"]["articles"]
    assert len(feb) == 1
    assert feb[0]["name"] == "Штрафы"


def test_summary_rows_include_drill_payload():
    rows = _build_summary_rows(
        [
            _fact(
                kpi_l1="Коммерческие расходы",
                contract="Договор 1",
                expense_article="",
                amount_buh=-300,
            ),
            _fact(
                kpi_l1="Коммерческие расходы",
                contract="Договор 2",
                expense_article="",
                tax_type="Доходы по льготируемым видам деятельности",
                amount_buh=-100,
            ),
        ]
    )
    commercial = next(row for row in rows if row["name"] == "Коммерческие расходы")
    assert "drill" in commercial
    articles = commercial["drill"]["total"]["articles"]
    assert {item["name"] for item in articles} == {"Договор 1", "Договор 2"}
