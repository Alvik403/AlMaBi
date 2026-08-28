"""Verify davaltz placement in FOT tree."""
from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from almabi_test_builder import load_almabi_dashboard_from_exports


def _latest(prefix: str) -> Path:
    return sorted(Path("uploads/almabi").glob(f"{prefix}-*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True)[0]


def main() -> None:
    paths = {"buh": _latest("buh"), "cost": _latest("cost"), "realization": _latest("realization")}
    dashboard = load_almabi_dashboard_from_exports(
        paths, upload_names={k: v.name for k, v in paths.items()}, logs_dir=None
    )
    cost = next(r for r in dashboard["summary_rows"] if r["name"] == "Себестоимость")
    fot = next(c for c in cost["children"] if c["name"] == "ФОТ")
    march = fot["values"]["Факт БУ"]["Март"]
    print(f"ФОТ March total: {march:,.2f}")
    for child in fot.get("children") or []:
        val = child["values"]["Факт БУ"].get("Март", 0)
        if abs(val) < 0.01:
            continue
        print(f"  {child['name']}: {val:,.2f}")
        for sub in child.get("children") or []:
            sv = sub["values"]["Факт БУ"].get("Март", 0)
            if abs(sv) < 0.01:
                continue
            print(f"    {sub['name']}: {sv:,.2f}")


if __name__ == "__main__":
    main()
