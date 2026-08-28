"""Extract January cost NU breakdown exactly as BI summary_rows tree."""
from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from almabi_test_builder import load_test_dashboard_from_exports

MONTH = "Январь"
OUTPUT = Path.home() / "Downloads" / "Себестоимость Январь — НУ по логике BI.txt"
SECTIONS = (
    "Амортизация",
    "Аренда (прямые)",
    "Материальные затраты",
    "Общепроизводственные затраты",
    "Прочие производственные расходы",
    "ФОТ",
)


def latest(prefix: str) -> Path:
    return sorted((ROOT / "uploads" / "almabi").glob(f"{prefix}*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True)[0]


def money(v: float) -> str:
    return f"{abs(v):,.2f}".replace(",", " ")


def nu(node: dict) -> float:
    return float(node["values"]["Факт НУ"].get(MONTH, 0) or 0)


def drill_noms(node: dict) -> list[tuple[str, float]]:
    payload = ((node.get("drill") or {}).get("months") or {}).get(MONTH) or {}
    items: list[tuple[str, float]] = []
    for line in payload.get("lines") or []:
        amount = float((line.get("cost") or {}).get("nu") or 0)
        if abs(amount) >= 0.005:
            items.append((line.get("name") or "—", amount))
    items.sort(key=lambda x: -abs(x[1]))
    return items


def main() -> None:
    paths = {k: latest(k + "-") for k in ("buh", "cost", "realization", "cost_nu")}
    dash = load_test_dashboard_from_exports(paths, upload_names={k: f"{k}.xlsx" for k in paths}, logs_dir=None)
    cost = next(r for r in dash["summary_rows"] if r["name"] == "Себестоимость")

    lines: list[str] = []
    lines.append(f"СЕБЕСТОИМОСТЬ ЗА {MONTH.upper()} — КАК В BI")
    lines.append("")
    lines.append("Колонка «Факт НУ» по дереву: Себестоимость → статья → направление → группа → проект.")
    lines.append(f"Итого НУ: {money(nu(cost))} руб.")
    lines.append("")

    section_map = {ch["name"]: ch for ch in cost.get("children") or [] if ch["name"] != "Прочее"}
    order = [name for name in SECTIONS if name in section_map] + [
        name for name in section_map if name not in SECTIONS and name != "Корректировка НУ"
    ]

    for name in order:
        section = section_map[name]
        val = nu(section)
        if abs(val) < 0.005:
            continue
        lines.append(f"СТАТЬЯ: {name}")
        lines.append(f"НУ: {money(val)} руб.")
        noms = drill_noms(section)
        if noms:
            lines.append("Наименования:")
            for nom, amount in noms[:20]:
                lines.append(f"  • {nom} — {money(amount)} руб.")
        for direction in section.get("children") or []:
            dval = nu(direction)
            if abs(dval) < 0.005:
                continue
            lines.append(f"  Направление: {direction['name']} — {money(dval)} руб.")
            for nom, amount in drill_noms(direction)[:10]:
                lines.append(f"    • {nom} — {money(amount)} руб.")
        lines.append("")

    prochee = section_map.get("Прочее")
    if prochee and abs(nu(prochee)) >= 0.005:
        lines.append(f"Прочее (разница структуры и KPI): {money(nu(prochee))} руб.")
        lines.append("")

    missing = [s for s in SECTIONS if s not in section_map or abs(nu(section_map[s])) < 0.005]
    if missing:
        lines.append("Статьи с нулём за январь:")
        for s in missing:
            lines.append(f"  • {s}")

    text = "\n".join(lines)
    OUTPUT.write_text(text, encoding="utf-8")
    print(text)
    print(f"\nФайл: {OUTPUT}")


if __name__ == "__main__":
    main()
