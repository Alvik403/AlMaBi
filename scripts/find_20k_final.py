from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from almabi_pipeline import run_pipeline

LOG = Path(__file__).resolve().parent.parent / "debug-a10d6d.log"
facts = run_pipeline(
    {
        "buh": Path.home() / "Downloads" / "Выгрузка - бух.регистр (2).xlsx",
        "cost": Path.home() / "Downloads" / "Выгрузка - себестоимость (1).xlsx",
        "realization": Path.home() / "Downloads" / "Выгрузка - Реализации проекты (2).xlsx",
    }
).facts
jan = [fact for fact in facts if fact.month == "Январь"]


def find_subset(rows, target: float):
    negatives = [(round(abs(fact.amount_buh), 2), fact) for fact in rows if fact.amount_buh < 0]
    negatives.sort(key=lambda pair: pair[0], reverse=True)

    def search(index: int, remaining: float, picked: list) -> list | None:
        if abs(remaining) < 0.02:
            return picked
        if index >= len(negatives) or remaining < -0.02:
            return None
        amount, fact = negatives[index]
        with_fact = search(index + 1, remaining - amount, picked + [fact])
        if with_fact is not None:
            return with_fact
        return search(index + 1, remaining, picked)

    return search(0, target, [])


comm = [fact for fact in jan if fact.kpi_l1 == "Коммерческие расходы"]
admin = [fact for fact in jan if fact.kpi_l1 == "Управленческие расходы"]

for title, rows in ("COMM", comm), ("ADMIN", admin):
    match = find_subset(rows, 20_000)
    print(f"{title}: subset 20k =", "FOUND" if match else "not found")
    if match:
        for fact in match:
            article = (fact.expense_article or "")[:75]
            print(f"  BU={fact.amount_buh:,.2f} article={article}")

# Key finding: BU vs NU commercial split
nu_only = [f for f in comm if f.amount_buh == 0 and f.amount_nu != 0]
bu_only_total = sum(f.amount_buh for f in comm)
nu_total = sum(f.amount_nu for f in comm)
print("\nCommercial January:")
print(f"  BU total (dashboard Факт БУ): {bu_only_total:,.2f}")
print(f"  NU total (dashboard Факт НУ): {nu_total:,.2f}")
print(f"  BU-NU gap: {bu_only_total - nu_total:,.2f}")
print(f"  NU-only lines (BU=0): {len(nu_only)} lines, NU sum {sum(f.amount_nu for f in nu_only):,.2f}")

# Operating scenarios
rev = 46_719_878.72
cost_bu = -40_442_360.16
comm_bu = -315_338.84
comm_nu = -123_808.58
admin_bu = -73_147_369.93
print("\nOperating January:")
print(f"  BU formula: {rev + cost_bu + comm_bu + admin_bu:,.2f}")
print(f"  if comm NU instead of BU: {rev + cost_bu + comm_nu + admin_bu:,.2f}")
print(f"  user manual target: {-67_165_190.21:,.2f}")
print(f"  gap vs BU operating: {-67_185_190.21 - (-67_165_190.21):,.2f}")

payload = {
    "sessionId": "a10d6d",
    "runId": "find-20k-final",
    "hypothesisId": "comm-bu-nu-split",
    "location": "scripts/find_20k_final.py",
    "message": "20k gap root cause January v2",
    "data": {
        "month": "Январь",
        "scenario_matching_screenshot": "Факт БУ",
        "bu_operating": -67185190.21,
        "user_manual_sum": -67165190.21,
        "gap": -20000.0,
        "comm_bu": -315338.84,
        "comm_nu": -123808.58,
        "comm_bu_nu_gap": -191530.26,
        "nu_only_comm_lines": len(nu_only),
        "nu_only_comm_nu_sum": sum(f.amount_nu for f in nu_only),
    },
    "timestamp": int(time.time() * 1000),
}
with LOG.open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
