from __future__ import annotations

from almabi_excel_utils import tax_bucket
from almabi_export_parsers import BuhRow
from almabi_pipeline import _merge_doc_tax


def test_tax_bucket_recognizes_privileged_variants():
    assert tax_bucket("Доходы по льготируемым видам деятельности") == "Льготные проекты"
    assert tax_bucket("Общие условия налогообложения") == "Нельготные проекты"
    assert (
        tax_bucket("Резидент (участник) особой (свободной) экономической зоны")
        == "Льготные проекты"
    )


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


def test_build_facts_cost_inherits_privileged_tax_from_same_document():
    from almabi_export_parsers import BuhRow, ParsedExports
    from almabi_pipeline import build_facts

    document = "Реализация 00АМ-000017 от 31.01.2026"
    privileged = "Доходы по льготируемым видам деятельности"
    exports = ParsedExports(
        buh=[
            BuhRow(
                document=document,
                account_dt="90.02.1",
                account_kt="43",
                amount_buh=400_000,
                amount_nu_dt=400_000,
                amount_nu_kt=0,
                month="Январь",
                tax_type="Общие условия налогообложения",
                expense_article="",
                contract="",
                project="",
                nomenclature_kt="Лицензия ПО",
                contractor="",
            ),
            BuhRow(
                document=document,
                account_dt="62.01",
                account_kt="90.01.3",
                amount_buh=1_000_000,
                amount_nu_dt=0,
                amount_nu_kt=1_000_000,
                month="Январь",
                tax_type=privileged,
                expense_article="",
                contract="",
                project="",
                nomenclature_kt="Лицензия ПО",
                contractor="",
            ),
        ]
    )

    facts = build_facts(exports).facts
    cost_facts = [fact for fact in facts if fact.kpi_l1 == "Себестоимость"]
    revenue_facts = [fact for fact in facts if fact.kpi_l1 == "Выручка"]

    assert len(cost_facts) == 1
    assert len(revenue_facts) == 1
    assert cost_facts[0].tax_type == privileged
    assert revenue_facts[0].tax_type == privileged
    assert tax_bucket(cost_facts[0].tax_type) == "Льготные проекты"


def test_duplicate_cost_buh_key_uses_buh_amount_per_line():
    from almabi_export_parsers import BuhRow, CostRow, ParsedExports
    from almabi_pipeline import build_facts

    document = "Реализация 00АМ-000070 от 17.04.2026 21:00:00"
    nomenclature = "Комплект замков тары (20.9801.050.00.00)"
    privileged = "Резидент (участник) особой (свободной) экономической зоны"
    exports = ParsedExports(
        buh=[
            BuhRow(
                document=document,
                account_dt="90.02.1",
                account_kt="43",
                amount_buh=4_940_720.02,
                amount_nu_dt=4_940_720.02,
                amount_nu_kt=0,
                month="Апрель",
                tax_type=privileged,
                expense_article="",
                contract="",
                project="",
                nomenclature_kt=nomenclature,
                contractor="",
            ),
            BuhRow(
                document=document,
                account_dt="90.02.1",
                account_kt="43",
                amount_buh=14_048_895.55,
                amount_nu_dt=14_048_895.55,
                amount_nu_kt=0,
                month="Апрель",
                tax_type=privileged,
                expense_article="",
                contract="",
                project="",
                nomenclature_kt=nomenclature,
                contractor="",
            ),
        ],
        cost=[
            CostRow(
                document=document,
                nomenclature=nomenclature,
                account="20",
                calc_article="",
                amount=100_637.73,
                quantity=1,
                month="Апрель",
                cost_section="",
                contract="",
            ),
        ],
    )

    facts = build_facts(exports).facts
    cost_facts = [fact for fact in facts if fact.kpi_l1 == "Себестоимость"]

    assert len(cost_facts) == 2
    assert sum(abs(fact.amount_buh) for fact in cost_facts) == 19_190_891.03
    assert all(tax_bucket(fact.tax_type) == "Льготные проекты" for fact in cost_facts)


