"""Shared chart UI helpers (compact money, cost-structure anomaly logic)."""

from __future__ import annotations

from typing import Any

ANOMALY_TOTAL_MEDIAN_MULTIPLIER = 3.0
ANOMALY_SECTION_SHARE_THRESHOLD = 70.0


def format_compact_ru(rubles: float | int | None, *, decimals: int | None = None) -> str:
    """Format ruble amounts as compact ru-RU labels: тыс / млн / млрд."""
    num = float(rubles or 0)
    abs_n = abs(num)
    sign = "\u2212" if num < 0 else ""

    def pick_decimals(scaled: float) -> int:
        if decimals is not None:
            return decimals
        return 1 if abs(scaled) < 100 else 0

    def fmt(scaled: float, suffix: str) -> str:
        d = pick_decimals(scaled)
        formatted = f"{scaled:,.{d}f}".replace(",", "\u00a0").replace(".", ",")
        return f"{sign}{formatted} {suffix}"

    if abs_n >= 1_000_000_000:
        return fmt(abs_n / 1_000_000_000, "млрд")
    if abs_n >= 1_000_000:
        return fmt(abs_n / 1_000_000, "млн")
    if abs_n >= 1_000:
        return fmt(abs_n / 1_000, "тыс")
    d = pick_decimals(abs_n)
    formatted = f"{abs_n:,.{d}f}".replace(",", "\u00a0").replace(".", ",")
    return f"{sign}{formatted} \u20bd"


def analyze_cost_period(total: float, sections: dict[str, float]) -> dict[str, Any]:
    total_n = float(total or 0)
    top_section = ""
    top_value = 0.0
    for name, raw in (sections or {}).items():
        value = float(raw or 0)
        if value > top_value:
            top_value = value
            top_section = name
    top_share = (top_value / total_n * 100) if total_n > 0 else 0.0
    return {
        "top_section": top_section,
        "top_share": top_share,
        "is_concentrated": top_share >= ANOMALY_SECTION_SHARE_THRESHOLD,
    }


def median_positive(values: list[float]) -> float:
    positive = sorted(v for v in values if v > 0)
    if not positive:
        return 0.0
    mid = len(positive) // 2
    if len(positive) % 2:
        return positive[mid]
    return (positive[mid - 1] + positive[mid]) / 2


def scale_anomaly_baseline(totals: list[float]) -> float:
    """Baseline total for scale-outlier detection (robust with few periods)."""
    positive = sorted(v for v in totals if v > 0)
    if not positive:
        return 0.0
    if len(positive) <= 3:
        return positive[0]
    return median_positive(positive)

def classify_cost_periods(periods: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Mark periods as anomalies when total exceeds median×N or one section ≥70%."""
    totals = [float(p.get("total") or 0) for p in periods]
    med = scale_anomaly_baseline(totals)
    enriched: list[dict[str, Any]] = []
    for period in periods:
        total = float(period.get("total") or 0)
        sections = period.get("sections") or {}
        meta = analyze_cost_period(total, sections)
        is_scale_anomaly = med > 0 and total > med * ANOMALY_TOTAL_MEDIAN_MULTIPLIER
        is_anomaly = is_scale_anomaly or meta["is_concentrated"]
        enriched.append(
            {
                **period,
                **meta,
                "is_anomaly": is_anomaly,
                "is_scale_anomaly": is_scale_anomaly,
            }
        )
    return enriched


def filter_cost_periods_breakout(
    periods: list[dict[str, Any]],
    *,
    breakout: str,
) -> list[dict[str, Any]]:
    """Filter periods for breakout: normal | anomaly | all (scale anomalies only)."""
    if breakout == "anomaly":
        return [p for p in periods if p.get("is_scale_anomaly")]
    if breakout == "normal":
        return [p for p in periods if not p.get("is_scale_anomaly")]
    return list(periods)


def build_scale_anomaly_banner(
    periods: list[dict[str, Any]],
    *,
    section_short: dict[str, str] | None = None,
) -> str | None:
    """Build banner like «Апр–Май: ×N к медиане, топ ОПЗ YY%» for scale outliers."""
    scale_periods = [p for p in periods if p.get("is_scale_anomaly")]
    if not scale_periods:
        return None

    normal_totals = [
        float(p.get("total") or 0)
        for p in periods
        if not p.get("is_scale_anomaly") and float(p.get("total") or 0) > 0
    ]
    median = scale_anomaly_baseline(
        normal_totals or [float(p.get("total") or 0) for p in periods if float(p.get("total") or 0) > 0]
    )
    if median <= 0:
        return None

    short = section_short or {}
    groups: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for period in periods:
        if period.get("is_scale_anomaly"):
            current.append(period)
        elif current:
            groups.append(current)
            current = []
    if current:
        groups.append(current)

    parts: list[str] = []
    for group in groups:
        labels = [str(p.get("label") or "") for p in group]
        range_label = labels[0] if len(labels) == 1 else f"{labels[0]}\u2013{labels[-1]}"
        max_total = max(float(p.get("total") or 0) for p in group)
        multiplier = max_total / median
        mult_str = str(int(round(multiplier))) if multiplier >= 10 else f"{multiplier:.1f}".replace(".", ",")

        top_share = 0.0
        top_section = ""
        for p in group:
            share = float(p.get("top_share") or 0)
            if share >= top_share:
                top_share = share
                top_section = str(p.get("top_section") or "")
        top_label = short.get(top_section, top_section)
        share_str = f"{top_share:.1f}".replace(".", ",")
        parts.append(f"{range_label}: \u00d7{mult_str} к медиане, топ {top_label} {share_str}%")
    return " \u00b7 ".join(parts)


def top_cost_section_excluding_scale_anomalies(periods: list[dict[str, Any]]) -> tuple[str, float]:
    pool = [p for p in periods if not p.get("is_scale_anomaly")] or list(periods)
    top_section = ""
    top_value = 0.0
    for period in pool:
        for name, raw in (period.get("sections") or {}).items():
            value = float(raw or 0)
            if value > top_value:
                top_value = value
                top_section = name
    return top_section, top_value


def cost_structure_share_matrix(
    periods: list[dict[str, Any]],
    sections: list[str],
) -> list[list[float | None]]:
    """100% share values per section; small months stay readable vs outliers."""
    matrix: list[list[float | None]] = []
    for section in sections:
        row: list[float | None] = []
        for period in periods:
            total = float(period.get("total") or 0)
            actual = float((period.get("sections") or {}).get(section) or 0)
            if actual <= 0 or total <= 0:
                row.append(None)
            else:
                row.append(actual / total * 100)
        matrix.append(row)
    return matrix
