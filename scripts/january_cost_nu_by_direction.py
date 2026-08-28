"""Январь: себестоимость по направлениям и статьям (НУ) с наименованиями."""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from almabi_dashboard_builder import COST_STRUCTURE_SECTIONS, build_unified_cost_structure_facts
from almabi_pq_common import is_black_metal_scrap_nomenclature
from almabi_test_builder import load_test_dashboard_from_exports
from almabi_test_pipeline import run_test_pipeline

MONTH = "Январь"
OUTPUT = Path.home() / "Downloads" / "Себестоимость Январь — НУ по направлениям и статьям.txt"


def _latest(prefix: str) -> Path:
    return sorted((ROOT / "uploads" / "almabi").glob(f"{prefix}*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True)[0]


def _money(value: float) -> str:
    return f"{abs(value):,.2f}".replace(",", " ")


def _normalize_section(section: str) -> str:
    text = (section or "").strip()
    if not text:
        return "Без статьи"
    aliases = {
        "Аренда": "Аренда (прямые)",
        "ОПЗ": "Общепроизводственные затраты",
    }
    return aliases.get(text, text)


def _section_order(section: str) -> tuple[int, str]:
    try:
        return (COST_STRUCTURE_SECTIONS.index(section), section)
    except ValueError:
        return (999, section)


def _build_from_unified_facts(facts) -> dict[str, dict[str, dict[str, float]]]:
    grouped: dict[str, dict[str, dict[str, float]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
    for fact in facts:
        if fact.month != MONTH or fact.kpi_l1 != "Себестоимость":
            continue
        if is_black_metal_scrap_nomenclature(fact.nomenclature):
            continue
        direction = (fact.direction or "").strip() or "Без направления"
        section = _normalize_section(fact.cost_section)
        label = (fact.nomenclature or fact.expense_article or fact.contract or "—").strip()
        grouped[direction][section][label] += float(fact.amount_nu or 0)
    return grouped


def _build_from_dashboard(cost_node) -> dict[str, dict[str, dict[str, float]]]:
    grouped: dict[str, dict[str, dict[str, float]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))

    def walk(node, path: list[str]) -> None:
        nu = float(node["values"]["Факт НУ"].get(MONTH, 0) or 0)
        if abs(nu) < 0.005:
            return
        if len(path) == 1:
            direction = path[0]
            section = _normalize_section(node["name"])
            grouped[direction][section]["(сумма по направлению)"] += nu
        elif len(path) == 2:
            direction, section_name = path[0], _normalize_section(path[1])
            label = node["name"]
            grouped[direction][section_name][label] += nu
        elif len(path) >= 3:
            direction, section_name = path[0], _normalize_section(path[1])
            label = node["name"]
            grouped[direction][section_name][label] += nu
        for child in node.get("children") or []:
            walk(child, path + [node["name"]])

    for child in cost_node.get("children") or []:
        walk(child, [])

    return grouped


def _render(grouped: dict[str, dict[str, dict[str, float]]], total_nu: float) -> list[str]:
    lines: list[str] = []
    lines.append(f"СЕБЕСТОИМОСТЬ ЗА {MONTH.upper()} — ПО НАПРАВЛЕНИЯМ И СТАТЬЯМ (НУ)")
    lines.append("")
    lines.append(f"Итого НУ: {_money(total_nu)} руб.")
    lines.append("")

    for direction in sorted(grouped, key=lambda name: -abs(sum(sum(items.values()) for items in grouped[name].values()))):
        dir_total = sum(sum(items.values()) for items in grouped[direction].values())
        lines.append(f"НАПРАВЛЕНИЕ: {direction}")
        lines.append(f"Итого по направлению: {_money(dir_total)} руб.")
        lines.append("")

        sections = grouped[direction]
        for section in sorted(sections, key=lambda name: _section_order(name)):
            section_total = sum(sections[section].values())
            if abs(section_total) < 0.005:
                continue
            lines.append(f"  {section}: {_money(section_total)} руб.")
            for label, amount in sorted(sections[section].items(), key=lambda item: -abs(item[1])):
                if abs(amount) < 0.005:
                    continue
                if label == "(сумма по направлению)":
                    continue
                lines.append(f"    • {label} — {_money(amount)} руб.")
            lines.append("")

        lines.append("-" * 72)
        lines.append("")

    missing_sections = [name for name in COST_STRUCTURE_SECTIONS if all(name not in sections for sections in grouped.values())]
    if missing_sections:
        lines.append("СТАТЬИ БЕЗ СУММ ЗА ЯНВАРЬ (НУ = 0):")
        for section in missing_sections:
            lines.append(f"  • {section} — 0,00 руб.")
        lines.append("")

    return lines


def main() -> None:
    paths = {
        "buh": _latest("buh"),
        "cost": _latest("cost"),
        "realization": _latest("realization"),
        "cost_nu": _latest("cost_nu"),
    }
    pipeline = run_test_pipeline(paths, logs_dir=None, write_audit=False)
    dash = load_test_dashboard_from_exports(
        paths,
        upload_names={k: v.name for k, v in paths.items()},
        logs_dir=None,
    )
    cost_node = next(row for row in dash["summary_rows"] if row["name"] == "Себестоимость")
    total_nu = float(cost_node["values"]["Факт НУ"].get(MONTH, 0) or 0)

    cost_buh = [
        fact
        for fact in pipeline.result.facts
        if fact.kpi_l1 == "Себестоимость" and not is_black_metal_scrap_nomenclature(fact.nomenclature)
    ]
    unified = build_unified_cost_structure_facts(cost_buh, pipeline.pq_cost_rows or [])
    grouped = _build_from_unified_facts(unified)

    if not grouped:
        grouped = _build_from_dashboard(cost_node)

    lines = _render(grouped, total_nu)
    text = "\n".join(lines)
    OUTPUT.write_text(text, encoding="utf-8")
    print(text)
    print(f"\nФайл сохранён: {OUTPUT}")


if __name__ == "__main__":
    main()
