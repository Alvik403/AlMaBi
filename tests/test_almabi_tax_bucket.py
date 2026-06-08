from __future__ import annotations

from almabi_excel_utils import tax_bucket
from almabi_export_parsers import BuhRow
from almabi_pipeline import _merge_doc_tax


def test_tax_bucket_recognizes_privileged_variants():
    assert tax_bucket("Доходы по льготируемым видам деятельности") == "Льготные проекты"
    assert tax_bucket("Общие условия налогообложения") == "Нельготные проекты"


def test_merge_doc_tax_prefers_revenue_line_over_cost_line():
    doc_tax: dict[str, str] = {}
    _merge_doc_tax(
        doc_tax,
        BuhRow(
            document="Док 1",
            account_dt="90.02.1",
            account_kt="43",
            amount_buh=100,
            amount_nu_dt=100,
            amount_nu_kt=0,
            month="Январь",
            tax_type="Общие условия налогообложения",
            expense_article="",
            contract="",
            project="",
            nomenclature_kt="",
            contractor="",
        ),
    )
    _merge_doc_tax(
        doc_tax,
        BuhRow(
            document="Док 1",
            account_dt="62.01",
            account_kt="90.01.3",
            amount_buh=200,
            amount_nu_dt=0,
            amount_nu_kt=200,
            month="Январь",
            tax_type="Доходы по льготируемым видам деятельности",
            expense_article="",
            contract="",
            project="",
            nomenclature_kt="",
            contractor="",
        ),
    )

    assert doc_tax["Док 1"] == "Доходы по льготируемым видам деятельности"
