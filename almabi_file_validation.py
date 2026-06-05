from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from openpyxl import load_workbook


@dataclass(frozen=True)
class AlmabiValidationResult:
    format: str
    sheet_name: str
    header_row: int

    def to_dict(self) -> dict:
        return {
            "format": self.format,
            "sheet_name": self.sheet_name,
            "header_row": self.header_row,
        }


_BDR_MARKERS = ("Документ", "Сумма", "Счет Дт")
_REALIZATION_MARKERS = ("Выручка", "Номенклатура", "Revenue", "SKU")


def _normalize_cell(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _row_texts(row: tuple[object, ...]) -> list[str]:
    return [_normalize_cell(value) for value in row if _normalize_cell(value)]


def _detect_format(cells: list[str]) -> str | None:
    joined = " | ".join(cells)
    if all(marker in joined for marker in _BDR_MARKERS):
        return "bdr_export"
    if any(marker in joined for marker in _REALIZATION_MARKERS):
        return "realization_export"
    return None


def validate_almabi_excel(path: Path) -> AlmabiValidationResult:
    if path.suffix.casefold() != ".xlsx":
        raise ValueError("Поддерживаются только файлы .xlsx")
    if not path.exists():
        raise ValueError(f"Файл не найден: {path}")
    if path.stat().st_size == 0:
        raise ValueError("Файл пустой")

    try:
        workbook = load_workbook(path, read_only=True, data_only=True)
    except Exception as exc:
        raise ValueError(f"Не удалось открыть Excel: {exc}") from exc

    try:
        for sheet in workbook.worksheets:
            for row_index, row in enumerate(
                sheet.iter_rows(min_row=1, max_row=30, values_only=True),
                start=1,
            ):
                cells = _row_texts(row)
                if not cells:
                    continue
                detected = _detect_format(cells)
                if detected:
                    return AlmabiValidationResult(
                        format=detected,
                        sheet_name=sheet.title,
                        header_row=row_index,
                    )
    finally:
        workbook.close()

    raise ValueError(
        "Файл не похож на выгрузку БДР или реализаций. "
        "Ожидаются колонки «Документ», «Сумма», «Счет Дт» или «Выручка», «Номенклатура»."
    )
