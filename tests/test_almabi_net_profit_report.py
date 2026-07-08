from __future__ import annotations

from pathlib import Path

from almabi_net_profit_report import (
    COMPONENT_ORDER,
    build_net_profit_hierarchy,
    build_net_profit_report,
)
from tests.test_almabi_exports import (
    create_cost_workbook,
    create_profit_before_tax_buh_workbook,
    create_realization_workbook,
)


def test_build_net_profit_hierarchy_groups_by_component():
    rows = [
        {"Компонент": "Прибыль/убыток до налогообложения", "Сумма": 900_000},
        {"Компонент": "Налоги", "Сумма": -132_500},
    ]
    tree = build_net_profit_hierarchy(rows)

    assert [node["name"] for node in tree] == list(COMPONENT_ORDER)
    assert tree[0]["amount"] == 900_000
    assert tree[1]["amount"] == -132_500


def test_build_net_profit_report_from_fixture_exports(tmp_path: Path):
    buh_path = tmp_path / "buh.xlsx"
    cost_path = tmp_path / "cost.xlsx"
    realization_path = tmp_path / "realization.xlsx"
    create_profit_before_tax_buh_workbook(buh_path)
    create_cost_workbook(cost_path)
    create_realization_workbook(realization_path)

    report = build_net_profit_report(
        buh_path=buh_path,
        cost_path=cost_path,
        revenue_path=realization_path,
        projects_path=realization_path,
    )

    components = report["summary"]["component_totals"]
    assert report["summary"]["row_count"] >= 5
    assert components["Прибыль/убыток до налогообложения"] == 900_000
    assert components["Налоги"] == -120_000
    assert report["summary"]["total_amount"] == 780_000
    assert len(report["tree"]) == 2
