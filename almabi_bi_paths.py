from __future__ import annotations

from almabi_excel_utils import tax_bucket
from almabi_pipeline import Fact

ARTICLE_BENEFIT_SECTIONS = frozenset({"Прочие доходы", "Прочие расходы"})
BENEFIT_KPI_SECTIONS = frozenset(
    {
        "Коммерческие расходы",
        "Управленческие расходы",
        "Прочие доходы",
        "Прочие расходы",
        "Налоги",
    }
)


def fact_bi_path(fact: Fact) -> str:
    """Путь строки в дереве дашборда (куда попадает факт в BI)."""
    if fact.kpi_l1 in BENEFIT_KPI_SECTIONS:
        parts = [fact.kpi_l1, tax_bucket(fact.tax_type)]
        if fact.kpi_l1 in ARTICLE_BENEFIT_SECTIONS:
            parts.append(fact.expense_article or "Прочее")
        parts.append(fact.contract or "Без договора")
        return " → ".join(parts)

    if fact.kpi_l1 == "Выручка":
        return " → ".join(
            [
                fact.kpi_l1,
                fact.direction or "Без направления",
                fact.project_group or "Без группы",
                fact.project or "Без проекта",
                fact.contract or "Без договора",
            ]
        )

    if fact.kpi_l1 == "Себестоимость":
        return " → ".join(
            [
                fact.kpi_l1,
                fact.direction or "Без направления",
                fact.project_group or "Без группы",
                fact.project or "Без проекта",
                fact.contract or "Без договора",
            ]
        )

    return " → ".join(
        [
            fact.kpi_l1,
            fact.direction or "Без направления",
            fact.project_group or "Без группы",
            fact.project or "Без проекта",
        ]
    )