def test_other_pnl_storno_general_leg_inherits_privileged_tax():
    from almabi_export_parsers import BuhRow, ParsedExports
    from almabi_pipeline import build_facts

    document = "Прочие доходы и расходы 00АМ-000544 от 30.04.2026"
    privileged = "Резидент (участник) особой (свободной) экономической зоны"
    amount_income = 36_680.50
    amount_expense_buh = 90_857.05
    amount_expense_nu = 68_194.00

    exports = ParsedExports(
        buh=[
            BuhRow(
                document=document,
                account_dt="76.09",
                account_kt="91.01",
                amount_buh=amount_income,
                amount_nu_dt=0,
                amount_nu_kt=amount_income,
                month="Апрель",
                tax_type="Общие условия налогообложения",
                expense_article="",
                contract="",
                project="",
                nomenclature_kt="",
                contractor="",
            ),
            BuhRow(
                document=document,
                account_dt="76.09",
                account_kt="91.01",
                amount_buh=-amount_income,
                amount_nu_dt=0,
                amount_nu_kt=amount_income,
                month="Апрель",
                tax_type=privileged,
                expense_article="",
                contract="",
                project="",
                nomenclature_kt="",
                contractor="",
            ),
            BuhRow(
                document=document,
                account_dt="91.02",
                account_kt="76.09",
                amount_buh=amount_expense_buh,
                amount_nu_dt=amount_expense_nu,
                amount_nu_kt=0,
                month="Апрель",
                tax_type="Общие условия налогообложения",
                expense_article="",
                contract="",
                project="",
                nomenclature_kt="",
                contractor="",
            ),
            BuhRow(
                document=document,
                account_dt="91.02",
                account_kt="76.09",
                amount_buh=-amount_expense_buh,
                amount_nu_dt=amount_expense_nu,
                amount_nu_kt=0,
                month="Апрель",
                tax_type=privileged,
                expense_article="",
                contract="",
                project="",
                nomenclature_kt="",
                contractor="",
            ),
        ]
    )

    facts = build_facts(exports).facts
    income_facts = [fact for fact in facts if fact.kpi_l1 == "Прочие доходы"]
    expense_facts = [fact for fact in facts if fact.kpi_l1 == "Прочие расходы"]

    assert len(income_facts) == 2
    assert len(expense_facts) == 2
    assert all(tax_bucket(fact.tax_type) == "Льготные проекты" for fact in income_facts)
    assert sum(fact.amount_buh for fact in income_facts) == 0
    assert sum(fact.amount_buh for fact in expense_facts) == 0
    assert any(tax_bucket(fact.tax_type) == "Нельготные проекты" for fact in expense_facts)
    assert any(tax_bucket(fact.tax_type) == "Льготные проекты" for fact in expense_facts)


