from __future__ import annotations

from almabi_chart_ui import (
    build_scale_anomaly_banner,
    classify_cost_periods,
    cost_structure_share_matrix,
    filter_cost_periods_breakout,
    format_compact_ru,
    top_cost_section_excluding_scale_anomalies,
)


def test_format_compact_ru_billion_and_million():
    assert format_compact_ru(12_400_000_000) == "12,4 млрд"
    assert format_compact_ru(90_400_000) == "90,4 млн"
    assert format_compact_ru(3_900_000) == "3,9 млн"


def test_format_compact_ru_thousands_and_rubles():
    assert format_compact_ru(12_400) == "12,4 тыс"
    assert format_compact_ru(500) == "500 \u20bd"


def test_classify_cost_periods_scale_and_concentration():
    periods = [
        {"label": "Mar", "total": 100_000_000, "sections": {"ФОТ": 40_000_000, "Материальные затраты": 60_000_000}},
        {"label": "Apr", "total": 12_000_000_000, "sections": {"Общепроизводственные затраты": 11_500_000_000, "ФОТ": 500_000_000}},
    ]
    enriched = classify_cost_periods(periods)
    assert enriched[0]["is_anomaly"] is False
    assert enriched[1]["is_anomaly"] is True
    assert enriched[1]["is_concentrated"] is True
    assert enriched[1]["top_section"] == "Общепроизводственные затраты"


def test_breakout_ignores_concentration_only_periods():
    periods = classify_cost_periods(
        [
            {
                "label": "Mar",
                "total": 100_000_000,
                "sections": {"ФОТ": 25_000_000, "Материальные затраты": 75_000_000},
            },
            {"label": "Apr", "total": 12_000_000_000, "sections": {"Общепроизводственные затраты": 12_000_000_000}},
        ]
    )
    assert periods[0]["is_concentrated"] is True
    assert periods[0]["is_scale_anomaly"] is False
    normal = filter_cost_periods_breakout(periods, breakout="normal")
    assert len(normal) == 1
    assert normal[0]["label"] == "Mar"


def test_scale_anomaly_banner_and_top_section():
    periods = classify_cost_periods(
        [
            {"label": "Mar", "total": 100_000_000, "sections": {"ФОТ": 60_000_000, "Материальные затраты": 40_000_000}},
            {
                "label": "Apr",
                "total": 12_000_000_000,
                "sections": {"Общепроизводственные затраты": 11_400_000_000, "ФОТ": 600_000_000},
            },
            {
                "label": "May",
                "total": 11_000_000_000,
                "sections": {"Общепроизводственные затраты": 10_500_000_000, "ФОТ": 500_000_000},
            },
        ]
    )
    banner = build_scale_anomaly_banner(
        periods,
        section_short={"Общепроизводственные затраты": "ОПЗ"},
    )
    assert banner is not None
    assert "Apr\u2013May" in banner
    assert "\u00d7" in banner
    assert "ОПЗ" in banner

    top_section, top_value = top_cost_section_excluding_scale_anomalies(periods)
    assert top_section == "ФОТ"
    assert top_value == 60_000_000


def test_breakout_keeps_normal_months_readable():
    periods = classify_cost_periods(
        [
            {"label": "Mar", "total": 100_000_000, "sections": {"ФОТ": 40_000_000, "Материальные затраты": 60_000_000}},
            {"label": "Apr", "total": 12_000_000_000, "sections": {"Общепроизводственные затраты": 12_000_000_000}},
        ]
    )
    normal = filter_cost_periods_breakout(periods, breakout="normal")
    assert len(normal) == 1
    assert normal[0]["label"] == "Mar"

    shares = cost_structure_share_matrix(normal, ["ФОТ", "Материальные затраты"])
    assert shares[0][0] == 40.0
    assert shares[1][0] == 60.0


def test_share_mode_small_month_not_zeroed_by_outlier():
    periods = [
        {"label": "Mar", "total": 100_000_000, "sections": {"ФОТ": 25_000_000, "Материальные затраты": 75_000_000}},
        {"label": "Apr", "total": 12_000_000_000, "sections": {"Общепроизводственные затраты": 12_000_000_000}},
    ]
    sections = ["ФОТ", "Материальные затраты", "Общепроизводственные затраты"]
    matrix = cost_structure_share_matrix(periods, sections)
    assert matrix[0][0] == 25.0
    assert matrix[1][0] == 75.0
    assert matrix[2][1] == 100.0
