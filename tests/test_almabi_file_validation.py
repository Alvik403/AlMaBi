from __future__ import annotations

from pathlib import Path

import pytest

from almabi_file_validation import validate_almabi_excel


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BDR_TEMPLATE = PROJECT_ROOT / "fixtures" / "bdr_template_empty.xlsx"


@pytest.mark.skipif(not BDR_TEMPLATE.exists(), reason="BDR fixture is missing")
def test_validate_empty_bdr_template():
    result = validate_almabi_excel(BDR_TEMPLATE)

    assert result.format == "bdr_export"
    assert result.header_row == 9
