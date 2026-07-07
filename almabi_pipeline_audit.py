from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from almabi_bi_paths import fact_bi_path
from almabi_export_parsers import BuhRow
from almabi_pipeline import Fact

TRACKED_SECTIONS = frozenset(
    {
        "Выручка",
        "Себестоимость",
        "Коммерческие расходы",
        "Управленческие расходы",
        "Прочие доходы",
        "Прочие расходы",
    }
)

PRIMARY_SECTIONS = ("Выручка", "Себестоимость")
OTHER_SECTIONS = tuple(section for section in TRACKED_SECTIONS if section not in PRIMARY_SECTIONS)


def _amount_key(value: float) -> float:
    return float(value or 0)


def _fact_fingerprint(fact: Fact) -> tuple[Any, ...]:
    return (
        fact.kpi_l1,
        fact.month,
        fact.nomenclature.casefold(),
        fact.expense_article.casefold(),
        fact.direction.casefold(),
        fact.project_group.casefold(),
        fact.project.casefold(),
        fact.contract.casefold(),
        _amount_key(fact.amount_buh),
    )


def _fact_cross_section_key(fact: Fact) -> tuple[Any, ...]:
    return (
        fact.month,
        fact.nomenclature.casefold(),
        fact.expense_article.casefold(),
        _amount_key(fact.amount_buh),
    )


def _fact_occurrence_payload(fact: Fact) -> dict[str, Any]:
    return {
        "kpi_l1": fact.kpi_l1,
        "month": fact.month,
        "amount_buh": fact.amount_buh,
        "amount_nu": fact.amount_nu,
        "nomenclature": fact.nomenclature,
        "expense_article": fact.expense_article,
        "contract": fact.contract,
        "direction": fact.direction,
        "tax_type": fact.tax_type,
        "bi_path": fact_bi_path(fact),
    }


def _buh_row_fingerprint(row: BuhRow) -> tuple[Any, ...]:
    return (
        row.document,
        row.account_dt,
        row.account_kt,
        row.month,
        _amount_key(row.amount_buh),
        row.nomenclature_kt.casefold(),
    )


