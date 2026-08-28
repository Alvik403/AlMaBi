from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from almabi_dashboard_builder import _build_summary_rows
from almabi_export_parsers import parse_exports
from almabi_pipeline import run_pipeline


def _latest(prefix: str) -> Path:
    return sorted(Path("uploads/almabi").glob(f"{prefix}-*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True)[0]


def main() -> None:
    paths = {"buh": _latest("buh"), "cost": _latest("cost"), "realization": _latest("realization")}
    exports = parse_exports(paths)
    result = run_pipeline(exports)
    rows = _build_summary_rows(result.facts)
    cost = next(x for x in rows if x["name"] == "Себестоимость")
    print("Main dashboard L2:")
    for child in cost["children"]:
        print(f"  {child['name']!r} total={child.get('total_fact', 0):,.2f}")


if __name__ == "__main__":
    main()
