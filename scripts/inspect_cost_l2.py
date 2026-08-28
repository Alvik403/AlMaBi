"""Inspect cost L2 children."""
from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from almabi_test_builder import load_almabi_dashboard_from_exports


def _latest(prefix: str) -> Path:
    return sorted(
        Path("uploads/almabi").glob(f"{prefix}-*.xlsx"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )[0]


def main() -> None:
    paths = {
        "buh": _latest("buh"),
        "cost": _latest("cost"),
        "realization": _latest("realization"),
    }
    dashboard = load_almabi_dashboard_from_exports(
        paths, upload_names={k: v.name for k, v in paths.items()}, logs_dir=None
    )
    cost = next(r for r in dashboard["summary_rows"] if r["name"] == "Себестоимость")
    print("L2 children:")
    for child in cost["children"]:
        total = child.get("total_fact", 0)
        march = child["values"]["Факт БУ"].get("Март", 0)
        print(
            f"  {child['name']!r}: total={total:,.2f} march={march:,.2f} "
            f"expandable={child.get('expandable')}"
        )


if __name__ == "__main__":
    main()
