from __future__ import annotations

from collections import defaultdict
from typing import Any

from almabi_excel_utils import tax_bucket
from almabi_pipeline import Fact


_CARD_META = {
    "Льготные проекты": ("Реализация льгота", "blue"),
    "Нельготные проекты": ("Реализация нельгота", "rose"),
}


def build_contractor_details(facts: list[Fact]) -> list[dict[str, Any]]:
    details: list[dict[str, Any]] = []
    for fact in facts:
        if fact.kpi_l1 != "Выручка":
            continue
        details.append(
            {
                "contractor": fact.contractor or "Не указан",
                "tax_bucket": tax_bucket(fact.tax_type),
                "direction": fact.direction,
                "project_group": fact.project_group,
                "project": fact.project,
                "contract": fact.contract,
                "month": fact.month,
                "amount": round(abs(fact.amount_buh)),
            }
        )
    return details


def build_contractor_cards(details: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not details:
        return []

    cards: list[dict[str, Any]] = []
    for bucket_name, (title, accent) in _CARD_META.items():
        grouped: dict[str, float] = defaultdict(float)
        for item in details:
            if item["tax_bucket"] != bucket_name:
                continue
            grouped[item["contractor"]] += float(item["amount"])

        if not grouped:
            continue

        rows = [
            {
                "name": contractor,
                "value": round(amount),
                "color": "green" if accent == "blue" else "rose",
            }
            for contractor, amount in sorted(grouped.items(), key=lambda pair: pair[1], reverse=True)
        ]
        cards.append(
            {
                "title": title,
                "accent": accent,
                "total": sum(row["value"] for row in rows),
                "rows": rows,
            }
        )
    return cards


def contractor_details_from_cards(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    details: list[dict[str, Any]] = []
    for card in cards:
        bucket = "Льготные проекты" if "льгот" in card["title"].casefold() else "Нельготные проекты"
        for row in card.get("rows", []):
            details.append(
                {
                    "contractor": row["name"],
                    "tax_bucket": bucket,
                    "direction": "",
                    "project_group": "",
                    "project": "",
                    "contract": "",
                    "month": "",
                    "amount": int(row["value"]),
                }
            )
    return details
