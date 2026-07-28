from __future__ import annotations

from almabi_mock_data import MONTHS, SCENARIOS
from almabi_test_levels import build_test_summary_rows, build_tree_from_levels_spec, load_dashboard_levels_spec


def _max_level(node: dict) -> int:
    children = node.get("children") or []
    if not children:
        return int(node["level"])
    return max(_max_level(child) for child in children)


def _child_names(node: dict) -> list[str]:
    return [child["name"] for child in node.get("children") or []]


def _assert_all_values_zero(node: dict) -> None:
    for scenario in SCENARIOS:
        for month in MONTHS:
            assert node["values"][scenario][month] == 0
    assert node["total_fact"] == 0
    assert node["total_plan"] == 0
    assert node["percent"] == 0.0
    for child in node.get("children") or []:
        _assert_all_values_zero(child)


def test_levels_spec_builds_ten_root_kpis():
    rows = build_test_summary_rows()

    assert len(rows) == 10
    assert [row["name"] for row in rows] == [
        "Выручка",
        "Себестоимость",
        "Коммерческие расходы",
        "Управленческие расходы",
        "Операционная прибыль",
        "Прочие доходы",
        "Прочие расходы",
        "Прибыль/убыток до налогообложения",
        "Налоги",
        "Чистая прибыль",
    ]


def test_levels_spec_matches_dashboard_structure():
    rows = {row["name"]: row for row in build_test_summary_rows()}

    assert _max_level(rows["Выручка"]) == 5
    assert _child_names(rows["Выручка"]) == ["Направление"]

    cost = rows["Себестоимость"]
    assert _max_level(cost) == 5
    assert _child_names(cost) == ["Раздел"]
    assert cost["children"][0]["children"][0]["name"] == "Направление"

    assert _child_names(rows["Коммерческие расходы"]) == ["Льготные проекты", "Нельготные проекты"]
    assert _child_names(rows["Прочие доходы"]) == ["Льготные проекты", "Нельготные проекты"]
    assert rows["Прочие доходы"]["children"][0]["children"][0]["name"] == "Статья"
    assert _child_names(rows["Операционная прибыль"]) == ["Льготные проекты", "Нельготные проекты"]
    assert rows["Операционная прибыль"]["children"][0]["children"][0]["name"] == "Договор"


def test_levels_spec_has_no_numeric_data():
    for row in build_test_summary_rows():
        _assert_all_values_zero(row)
        if row.get("children"):
            assert row["expandable"] is True


def test_flat_levels_spec_parses_into_tree():
    flat = load_dashboard_levels_spec()
    tree = build_tree_from_levels_spec(flat)

    assert len(tree) == 10
    assert tree[0]["name"] == "Выручка"
    assert tree[0]["children"][0]["name"] == "Направление"