def test_other_pnl_nu_split_uses_buh_side_tax_for_nu_only_rows():
    from almabi_export_parsers import BuhRow, ParsedExports
    from almabi_pipeline import build_facts

    document = "Прочие доходы и расходы 00АМ-000544 от 30.04.2026"
    privileged = "Резидент (участник) особой (свободной) экономической зоны"
    amount = 36_680.50

    exports = ParsedExports(
        buh=[
            BuhRow(
                document=document,
                account_dt="76.09",
                account_kt="91.01",
                amount_buh=amount,
                amount_nu_dt=0,
                amount_nu_kt=0,
                month="Апрель",
                tax_type="Общие условия налогообложения",
                expense_article="",
                contract="",
                project="",
                nomenclature_kt="",
                contractor="",
            ),
            BuhRow(
                document=document,
                account_dt="76.09",
                account_kt="91.01",
                amount_buh=-amount,
                amount_nu_dt=0,
                amount_nu_kt=0,
                month="Апрель",
                tax_type=privileged,
                expense_article="",
                contract="",
                project="",
                nomenclature_kt="",
                contractor="",
            ),
            BuhRow(
                document=document,
                account_dt="76.09",
                account_kt="91.01",
                amount_buh=0,
                amount_nu_dt=0,
                amount_nu_kt=amount,
                month="Апрель",
                tax_type="Общие условия налогообложения",
                expense_article="",
                contract="",
                project="",
                nomenclature_kt="",
                contractor="",
            ),
            BuhRow(
                document=document,
                account_dt="76.09",
                account_kt="91.01",
                amount_buh=0,
                amount_nu_dt=0,
                amount_nu_kt=-amount,
                month="Апрель",
                tax_type=privileged,
                expense_article="",
                contract="",
                project="",
                nomenclature_kt="",
                contractor="",
            ),
            BuhRow(
                document=document,
                account_dt="91.02",
                account_kt="76.09",
                amount_buh=amount,
                amount_nu_dt=amount * 0.8,
                amount_nu_kt=0,
                month="Апрель",
                tax_type="Общие условия налогообложения",
                expense_article="",
                contract="",
                project="",
                nomenclature_kt="",
                contractor="",
            ),
        ]
    )

    facts = build_facts(exports).facts
    income_facts = [fact for fact in facts if fact.kpi_l1 == "Прочие доходы"]
    priv_nu = sum(fact.amount_nu for fact in income_facts if tax_bucket(fact.tax_type) == "Льготные проекты")
    non_nu = sum(fact.amount_nu for fact in income_facts if tax_bucket(fact.tax_type) == "Нельготные проекты")

    assert sum(fact.amount_nu for fact in income_facts) == 0
    assert priv_nu == 0
    assert non_nu == 0


def test_other_pnl_keeps_raw_tax_for_cost_rounding_rows():
    from almabi_export_parsers import BuhRow, ParsedExports
    from almabi_pipeline import COST_ROUNDING_ARTICLE, build_facts

    document = "Расчет себестоимости товаров АМ-00000004 от 30.04.2026 23:59:59"
    privileged = "Резидент (участник) особой (свободной) экономической зоны"
    amount_buh = 10_000.0
    amount_nu = 8_000.0
    rounding_buh = 0.02

    exports = ParsedExports(
        buh=[
            BuhRow(
                document=document,
                account_dt="91.02",
                account_kt="26",
                amount_buh=amount_buh,
                amount_nu_dt=amount_nu,
                amount_nu_kt=0,
                month="Апрель",
                tax_type="Общие условия налогообложения",
                expense_article="",
                contract="",
                project="",
                nomenclature_kt="",
                contractor="",
            ),
            BuhRow(
                document=document,
                account_dt="91.02",
                account_kt="26",
                amount_buh=-amount_buh,
                amount_nu_dt=-amount_nu,
                amount_nu_kt=0,
                month="Апрель",
                tax_type=privileged,
                expense_article="",
                contract="",
                project="",
                nomenclature_kt="",
                contractor="",
            ),
            BuhRow(
                document=document,
                account_dt="91.02",
                account_kt="26",
                amount_buh=rounding_buh,
                amount_nu_dt=rounding_buh,
                amount_nu_kt=0,
                month="Апрель",
                tax_type="Общие условия налогообложения",
                expense_article=COST_ROUNDING_ARTICLE,
                contract="",
                project="",
                nomenclature_kt="",
                contractor="",
            ),
            BuhRow(
                document=document,
                account_dt="91.02",
                account_kt="26",
                amount_buh=-rounding_buh,
                amount_nu_dt=-rounding_buh,
                amount_nu_kt=0,
                month="Апрель",
                tax_type=privileged,
                expense_article=COST_ROUNDING_ARTICLE,
                contract="",
                project="",
                nomenclature_kt="",
                contractor="",
            ),
        ]
    )

    facts = build_facts(exports).facts
    rounding_facts = [
        fact
        for fact in facts
        if fact.kpi_l1 == "Прочие расходы" and fact.expense_article == COST_ROUNDING_ARTICLE
    ]

    non_priv_buh = sum(
        fact.amount_buh
        for fact in rounding_facts
        if tax_bucket(fact.tax_type) == "Нельготные проекты"
    )
    priv_buh = sum(
        fact.amount_buh
        for fact in rounding_facts
        if tax_bucket(fact.tax_type) == "Льготные проекты"
    )
    non_priv_nu = sum(
        fact.amount_nu
        for fact in rounding_facts
        if tax_bucket(fact.tax_type) == "Нельготные проекты"
    )
    priv_nu = sum(
        fact.amount_nu
        for fact in rounding_facts
        if tax_bucket(fact.tax_type) == "Льготные проекты"
    )
    assert non_priv_buh == -rounding_buh
    assert priv_buh == rounding_buh
    assert non_priv_nu == -rounding_buh
    assert priv_nu == rounding_buh


