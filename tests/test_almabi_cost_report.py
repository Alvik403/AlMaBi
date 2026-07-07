from __future__ import annotations

from pathlib import Path

from almabi_cost_report import (
    TAX_BUCKET_NON_PRIVILEGED,
    TAX_BUCKET_PRIVILEGED,
    build_cost_hierarchy,
    build_cost_report,
    build_month_tax_table,
)
from tests.test_almabi_exports import create_buh_workbook, create_cost_workbook, create_realization_workbook


def test_build_cost_hierarchy_groups_by_analytics():
    rows = [
        {
            "Направление": "Услуги",
            "Группа проектов": "Обслуживание",
            "Проект": "Проект А",
            "Документ": "Док 1",
            "Сумма БУ": 250_000,
        },
        {
            "Направление": "Услуги",
            "Группа проектов": "Обслуживание",
            "Проект": "Проект А",
            "Документ": "Док 2",
            "Сумма БУ": 150_000,
        },
    ]
    tree = build_cost_hierarchy(rows)

    assert len(tree) == 1
    assert tree[0]["name"] == "Услуги"
    assert tree[0]["amount"] == 400_000
    assert tree[0]["row_count"] == 2
    project = tree[0]["children"][0]["children"][0]
    assert project["name"] == "Проект А"
    assert project["amount"] == 400_000
    assert len(project["children"]) == 2


def test_build_month_tax_table_splits_privileged_and_non_privileged():
    rows = [
        {"Месяц": "Январь", "Льгота": TAX_BUCKET_PRIVILEGED, "Сумма БУ": 120_000},
        {"Месяц": "Январь", "Льгота": TAX_BUCKET_NON_PRIVILEGED, "Сумма БУ": 280_000},
        {"Месяц": "Февраль", "Льгота": TAX_BUCKET_NON_PRIVILEGED, "Сумма БУ": 50_000},
    ]
    table = build_month_tax_table(rows)

    assert len(table) == 2
    assert table[0]["month"] == "Январь"
    assert table[0]["privileged"] == 120_000
    assert table[0]["non_privileged"] == 280_000
    assert table[0]["total"] == 400_000
    assert table[1]["month"] == "Февраль"
    assert table[1]["non_privileged"] == 50_000


def test_build_cost_report_from_fixture_exports(tmp_path: Path):
    buh_path = tmp_path / "buh.xlsx"
    cost_path = tmp_path / "cost.xlsx"
    realization_path = tmp_path / "realization.xlsx"
    create_buh_workbook(buh_path)
    create_cost_workbook(cost_path)
    create_realization_workbook(realization_path)

    report = build_cost_report(
        buh_path=buh_path,
        cost_path=cost_path,
        revenue_path=realization_path,
        projects_path=realization_path,
    )

    assert report["summary"]["row_count"] >= 1
    assert report["summary"]["total_amount"] == -400_000
    assert report["summary"]["non_privileged_amount"] == -400_000
    assert report["rows"][0]["Направление"] == "Услуги"
    assert report["rows"][0]["Месяц"] == "Январь"
    assert report["rows"][0]["Льгота"] == TAX_BUCKET_NON_PRIVILEGED
    assert len(report["tree"]) >= 1
    assert len(report["tree_by_tax"]) >= 1
    assert len(report["tree_by_month"]) >= 1
    assert len(report["month_table"]) >= 1
