from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

from almabi_pq_revenue import build_pq_revenue_table, table_summary
from tests.test_almabi_exports import create_realization_workbook


def _pad_rows(sheet, count: int) -> None:
    for _ in range(count):
        sheet.append([])


def create_pq_revenue_workbook(path: Path) -> None:
    """Выгрузка с пустыми Column2/3/5/6 как в 1С перед PromoteHeaders."""
    workbook = Workbook()
    sheet = workbook.active
    _pad_rows(sheet, 7)
    sheet.append(
        [
            "Заказ клиента / Реализация",
            None,
            None,
            "Номенклатура",
            None,
            None,
            "Проект",
            "Группа проектов",
            "Направление",
            "Выручка",
            "Валовая прибыль",
        ]
    )
    sheet.append(
        [
            "Реализация 00АМ-000100 от 31.01.2026",
            None,
            None,
            "Лицензия ПО",
            None,
            None,
            "П-100",
            "Обслуживание",
            "Услуги",
            600_000,
            200_000,
        ]
    )
    sheet.append(
        [
            "Реализация 00АМ-000100 от 31.01.2026",
            None,
            None,
            "Лицензия ПО",
            None,
            None,
            "П-100",
            "Обслуживание",
            "Услуги",
            400_000,
            100_000,
        ]
    )
    sheet.append(["Итого"])
    workbook.save(path)


def test_build_pq_revenue_table_groups_by_document(tmp_path: Path):
    path = tmp_path / "revenue.xlsx"
    create_pq_revenue_workbook(path)

    rows = build_pq_revenue_table(path)

    assert len(rows) == 1
    assert rows[0]["Документ"] == "Реализация 00АМ-000100 от 31.01.2026"
    assert rows[0]["Проект"] == "П-100"
    assert rows[0]["Раздел"] == "Доходы"
    assert rows[0]["Сумма"] == 1_000_000


def test_build_pq_revenue_table_supports_compact_workbook(tmp_path: Path):
    path = tmp_path / "realization.xlsx"
    create_realization_workbook(path)

    rows = build_pq_revenue_table(path)

    assert len(rows) == 1
    assert rows[0]["Сумма"] == 1_000_000
    assert rows[0]["Раздел"] == "Доходы"


def test_table_summary_totals():
    rows = [{"Сумма": 100.0}, {"Сумма": 250.5}]
    summary = table_summary(rows)

    assert summary["row_count"] == 2
    assert summary["total_amount"] == 350.5
