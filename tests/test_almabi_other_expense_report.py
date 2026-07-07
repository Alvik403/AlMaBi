from __future__ import annotations

from pathlib import Path

from almabi_other_expense_report import (
    TAX_BUCKET_NON_PRIVILEGED,
    build_month_tax_table,
    build_other_expense_hierarchy,
    build_other_expense_report,
)
from tests.test_almabi_exports import (
    create_cost_workbook,
    create_other_expense_buh_workbook,
    create_realization_workbook,
)


def test_build_other_expense_hierarchy_groups_by_article_and_document():
    rows = [
        {
            "Статья": "Штрафы",
            "Документ": "Док 1",
            "Сумма БУ": -30_000,
        },
        {
            "Статья": "Штрафы",
            "Документ": "Док 2",
            "Сумма БУ": -20_000,
        },
    ]
    tree = build_other_expense_hierarchy(rows)

    assert len(tree) == 1
    assert tree[0]["name"] == "Штрафы"
    assert tree[0]["amount"] == -50_000
    assert tree[0]["row_count"] == 2
    assert len(tree[0]["children"]) == 2


def test_build_month_tax_table_splits_privileged_and_non_privileged():
    rows = [
        {"Месяц": "Апрель", "Льгота": "Льготные проекты", "Сумма БУ": -20_000},
        {"Месяц": "Апрель", "Льгота": "Нельготные проекты", "Сумма БУ": -30_000},
    ]
    table = build_month_tax_table(rows)

    assert len(table) == 1
    assert table[0]["month"] == "Апрель"
    assert table[0]["privileged"] == -20_000
    assert table[0]["non_privileged"] == -30_000
    assert table[0]["total"] == -50_000


def test_build_other_expense_report_from_fixture_exports(tmp_path: Path):
    buh_path = tmp_path / "buh.xlsx"
    cost_path = tmp_path / "cost.xlsx"
    realization_path = tmp_path / "realization.xlsx"
    create_other_expense_buh_workbook(buh_path)
    create_cost_workbook(cost_path)
    create_realization_workbook(realization_path, document="Другой документ")

    report = build_other_expense_report(
        buh_path=buh_path,
        cost_path=cost_path,
        revenue_path=realization_path,
        projects_path=realization_path,
    )

    assert report["summary"]["row_count"] == 1
    assert report["summary"]["total_amount"] == -50_000
    assert report["summary"]["non_privileged_amount"] == -50_000
    assert report["rows"][0]["Статья"] == "Штрафы"
    assert report["rows"][0]["Месяц"] == "Апрель"
    assert report["rows"][0]["Льгота"] == TAX_BUCKET_NON_PRIVILEGED
    assert len(report["tree"]) == 1
    assert report["tree"][0]["name"] == "Штрафы"
    assert len(report["month_table"]) == 1