@dataclass
class PipelineAuditLog:
    detail: bool = True
    run_id: str = field(default_factory=lambda: uuid4().hex[:12])
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    section_lines: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    fallback_lines: list[dict[str, Any]] = field(default_factory=list)
    duplicate_buh_rows: list[dict[str, Any]] = field(default_factory=list)
    duplicate_facts: list[dict[str, Any]] = field(default_factory=list)
    cross_section_overlaps: list[dict[str, Any]] = field(default_factory=list)
    section_counts: dict[str, int] = field(default_factory=dict)

    @property
    def revenue_lines(self) -> list[dict[str, Any]]:
        return self.section_lines.get("Выручка", [])

    @property
    def cost_lines(self) -> list[dict[str, Any]]:
        return self.section_lines.get("Себестоимость", [])

    def log_buh_line(
        self,
        *,
        section: str,
        row: BuhRow,
        main_section: str | None,
        amount_buh: float,
        amount_nu: float,
        cost_match: dict[str, Any] | None,
        rev_match: dict[str, Any] | None,
        analytics: dict[str, str],
        nomenclature: str,
    ) -> None:
        if not self.detail:
            return
        if section not in TRACKED_SECTIONS:
            return

        entry = {
            "source": "buh_register",
            "section": section,
            "main_section": main_section,
            "document": row.document,
            "month": row.month,
            "account_dt": row.account_dt,
            "account_kt": row.account_kt,
            "nomenclature_kt": row.nomenclature_kt,
            "nomenclature_resolved": nomenclature,
            "amount_buh": amount_buh,
            "amount_nu": amount_nu,
            "expense_article": row.expense_article,
            "tax_type": row.tax_type,
            "cost_join": cost_match,
            "realization_join": rev_match,
            "analytics": analytics,
        }
        self.section_lines.setdefault(section, []).append(entry)

    def log_fallback_line(self, entry: dict[str, Any]) -> None:
        if not self.detail:
            return
        self.fallback_lines.append(entry)

    def record_fact(self, fact: Fact) -> None:
        self.section_counts[fact.kpi_l1] = self.section_counts.get(fact.kpi_l1, 0) + 1

    def analyze_duplicates(self, facts: list[Fact], buh_rows: list[BuhRow]) -> None:
        self._analyze_buh_duplicates(buh_rows)
        self._analyze_fact_duplicates(facts)
        self._analyze_cross_section_overlaps(facts)

    def _analyze_buh_duplicates(self, buh_rows: list[BuhRow]) -> None:
        grouped: dict[tuple[Any, ...], list[BuhRow]] = defaultdict(list)
        for row in buh_rows:
            grouped[_buh_row_fingerprint(row)].append(row)

        for fingerprint, rows in grouped.items():
            if len(rows) < 2:
                continue
            self.duplicate_buh_rows.append(
                {
                    "fingerprint": {
                        "document": fingerprint[0],
                        "account_dt": fingerprint[1],
                        "account_kt": fingerprint[2],
                        "month": fingerprint[3],
                        "amount_buh": fingerprint[4],
                        "nomenclature_kt": fingerprint[5],
                    },
                    "count": len(rows),
                    "sections": sorted(
                        {
                            section
                            for section in (
                                self._section_label(row.account_dt, row.account_kt) for row in rows
                            )
                            if section
                        }
                    ),
                }
            )

    @staticmethod
    def _section_label(account_dt: str, account_kt: str) -> str | None:
        from almabi_export_parsers import classify_buh_section

        return classify_buh_section(account_dt, account_kt)

    def _analyze_fact_duplicates(self, facts: list[Fact]) -> None:
        grouped: dict[tuple[Any, ...], list[Fact]] = defaultdict(list)
        for fact in facts:
            grouped[_fact_fingerprint(fact)].append(fact)

        for fingerprint, items in grouped.items():
            if len(items) < 2:
                continue
            self.duplicate_facts.append(
                {
                    "fingerprint": {
                        "kpi_l1": fingerprint[0],
                        "month": fingerprint[1],
                        "nomenclature": fingerprint[2],
                        "expense_article": fingerprint[3],
                        "direction": fingerprint[4],
                        "project_group": fingerprint[5],
                        "project": fingerprint[6],
                        "contract": fingerprint[7],
                        "amount_buh": fingerprint[8],
                    },
                    "count": len(items),
                    "sources": sorted({item.kpi_l1 for item in items}),
                    "occurrences": [_fact_occurrence_payload(item) for item in items],
                    "bi_paths": sorted({fact_bi_path(item) for item in items}),
                    "extra_in_bi": len(items) - 1,
                }
            )

    def _analyze_cross_section_overlaps(self, facts: list[Fact]) -> None:
        grouped: dict[tuple[Any, ...], list[Fact]] = defaultdict(list)
        for fact in facts:
            if not fact.nomenclature and not fact.expense_article:
                continue
            grouped[_fact_cross_section_key(fact)].append(fact)

        for key, items in grouped.items():
            sections = {fact.kpi_l1 for fact in items}
            if len(sections) < 2:
                continue
            self.cross_section_overlaps.append(
                {
                    "month": key[0],
                    "nomenclature": items[0].nomenclature,
                    "expense_article": items[0].expense_article,
                    "amount_buh": key[3],
                    "sections": sorted(sections),
                    "count": len(items),
                    "documents": sorted(
                        {fact.contract or fact.nomenclature for fact in items if fact.contract or fact.nomenclature}
                    )[:5],
                    "occurrences": [_fact_occurrence_payload(fact) for fact in items],
                    "bi_paths_by_section": {
                        section: sorted({fact_bi_path(fact) for fact in items if fact.kpi_l1 == section})
                        for section in sorted(sections)
                    },
                }
            )

    def to_dict(self) -> dict[str, Any]:
        section_line_counts = {section: len(lines) for section, lines in sorted(self.section_lines.items())}
        return {
            "run_id": self.run_id,
            "created_at": self.created_at,
            "summary": {
                "revenue_lines": len(self.revenue_lines),
                "cost_lines": len(self.cost_lines),
                "other_section_lines": {
                    section: section_line_counts.get(section, 0) for section in OTHER_SECTIONS
                },
                "fallback_lines": len(self.fallback_lines),
                "duplicate_buh_groups": len(self.duplicate_buh_rows),
                "duplicate_fact_groups": len(self.duplicate_facts),
                "cross_section_overlaps": len(self.cross_section_overlaps),
                "section_counts": dict(sorted(self.section_counts.items())),
                "section_line_counts": section_line_counts,
            },
            "section_lines": dict(sorted(self.section_lines.items())),
            "revenue_lines": self.revenue_lines,
            "cost_lines": self.cost_lines,
            "fallback_lines": self.fallback_lines,
            "duplicate_buh_rows": self.duplicate_buh_rows,
            "duplicate_facts": self.duplicate_facts,
            "cross_section_overlaps": self.cross_section_overlaps,
        }

    def write_report(self, logs_dir: Path) -> Path:
        target_dir = logs_dir / "almabi_test"
        target_dir.mkdir(parents=True, exist_ok=True)

        report_path = target_dir / f"audit-{self.run_id}.json"
        latest_path = target_dir / "audit-latest.json"
        payload = self.to_dict()

        encoded = json.dumps(payload, ensure_ascii=False, indent=2)
        report_path.write_text(encoded, encoding="utf-8")
        latest_path.write_text(encoded, encoding="utf-8")
        return report_path


def _match_payload_cost(row: Any | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "document": row.document,
        "nomenclature": row.nomenclature,
        "amount": row.amount,
        "direction": row.direction,
        "project_group": row.project_group,
        "project": row.project,
        "cost_section": row.cost_section,
        "contract": row.contract,
    }


def _match_payload_realization(row: Any | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "document": row.document,
        "nomenclature": row.nomenclature,
        "revenue": row.revenue,
        "direction": row.direction,
        "project_group": row.project_group,
        "project": row.project,
        "contract": row.contract,
    }
