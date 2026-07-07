from __future__ import annotations

from pathlib import Path

from almabi_management_expense_report import (
    TAX_BUCKET_NON_PRIVILEGED,
    build_management_expense_hierarchy,
    build_management_expense_report,
    build_month_tax_table,
)
from tests.test_almabi_exports import (
    create_cost_workbook,
    create_management_expense_buh_workbook,
    create_realization_workbook,
)


def test_build_management_expense_hierarchy_groups_by_article_and_document():
    rows = [
        {
            "Статья": "Аренда офиса",
            "Документ": "Док 1",
            "Сумма БУ": -45_000,
        },
        {
            "Статья": "Аренда офиса",
            "Документ": "Док 2",
            "Сумма БУ": -30_000,
        },
    ]
    tree = build_management_expense_hierarchy(rows)

    assert len(tree) == 1
    assert tree[0]["name"] == "Аренда офиса"
    assert tree[0]["amount"] == -75_000
    assert tree[0]["row_count"] == 2
    assert len(tree[0]["children"]) == 2


def test_build_month_tax_table_splits_privileged_and_non_privileged():
    rows = [
        {"Месяц": "Май", "Льгота": "Льготные проекты", "Сумма БУ": -25_000},
        {"Месяц": "Май", "Льгота": "Нельготные проекты", "Сумма БУ": -50_000},
    ]
    table = build_month_tax_table(rows)

    assert len(table) == 1
    assert table[0]["month"] == "Май"
    assert table[0]["total"] == -75_000


def test_build_management_expense_report_from_fixture_exports(tmp_path: Path):
    buh_path = tmp_path / "buh.xlsx"
    cost_path = tmp_path / "cost.xlsx"
    realization_path = tmp_path / "realization.xlsx"
    create_management_expense_buh_workbook(buh_path)
    create_cost_workbook(cost_path)
    create_realization_workbook(realization_path, document="Другой документ")

    report = build_management_expense_report(
        buh_path=buh_path,
        cost_path=cost_path,
        revenue_path=realization_path,
        projects_path=realization_path,
    )

    assert report["summary"]["row_count"] == 1
    assert report["summary"]["total_amount"] == -75_000
    assert report["summary"]["non_privileged_amount"] == -75_000
    assert report["rows"][0]["Статья"] == "Аренда офиса"
    assert report["rows"][0]["Месяц"] == "Май"
    assert report["rows"][0]["Льгота"] == TAX_BUCKET_NON_PRIVILEGED
    assert len(report["tree"]) == 1
    assert report["tree"][0]["name"] == "Аренда офиса"
