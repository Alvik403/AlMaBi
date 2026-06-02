from __future__ import annotations

import pytest

from file_validation import validate_excel_file


def test_validate_excel_file_accepts_expected_structure(sample_excel_path):
    result = validate_excel_file(sample_excel_path)

    assert result.service_count == 1
    assert result.class_count == 1


def test_validate_excel_file_rejects_non_xlsx(tmp_path):
    path = tmp_path / "data.txt"
    path.write_text("not excel", encoding="utf-8")

    with pytest.raises(ValueError, match="только файлы .xlsx"):
        validate_excel_file(path)


def test_validate_excel_file_rejects_wrong_structure(tmp_path):
    path = tmp_path / "broken.xlsx"
    path.write_bytes(b"not an excel file")

    with pytest.raises(ValueError, match="не прошёл проверку структуры"):
        validate_excel_file(path)
