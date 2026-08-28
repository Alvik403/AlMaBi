"""Поиск источника расхождения pipeline vs файл «Себестоимость НУ»."""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from almabi_excel_utils import document_match_keys, normalize_text
from almabi_export_parsers import parse_cost_nu, parse_exports
from almabi_pipeline import CostNuAllocator
from almabi_pq_common import nomenclature_key
from almabi_test_pipeline import build_test_facts


def main() -> None:
    uploads = ROOT / "uploads" / "almabi"
    paths = {
        k: sorted(uploads.glob(p + "*.xlsx"), key=lambda x: x.stat().st_mtime, reverse=True)[0]
        for k, p in [("buh", "buh-"), ("realization", "realization-"), ("cost", "cost-")]
    }
    paths["cost_nu"] = Path(r"c:\Users\Flirp\Downloads\Выгрузка - Себестоимость НУ.xlsx")

    exports = parse_exports(paths)
    facts = build_test_facts(exports).facts

    for month in ("Апрель", "Май"):
        print("\n" + "=" * 90)
        print(month)
        print("=" * 90)

        file_rows = [r for r in exports.cost_nu if r.month == month]
        file_total = sum(float(r.amount_nu or 0) for r in file_rows)

        pipe_nu = sum(f.amount_nu for f in facts if f.kpi_l1 == "Себестоимость" and f.month == month)
        orphan = sum(
            f.amount_nu
            for f in facts
            if f.kpi_l1 == "Себестоимость" and f.month == month and abs(f.amount_buh) < 0.005
        )
        matched = pipe_nu - orphan

        print(f"Файл НУ (положит.):     {file_total:>18,.2f}")
        print(f"Pipeline NU:             {pipe_nu:>18,.2f}")
        print(f"  из них orphan (buh=0): {orphan:>18,.2f}")
        print(f"  из них matched:        {matched:>18,.2f}")
        print(f"Δ pipeline + файл:       {pipe_nu + file_total:>18,.2f}")

        # Re-run allocator to see consumed vs file
        allocator = CostNuAllocator.from_rows(exports.cost_nu)
        # Simulate consumption by replaying facts - easier: compare file rows to fact orphan list

        orphan_noms: dict[tuple[str, str], float] = defaultdict(float)
        for fact in facts:
            if fact.kpi_l1 != "Себестоимость" or fact.month != month or abs(fact.amount_buh) >= 0.005:
                continue
            key = (nomenclature_key(fact.nomenclature), normalize_text(fact.contract or ""))
            orphan_noms[key] += -float(fact.amount_nu or 0)

        # File rows not represented in any fact NU (by nom+doc keys fuzzy)
        fact_nu_by_nom: dict[str, float] = defaultdict(float)
        for fact in facts:
            if fact.kpi_l1 == "Себестоимость" and fact.month == month:
                fact_nu_by_nom[nomenclature_key(fact.nomenclature)] += -float(fact.amount_nu or 0)

        file_by_nom: dict[str, float] = defaultdict(float)
        for row in file_rows:
            file_by_nom[nomenclature_key(row.nomenclature)] += float(row.amount_nu or 0)

        nom_deltas = []
        for nom in set(file_by_nom) | set(fact_nu_by_nom):
            delta = fact_nu_by_nom.get(nom, 0) - file_by_nom.get(nom, 0)
            if abs(delta) > 5000:
                nom_deltas.append((delta, nom, file_by_nom.get(nom, 0), fact_nu_by_nom.get(nom, 0)))
        nom_deltas.sort(key=lambda x: -abs(x[0]))

        print("\nТоп расхождений по номенклатуре (pipeline_pos - file_pos):")
        for delta, nom, file_v, pipe_v in nom_deltas[:15]:
            print(f"  Δ={delta:>14,.2f}  file={file_v:>16,.2f}  pipe={pipe_v:>16,.2f}  {nom[:50]}")


if __name__ == "__main__":
    main()
