from __future__ import annotations

from pathlib import Path

from almabi_profit_before_tax_report import (
    COMPONENT_ORDER,
    build_profit_before_tax_hierarchy,
    build_profit_before_tax_report,
)
from tests.test_almabi_exports import (
    create_cost_workbook,
    create_profit_before_tax_buh_workbook,
    create_realization_workbook,
)


def test_build_profit_before_tax_hierarchy_groups_by_component():
    rows = [
        {"Компонент": "Операционная прибыль", "Сумма БУ": 550_000},
        {"Компонент": "Прочие доходы", "Сумма БУ": 400_000},
        {"Компонент": "Прочие расходы", "Сумма БУ": -50_000},
    ]
    tree = build_profit_before_tax_hierarchy(rows)

    assert [node["name"] for node in tree] == list(COMPONENT_ORDER)
    assert tree[0]["amount"] == 550_000
    assert tree[1]["amount"] == 400_000
    assert tree[2]["amount"] == -50_000


def test_build_profit_before_tax_report_from_fixture_exports(tmp_path: Path):
    buh_path = tmp_path / "buh.xlsx"
    cost_path = tmp_path / "cost.xlsx"
    realization_path = tmp_path / "realization.xlsx"
    create_profit_before_tax_buh_workbook(buh_path)
    create_cost_workbook(cost_path)
    create_realization_workbook(realization_path)

    report = build_profit_before_tax_report(
        buh_path=buh_path,
        cost_path=cost_path,
        revenue_path=realization_path,
        projects_path=realization_path,
    )

    components = report["summary"]["component_totals"]
    assert report["summary"]["row_count"] >= 5
    assert components["Операционная прибыль"] == 550_000
    assert components["Прочие доходы"] == 400_000
    assert components["Прочие расходы"] == -50_000
    assert report["summary"]["total_amount"] == 900_000
    assert len(report["tree"]) == 3
    for name in COMPONENT_ORDER:
        assert name in components
