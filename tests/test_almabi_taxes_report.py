from __future__ import annotations

from pathlib import Path

from almabi_taxes_report import (
    TAX_BUCKET_NON_PRIVILEGED,
    TAX_BUCKET_PRIVILEGED,
    build_taxes_hierarchy,
    build_taxes_report,
)
from tests.test_almabi_exports import (
    create_cost_workbook,
    create_profit_before_tax_buh_workbook,
    create_realization_workbook,
)


def test_build_taxes_hierarchy_groups_by_tax_bucket():
    rows = [
        {"Льгота": TAX_BUCKET_PRIVILEGED, "Налог": -20_000},
        {"Льгота": TAX_BUCKET_NON_PRIVILEGED, "Налог": -87_500},
    ]
    tree = build_taxes_hierarchy(rows)

    assert len(tree) == 2
    assert tree[0]["name"] == TAX_BUCKET_PRIVILEGED
    assert tree[0]["amount"] == -20_000
    assert tree[1]["amount"] == -87_500


def test_build_taxes_report_from_fixture_exports(tmp_path: Path):
    buh_path = tmp_path / "buh.xlsx"
    cost_path = tmp_path / "cost.xlsx"
    realization_path = tmp_path / "realization.xlsx"
    create_profit_before_tax_buh_workbook(buh_path)
    create_cost_workbook(cost_path)
    create_realization_workbook(realization_path)

    report = build_taxes_report(
        buh_path=buh_path,
        cost_path=cost_path,
        revenue_path=realization_path,
        projects_path=realization_path,
    )

    bases = report["summary"]["base_totals"]
    taxes = report["summary"]["component_totals"]
    assert report["summary"]["row_count"] >= 3
    assert bases[TAX_BUCKET_PRIVILEGED] == 1_000_000
    assert bases[TAX_BUCKET_NON_PRIVILEGED] == 400_000
    assert taxes[TAX_BUCKET_PRIVILEGED] == -20_000
    assert taxes[TAX_BUCKET_NON_PRIVILEGED] == -100_000
    assert report["summary"]["total_amount"] == -120_000
    assert len(report["tree"]) == 2
