from __future__ import annotations

from almabi_dashboard_builder import _build_summary_rows
from almabi_pipeline import Fact


def _child_names(node: dict) -> list[str]:
    return [child["name"] for child in node.get("children") or []]


def test_benefit_branches_include_contracts():
    facts = [
        Fact(
            kpi_l1="Коммерческие расходы",
            month="Январь",
            amount_buh=50_000,
            amount_nu=50_000,
            tax_type="Общие условия налогообложения",
            contract="Д-001",
        ),
        Fact(
            kpi_l1="Прочие доходы",
            month="Март",
            amount_buh=400_000,
            amount_nu=400_000,
            tax_type="Общие условия налогообложения",
            expense_article="Проценты",
            contract="Д-014",
        ),
    ]
    rows = {row["name"]: row for row in _build_summary_rows(facts)}

    commercial = rows["Коммерческие расходы"]
    nelf = next(child for child in commercial["children"] if child["name"] == "Нельготные проекты")
    assert _child_names(nelf) == ["Д-001"]

    other = rows["Прочие доходы"]
    nelf_other = next(child for child in other["children"] if child["name"] == "Нельготные проекты")
    assert _child_names(nelf_other) == ["Проценты"]
    article = nelf_other["children"][0]
    assert _child_names(article) == ["Д-014"]
