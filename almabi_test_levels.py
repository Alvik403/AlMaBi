from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import almabi_mock_data as mock
from almabi_mock_data import MONTHS, SCENARIOS, _MONTHS_SHORT, _attach_metrics, _month_values

LEVELS_SPEC_PATH = Path(__file__).resolve().parent / "fixtures" / "almabi_dashboard_levels.json"


def load_dashboard_levels_spec() -> list[dict[str, Any]]:
    payload = json.loads(LEVELS_SPEC_PATH.read_text(encoding="utf-8"))
    return [{"level": int(item["level"]), "name": str(item["name"]).strip()} for item in payload]


def build_tree_from_levels_spec(flat: list[dict[str, Any]]) -> list[dict[str, Any]]:
    roots: list[dict[str, Any]] = []
    stack: list[dict[str, Any]] = []
    for item in flat:
        level = item["level"]
        node: dict[str, Any] = {"name": item["name"], "level": level, "children": []}
        while stack and stack[-1]["level"] >= level:
            stack.pop()
        if stack:
            stack[-1]["children"].append(node)
        else:
            roots.append(node)
        stack.append(node)
    return roots


def _empty_month_values() -> dict[str, dict[str, int]]:
    return _month_values([0] * len(MONTHS))


def _next_id(prefix: str = "test") -> str:
    return mock._next_id(prefix)


def _build_summary_node(spec: dict[str, Any]) -> dict[str, Any]:
    children = [_build_summary_node(child) for child in spec.get("children") or []]
    return _attach_metrics(
        {
            "id": _next_id("test-node"),
            "name": spec["name"],
            "level": spec["level"],
            "values": _empty_month_values(),
            "children": children,
        }
    )


def build_test_summary_rows() -> list[dict[str, Any]]:
    mock._id_seq = 0
    tree = build_tree_from_levels_spec(load_dashboard_levels_spec())
    return [_build_summary_node(node) for node in tree]


def empty_chart_series() -> list[dict[str, Any]]:
    return [{"month": label, "value": 0} for label in _MONTHS_SHORT]
