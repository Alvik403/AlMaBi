from __future__ import annotations

from dashboard_builder import build_dashboard_data, build_navigation_data
from data_loader import load_calculation_services_dataset


def test_dashboard_builder_creates_overview_and_navigation(sample_excel_path):
    dataset = load_calculation_services_dataset(sample_excel_path)

    overview = build_dashboard_data(dataset)
    navigation = build_navigation_data(dataset)

    assert overview["totals"]["total_services"] == 1
    assert overview["totals"]["total_classes"] == 1
    assert navigation["class_index"]["экспорт/сибур"]["services_count"] == 1
    assert ("экспорт/сибур", "Комплексная/услуга 2") in navigation["service_index"]
