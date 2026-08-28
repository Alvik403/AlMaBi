"""Pinpoint net gap: buh facts vs PQ structure by document prefix."""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from almabi_dashboard_builder import build_cost_structure_facts_from_pq_rows
from almabi_excel_utils import document_match_keys, month_name, normalize_text, parse_date_from_text
from almabi_pq_cost import build_pq_cost_table
from almabi_test_pipeline import run_test_pipeline

MONTH = "Март"


def _latest(prefix: str) -> Path:
    return sorted(Path("uploads/almabi").glob(f"{prefix}-*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True)[0]


def main() -> None:
    paths = {"buh": _latest("buh"), "cost": _latest("cost"), "realization": _latest("realization")}
    pipeline = run_test_pipeline(paths, logs_dir=None, write_audit=False)
    pq = pipeline.pq_cost_rows or build_pq_cost_table(paths["cost"], projects_path=paths["realization"])
    structure = build_cost_structure_facts_from_pq_rows(pq)
    buh = [f for f in pipeline.result.facts if f.kpi_l1 == "Себестоимость" and f.month == MONTH]

    buh_by_doc: dict[str, float] = defaultdict(float)
    for f in buh:
        # facts don't store document - aggregate by nomenclature only for now
        buh_by_doc[(f.nomenclature or "").casefold()] += f.amount_buh

    struct_by_nom: dict[str, float] = defaultdict(float)
    for f in structure:
        if f.month != MONTH:
            continue
        struct_by_nom[(f.nomenclature or "").casefold()] += f.amount_buh

    all_noms = set(buh_by_doc) | set(struct_by_nom)
    deltas: list[tuple[float, str, float, float]] = []
    for nom in all_noms:
        b = buh_by_doc.get(nom, 0.0)
        s = struct_by_nom.get(nom, 0.0)
        d = b - s
        if abs(d) > 0.01:
            deltas.append((d, nom, b, s))
    deltas.sort(key=lambda x: -abs(x[0]))

    print(f"Net gap {MONTH}: {sum(buh_by_doc.values()) - sum(struct_by_nom.values()):,.2f}")
    print(f"Nomenclatures with delta: {len(deltas)}")
    print("Top deltas (buh − structure):")
    running = 0.0
    for d, nom, b, s in deltas[:15]:
        running += d
        print(f"  {d:>14,.2f}  cum={running:>14,.2f}  buh={b:>14,.2f} struct={s:>14,.2f}")
        print(f"    {nom[:80]}")

    # Document-level from PQ vs buh is harder; show small residual-only noms
    small = [(d, nom) for d, nom, _, _ in deltas if abs(d) < 1000]
    print(f"\nSmall deltas (<1000): {len(small)} lines, sum={sum(d for d,_ in small):,.2f}")


if __name__ == "__main__":
    main()
