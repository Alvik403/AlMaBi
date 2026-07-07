from __future__ import annotations

from pathlib import Path

from almabi_other_income_report import (
    TAX_BUCKET_NON_PRIVILEGED,
    build_month_tax_table,
    build_other_income_hierarchy,
    build_other_income_report,
)
from tests.test_almabi_exports import (
    create_cost_workbook,
    create_other_income_buh_workbook,
    create_realization_workbook,
)


def test_build_other_income_hierarchy_groups_by_article_and_document():
    rows = [
        {
            "Статья": "Проценты",
            "Документ": "Док 1",
            "Сумма БУ": 250_000,
        },
        {
            "Статья": "Проценты",
            "Документ": "Док 2",
            "Сумма БУ": 150_000,
        },
    ]
    tree = build_other_income_hierarchy(rows)

    assert len(tree) == 1
    assert tree[0]["name"] == "Проценты"
    assert tree[0]["amount"] == 400_000
    assert tree[0]["row_count"] == 2
    assert len(tree[0]["children"]) == 2


def test_build_month_tax_table_splits_privileged_and_non_privileged():
    rows = [
        {"Месяц": "Март", "Льгота": "Льготные проекты", "Сумма БУ": 120_000},
        {"Месяц": "Март", "Льгота": "Нельготные проекты", "Сумма БУ": 280_000},
    ]
    table = build_month_tax_table(rows)

    assert len(table) == 1
    assert table[0]["month"] == "Март"
    assert table[0]["privileged"] == 120_000
    assert table[0]["non_privileged"] == 280_000
    assert table[0]["total"] == 400_000


def test_build_other_income_report_from_fixture_exports(tmp_path: Path):
    buh_path = tmp_path / "buh.xlsx"
    cost_path = tmp_path / "cost.xlsx"
    realization_path = tmp_path / "realization.xlsx"
    create_other_income_buh_workbook(buh_path)
    create_cost_workbook(cost_path)
    create_realization_workbook(realization_path, document="Другой документ")

    report = build_other_income_report(
        buh_path=buh_path,
        cost_path=cost_path,
        revenue_path=realization_path,
        projects_path=realization_path,
    )

    assert report["summary"]["row_count"] == 1
    assert report["summary"]["total_amount"] == 400_000
    assert report["summary"]["non_privileged_amount"] == 400_000
    assert report["rows"][0]["Статья"] == "Проценты полученные"
    assert report["rows"][0]["Месяц"] == "Март"
    assert report["rows"][0]["Льгота"] == TAX_BUCKET_NON_PRIVILEGED
    assert len(report["tree"]) == 1
    assert report["tree"][0]["name"] == "Проценты полученные"
    assert len(report["month_table"]) == 1
