from __future__ import annotations

from pathlib import Path

from almabi_operating_profit_report import (
    COMPONENT_ORDER,
    build_operating_profit_hierarchy,
    build_operating_profit_report,
)
from tests.test_almabi_exports import create_buh_workbook, create_cost_workbook, create_realization_workbook


def test_build_operating_profit_hierarchy_groups_by_component():
    rows = [
        {"Компонент": "Выручка", "Сумма БУ": 1_000_000},
        {"Компонент": "Себестоимость", "Сумма БУ": -400_000},
        {"Компонент": "Коммерческие расходы", "Сумма БУ": -50_000},
    ]
    tree = build_operating_profit_hierarchy(rows)

    assert [node["name"] for node in tree] == ["Выручка", "Себестоимость", "Коммерческие расходы"]
    assert tree[0]["amount"] == 1_000_000
    assert tree[1]["amount"] == -400_000


def test_build_operating_profit_report_from_fixture_exports(tmp_path: Path):
    buh_path = tmp_path / "buh.xlsx"
    cost_path = tmp_path / "cost.xlsx"
    realization_path = tmp_path / "realization.xlsx"
    create_buh_workbook(buh_path)
    create_cost_workbook(cost_path)
    create_realization_workbook(realization_path)

    report = build_operating_profit_report(
        buh_path=buh_path,
        cost_path=cost_path,
        revenue_path=realization_path,
        projects_path=realization_path,
    )

    components = report["summary"]["component_totals"]
    assert report["summary"]["row_count"] >= 3
    assert components["Выручка"] == 1_000_000
    assert components["Себестоимость"] == -400_000
    assert components["Коммерческие расходы"] == -50_000
    assert components["Управленческие расходы"] == 0.0
    assert report["summary"]["total_amount"] == 550_000
    assert len(report["tree"]) == 3
    for name in COMPONENT_ORDER:
        assert name in components
