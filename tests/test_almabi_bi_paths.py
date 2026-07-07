from __future__ import annotations

from almabi_bi_paths import fact_bi_path
from almabi_pipeline import Fact


def test_fact_bi_path_for_benefit_section():
    fact = Fact(
        kpi_l1="Коммерческие расходы",
        month="Январь",
        amount_buh=1000,
        amount_nu=1000,
        tax_type="Общие условия налогообложения",
        contract="Д-001",
    )
    assert fact_bi_path(fact) == "Коммерческие расходы → Нельготные проекты → Д-001"


def test_fact_bi_path_for_other_income_with_article():
    fact = Fact(
        kpi_l1="Прочие доходы",
        month="Март",
        amount_buh=400_000,
        amount_nu=400_000,
        tax_type="Доходы по льготируемым видам деятельности",
        expense_article="Проценты",
        contract="АМ-472/25",
    )
    assert (
        fact_bi_path(fact)
        == "Прочие доходы → Льготные проекты → Проценты → АМ-472/25"
    )