def test_other_pnl_income_keeps_raw_tax_when_section_has_no_nu():
    """Курсовые: доходы без НУ не наследуют льготу со сторно расходов того же документа."""
    from almabi_export_parsers import BuhRow, ParsedExports
    from almabi_pipeline import build_facts

    document = "Операция 00АМ-000550 от 31.03.2026"
    privileged = "Резидент (участник) особой (свободной) экономической зоны"
    income_amount = 177_494.0
    expense_buh = 286_993.71
    expense_nu = 177_330.32

    exports = ParsedExports(
        buh=[
            BuhRow(
                document=document,
                account_dt="60.31",
                account_kt="91.01",
                amount_buh=-income_amount,
                amount_nu_dt=0,
                amount_nu_kt=0,
                month="Март",
                tax_type="Общие условия налогообложения",
                expense_article="Курсовые разницы",
                contract="",
                project="",
                nomenclature_kt="",
                contractor="",
            ),
            BuhRow(
                document=document,
                account_dt="60.31",
                account_kt="91.01",
                amount_buh=income_amount,
                amount_nu_dt=0,
                amount_nu_kt=0,
                month="Март",
                tax_type=privileged,
                expense_article="Курсовые разницы",
                contract="",
                project="",
                nomenclature_kt="",
                contractor="",
            ),
            BuhRow(
                document=document,
                account_dt="91.02",
                account_kt="60.31",
                amount_buh=expense_buh,
                amount_nu_dt=expense_nu,
                amount_nu_kt=0,
                month="Март",
                tax_type="Общие условия налогообложения",
                expense_article="Курсовые разницы",
                contract="",
                project="",
                nomenclature_kt="",
                contractor="",
            ),
            BuhRow(
                document=document,
                account_dt="91.02",
                account_kt="60.31",
                amount_buh=-expense_buh,
                amount_nu_dt=expense_nu,
                amount_nu_kt=0,
                month="Март",
                tax_type=privileged,
                expense_article="Курсовые разницы",
                contract="",
                project="",
                nomenclature_kt="",
                contractor="",
            ),
        ]
    )

    facts = build_facts(exports).facts
    income_facts = [fact for fact in facts if fact.kpi_l1 == "Прочие доходы"]
    expense_facts = [fact for fact in facts if fact.kpi_l1 == "Прочие расходы"]

    priv_income_bu = sum(
        fact.amount_buh for fact in income_facts if tax_bucket(fact.tax_type) == "Льготные проекты"
    )
    non_income_bu = sum(
        fact.amount_buh for fact in income_facts if tax_bucket(fact.tax_type) == "Нельготные проекты"
    )
    priv_expense_bu = sum(
        fact.amount_buh for fact in expense_facts if tax_bucket(fact.tax_type) == "Льготные проекты"
    )

    assert priv_income_bu == income_amount
    assert non_income_bu == -income_amount
    assert priv_expense_bu == expense_buh


