"""One-off verification of PQ cost section mapping (debug session 099d59)."""
from __future__ import annotations

import json
import time
from pathlib import Path

from almabi_export_parsers import classify_cost_section_pq

OLD_MAP_ACCOUNT_20 = {
    "Сырье и материалы": "Материальные затраты",
    "Прочие производственные расходы": "Материальные затраты",
    "Оплата труда": "ФОТ",
    "Страховые взносы": "ФОТ",
    "Аренда": "Аренда (прямые)",
    "Амортизация": "Амортизация",
    "Возвратные отходы": "Прочие производственные расходы",
    "Полуфабрикаты производимые в процессе": "Прочие производственные расходы",
}

CASES: list[tuple[str | None, str | None]] = [
    (None, None),
    ("", ""),
    ("Сырье и материалы", "20"),
    ("Прочие производственные расходы", "20"),
    ("Оплата труда", "20"),
    ("Страховые взносы", "20"),
    ("Аренда", "20"),
    ("Амортизация", "20"),
    ("Возвратные отходы", "20"),
    ("Полуфабрикаты производимые в процессе", "20"),
    ("Прочее", "20"),
    ("Сырье и материалы", "10"),
]


def _old_section(calc_article: str | None, account: str | None) -> str:
    article = (calc_article or "Сырье и материалы").strip()
    account_value = (account or "20").strip()
    if account_value != "20":
        return "Прочие производственные расходы"
    return OLD_MAP_ACCOUNT_20.get(article, "Прочие производственные расходы")


def main() -> None:
    log_path = Path("debug-099d59.log")
    if log_path.exists():
        log_path.unlink()

    print("=== Сверка правил (статья | счёт | было | стало) ===")
    changed_count = 0
    for calc_article, account in CASES:
        new_section = classify_cost_section_pq(calc_article, account)
        old_section = _old_section(calc_article, account)
        article_label = calc_article if calc_article not in (None, "") else "NULL->Сырье и материалы"
        account_label = account if account not in (None, "") else "NULL->20"
        changed = old_section != new_section
        if changed:
            changed_count += 1
        mark = " *" if changed else ""
        print(f"{article_label} | {account_label} | {old_section} | {new_section}{mark}")

        payload = {
            "sessionId": "099d59",
            "location": "scripts/verify_cost_section_rules.py",
            "message": "spec case",
            "data": {
                "calc_article": calc_article,
                "account": account,
                "old": old_section,
                "new": new_section,
                "changed": changed,
            },
            "timestamp": int(time.time() * 1000),
            "hypothesisId": "A",
            "runId": "cost-section-fix",
        }
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    print(f"\nИзменено правил: {changed_count} из {len(CASES)}")


if __name__ == "__main__":
    main()