def test_other_pnl_expense_bu_nu_pair_keeps_raw_when_income_section_has_no_nu():
    """Расходы БУ=НУ не наследуют льготу, если в прочих доходах документа нет НУ."""
    from almabi_export_parsers import BuhRow, ParsedExports
    from almabi_pipeline import build_facts

    document = "Операция 00АМ-000552 от 31.03.2026"
    privileged = "Резидент (участник) особой (свободной) экономической зоны"
    amount = 72_426.64

    exports = ParsedExports(
        buh=[
            BuhRow(
                document=document,
                account_dt="60.21",
                account_kt="91.01",
                amount_buh=-amount,
                amount_nu_dt=0,
                amount_nu_kt=0,
                month="Март",
                tax_type="Общие условия налогообложения",
                expense_article="Курсовые разницы",
                contract="",
                project="",
                nomenclature_kt="",
                contractor="",
            ),
            BuhRow(
                document=document,
                account_dt="60.21",
                account_kt="91.01",
                amount_buh=amount,
                amount_nu_dt=0,
                amount_nu_kt=0,
                month="Март",
                tax_type=privileged,
                expense_article="Курсовые разницы",
                contract="",
                project="",
                nomenclature_kt="",
                contractor="",
            ),
            BuhRow(
                document=document,
                account_dt="91.02",
                account_kt="60.21",
                amount_buh=amount,
                amount_nu_dt=amount,
                amount_nu_kt=0,
                month="Март",
                tax_type="Общие условия налогообложения",
                expense_article="Курсовые разницы",
                contract="",
                project="",
                nomenclature_kt="",
                contractor="",
            ),
            BuhRow(
                document=document,
                account_dt="91.02",
                account_kt="60.21",
                amount_buh=-amount,
                amount_nu_dt=amount,
                amount_nu_kt=0,
                month="Март",
                tax_type=privileged,
                expense_article="Курсовые разницы",
                contract="",
                project="",
                nomenclature_kt="",
                contractor="",
            ),
        ]
    )

    facts = build_facts(exports).facts
    expense_facts = [fact for fact in facts if fact.kpi_l1 == "Прочие расходы"]
    priv_bu = sum(
        fact.amount_buh for fact in expense_facts if tax_bucket(fact.tax_type) == "Льготные проекты"
    )
    priv_nu = sum(
        fact.amount_nu for fact in expense_facts if tax_bucket(fact.tax_type) == "Льготные проекты"
    )

    assert priv_bu == amount
    assert priv_nu == -amount

def test_other_expense_skips_non_deductible_inventory_writeoff():
    """Исходное списание ТМЦ исключается, но его межпериодное сторно сохраняется."""
    from almabi_export_parsers import ParsedExports
    from almabi_pipeline import NON_DEDUCTIBLE_INVENTORY_ARTICLE, build_facts

    exports = ParsedExports(
        buh=[
            BuhRow(
                document="Операция 00АМ-000546",
                account_dt="91.02",
                account_kt="10.01",
                amount_buh=5_635.35,
                amount_nu_dt=5_635.35,
                amount_nu_kt=5_635.35,
                month="Март",
                tax_type="Общие условия налогообложения",
                expense_article=NON_DEDUCTIBLE_INVENTORY_ARTICLE,
                contract="",
                project="",
                nomenclature_kt="Стеллаж",
                contractor="",
            ),
            BuhRow(
                document="Приобретение 00АМ-000162",
                account_dt="91.02",
                account_kt="60.01",
                amount_buh=57_377.05,
                amount_nu_dt=0,
                amount_nu_kt=0,
                month="Январь",
                tax_type="Общие условия налогообложения",
                expense_article=NON_DEDUCTIBLE_INVENTORY_ARTICLE,
                contract="",
                project="",
                nomenclature_kt="",
                contractor="",
            ),
            BuhRow(
                document="Операция 00АМ-000565",
                account_dt="91.02",
                account_kt="10.01",
                amount_buh=-5_635.35,
                amount_nu_dt=0,
                amount_nu_kt=0,
                month="Апрель",
                tax_type="Общие условия налогообложения",
                expense_article=NON_DEDUCTIBLE_INVENTORY_ARTICLE,
                contract="",
                project="",
                nomenclature_kt="Стеллаж",
                contractor="",
            ),
        ]
    )
    facts = build_facts(exports).facts
    expense = [fact for fact in facts if fact.kpi_l1 == "Прочие расходы"]
    by_month = {fact.month: fact.amount_buh for fact in expense}
    assert by_month == {"Январь": -57_377.05, "Апрель": 5_635.35}

