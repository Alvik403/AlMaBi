from __future__ import annotations

from pathlib import Path

import pytest
from openpyxl import Workbook

from almabi_dashboard_builder import load_almabi_dashboard_from_exports
from almabi_file_validation import validate_almabi_export


def _pad_rows(sheet, count: int) -> None:
    for _ in range(count):
        sheet.append([None])


def create_buh_workbook(
    path: Path,
    *,
    document: str = "Реализация товаров и услуг 00АМ-000017 от 31.01.2026 21:00:00",
) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Лист_1"
    _pad_rows(sheet, 8)
    headers = [
        "Документ",
        "Счет Дт",
        "Вид субконто2 Дт",
        "Субконто2 Дт",
        "Счет Кт",
        "Вид субконто1 Кт",
        "Субконто1 Кт",
        "Дата",
        "Договор",
        "Сумма",
        "Сумма НУ Дт",
        "Сумма НУ Кт",
    ]
    sheet.append(headers)
    realization_document = document
    sheet.append(
        [
            realization_document,
            "90.02.1",
            "Варианты налогообложения прибыли",
            "Общие условия налогообложения",
            "43",
            "Номенклатура",
            "Лицензия ПО",
            "15.01.2026",
            "Д-001",
            400_000,
            400_000,
            0,
        ]
    )
    sheet.append(
        [
            realization_document,
            "62.01",
            "Варианты налогообложения прибыли",
            "Доходы по льготируемым видам деятельности",
            "90.01.3",
            "",
            "",
            "15.01.2026",
            "Д-001",
            1_000_000,
            0,
            1_000_000,
        ]
    )
    sheet.append(
        [
            realization_document,
            "62.01",
            "Контрагенты",
            "ООО Тест Клиент",
            "51",
            "",
            "",
            "15.01.2026",
            "Д-001",
            1,
            0,
            0,
        ]
    )
    sheet.append(
        [
            realization_document,
            "90.07.1",
            "Варианты налогообложения прибыли",
            "Общие условия налогообложения",
            "44",
            "Статьи затрат",
            "Реклама",
            "20.02.2026",
            "",
            50_000,
            50_000,
            0,
        ]
    )
    sheet.append(["Итого"])
    workbook.save(path)


def create_realization_workbook(path: Path, *, document: str = "Реализация товаров и услуг 00АМ-000017 от 31.01.2026 21:00:00") -> None:
    workbook = Workbook()
    sheet = workbook.active
    _pad_rows(sheet, 7)
    headers = [
        "Заказ клиента / Реализация",
        "Номенклатура",
        "Проект",
        "Группа проектов",
        "Направление",
        "Выручка",
        "Валовая прибыль",
    ]
    sheet.append(headers)
    sheet.append(
        [
            document,
            "Лицензия ПО",
            "Обслуживание Долго",
            "Обслуживание",
            "Услуги",
            1_000_000,
            600_000,
        ]
    )
    sheet.append(["Итого"])
    workbook.save(path)


def create_cost_workbook(
    path: Path,
    *,
    document: str = "Реализация товаров и услуг 00АМ-000017 от 31.01.2026 21:00:00",
    quantity: float = 1,
    header_pad: int = 5,
) -> None:
    workbook = Workbook()
    sheet = workbook.active
    _pad_rows(sheet, header_pad)
    headers = [
        "Продукция",
        "Счет",
        "Статья калькуляции",
        "Документ отгрузки",
        "Договор",
        "Количество продаж",
        "Себестоимость (бухг. учет)",
    ]
    sheet.append(headers)
    sheet.append(
        [
            "Лицензия ПО",
            "20",
            "Сырье и материалы",
            document,
            "Д-001",
            quantity,
            400_000,
        ]
    )
    _pad_rows(sheet, 38)
    workbook.save(path)


def create_profit_before_tax_buh_workbook(path: Path) -> None:
    """Бухрегистр с операционными строками, прочими доходами и расходами."""
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Лист_1"
    _pad_rows(sheet, 8)
    headers = [
        "Документ",
        "Счет Дт",
        "Вид субконто2 Дт",
        "Субконто2 Дт",
        "Счет Кт",
        "Вид субконто1 Кт",
        "Субконто1 Кт",
        "Дата",
        "Договор",
        "Сумма",
        "Сумма НУ Дт",
        "Сумма НУ Кт",
    ]
    sheet.append(headers)
    realization_document = "Реализация товаров и услуг 00АМ-000017 от 31.01.2026 21:00:00"
    sheet.append(
        [
            realization_document,
            "90.02.1",
            "Варианты налогообложения прибыли",
            "Общие условия налогообложения",
            "43",
            "Номенклатура",
            "Лицензия ПО",
            "15.01.2026",
            "Д-001",
            400_000,
            400_000,
            0,
        ]
    )
    sheet.append(
        [
            realization_document,
            "62.01",
            "Варианты налогообложения прибыли",
            "Доходы по льготируемым видам деятельности",
            "90.01.3",
            "",
            "",
            "15.01.2026",
            "Д-001",
            1_000_000,
            0,
            1_000_000,
        ]
    )
    sheet.append(
        [
            realization_document,
            "62.01",
            "Контрагенты",
            "ООО Тест Клиент",
            "51",
            "",
            "",
            "15.01.2026",
            "Д-001",
            1,
            0,
            0,
        ]
    )
    sheet.append(
        [
            realization_document,
            "90.07.1",
            "Варианты налогообложения прибыли",
            "Общие условия налогообложения",
            "44",
            "Статьи затрат",
            "Реклама",
            "20.02.2026",
            "",
            50_000,
            50_000,
            0,
        ]
    )
    sheet.append(
        [
            "Операция 0001 от 15.03.2026",
            "76.09",
            "",
            "",
            "91.01",
            "Прочие доходы и расходы",
            "Проценты полученные",
            "15.03.2026",
            "",
            400_000,
            0,
            400_000,
        ]
    )
    sheet.append(
        [
            "Операция штраф от 20.04.2026",
            "91.02",
            "Прочие доходы и расходы",
            "Штрафы",
            "76.09",
            "",
            "",
            "20.04.2026",
            "",
            50_000,
            50_000,
            0,
        ]
    )
    sheet.append(["Итого"])
    workbook.save(path)


def create_other_income_buh_workbook(
    path: Path,
    *,
    document: str = "Операция 0001 от 15.03.2026",
    article: str = "Проценты полученные",
    amount: float = 400_000,
) -> None:
    workbook = Workbook()
    sheet = workbook.active
    _pad_rows(sheet, 8)
    headers = [
        "Документ",
        "Счет Дт",
        "Счет Кт",
        "Субконто1 Кт",
        "Дата",
        "Сумма",
        "Сумма НУ Дт",
        "Сумма НУ Кт",
    ]
    sheet.append(headers)
    sheet.append(
        [
            document,
            "76.09",
            "91.01",
            article,
            "15.03.2026",
            amount,
            0,
            amount,
        ]
    )
    sheet.append(["Итого"])
    workbook.save(path)


def create_other_expense_buh_workbook(
    path: Path,
    *,
    document: str = "Операция штраф от 20.04.2026",
    article: str = "Штрафы",
    amount: float = 50_000,
) -> None:
    workbook = Workbook()
    sheet = workbook.active
    _pad_rows(sheet, 8)
    headers = [
        "Документ",
        "Счет Дт",
        "Субконто1 Дт",
        "Счет Кт",
        "Дата",
        "Сумма",
        "Сумма НУ Дт",
        "Сумма НУ Кт",
    ]
    sheet.append(headers)
    sheet.append(
        [
            document,
            "91.02",
            article,
            "76.09",
            "20.04.2026",
            amount,
            amount,
            0,
        ]
    )
    sheet.append(["Итого"])
    workbook.save(path)


def create_management_expense_buh_workbook(
    path: Path,
    *,
    document: str = "Операция аренда от 10.05.2026",
    article: str = "Аренда офиса",
    amount: float = 75_000,
) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Лист_1"
    _pad_rows(sheet, 8)
    headers = [
        "Документ",
        "Счет Дт",
        "Вид субконто2 Дт",
        "Субконто2 Дт",
        "Счет Кт",
        "Вид субконто1 Кт",
        "Субконто1 Кт",
        "Дата",
        "Договор",
        "Сумма",
        "Сумма НУ Дт",
        "Сумма НУ Кт",
    ]
    sheet.append(headers)
    sheet.append(
        [
            document,
            "90.08.1",
            "Варианты налогообложения прибыли",
            "Общие условия налогообложения",
            "26",
            "Статьи затрат",
            article,
            "10.05.2026",
            "",
            amount,
            amount,
            0,
        ]
    )
    sheet.append(["Итого"])
    workbook.save(path)


def create_amort_workbook(path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    _pad_rows(sheet, 8)
    headers = [
        "Статья расходов",
        "Организация",
        "Подразделение",
        "Статья калькуляции",
        "Регистратор (рег.) приход",
        "Дата записи",
        "Направление деятельности",
        "Стоимость",
    ]
    sheet.append(headers)
    sheet.append(["Амортизация ОС", "ООО Тест", "Цех 1", "Амортизация", "Док 1", "31.01.2026", "Услуги", 25_000])
    sheet.append(["Итого"])
    workbook.save(path)


def test_buh_other_income_expense_articles_are_parsed(tmp_path: Path):
    from almabi_export_parsers import parse_buh_register

    income_path = tmp_path / "income.xlsx"
    expense_path = tmp_path / "expense.xlsx"
    create_other_income_buh_workbook(income_path)
    create_other_expense_buh_workbook(expense_path)

    income = parse_buh_register(income_path)[0]
    expense = parse_buh_register(expense_path)[0]
    assert income.expense_article == "Проценты полученные"
    assert expense.expense_article == "Штрафы"


def test_other_pnl_drill_distributes_by_article(tmp_path: Path):
    paths = {
        "buh": tmp_path / "buh.xlsx",
        "realization": tmp_path / "realization.xlsx",
        "cost": tmp_path / "cost.xlsx",
    }
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    _pad_rows(sheet, 8)
    sheet.append(
        [
            "Документ",
            "Счет Дт",
            "Вид субконто1 Дт",
            "Субконто1 Дт",
            "Счет Кт",
            "Вид субконто1 Кт",
            "Субконто1 Кт",
            "Дата",
            "Сумма",
            "Сумма НУ Дт",
            "Сумма НУ Кт",
        ]
    )
    sheet.append(
        [
            "Операция 0001 от 15.03.2026",
            "76.09",
            "",
            "",
            "91.01",
            "Прочие доходы и расходы",
            "Проценты полученные",
            "15.03.2026",
            400_000,
            0,
            400_000,
        ]
    )
    sheet.append(
        [
            "Операция штраф от 20.04.2026",
            "91.02",
            "Прочие доходы и расходы",
            "Штрафы",
            "76.09",
            "",
            "",
            "20.04.2026",
            50_000,
            50_000,
            0,
        ]
    )
    sheet.append(["Итого"])
    workbook.save(paths["buh"])
    create_realization_workbook(paths["realization"], document="Другой документ")
    create_cost_workbook(paths["cost"], document="Другой документ")

    dashboard = load_almabi_dashboard_from_exports(
        paths,
        upload_names={key: path.name for key, path in paths.items()},
    )
    rows = {row["name"]: row for row in dashboard["summary_rows"]}
    income = rows["Прочие доходы"]
    assert income["drill"]["type"] == "other_pnl"

    sections = {section["name"]: section["articles"] for section in income["drill"]["total"]["sections"]}
    income_articles = [item["name"] for item in sections["Прочие доходы"]]
    expense_articles = [item["name"] for item in sections["Прочие расходы"]]
    assert income_articles == ["Проценты полученные"]
    assert expense_articles == ["Штрафы"]


def test_commercial_expense_article_from_cost_kind(tmp_path: Path):
    from almabi_export_parsers import parse_buh_register

    path = tmp_path / "buh.xlsx"
    create_buh_workbook(path)
    commercial = next(row for row in parse_buh_register(path) if row.account_dt.startswith("90.07"))
    assert commercial.expense_article == "Реклама"


def test_parse_cost_finds_header_on_row_4_or_6(tmp_path: Path):
    from almabi_export_parsers import parse_cost

    for header_pad in (3, 5):
        path = tmp_path / f"cost-pad-{header_pad}.xlsx"
        create_cost_workbook(path, header_pad=header_pad, quantity=7)
        rows = parse_cost(path)
        assert len(rows) == 1
        assert rows[0].quantity == 7
        assert rows[0].amount == 400_000


def test_revenue_and_cost_facts_get_quantity_from_cost_file(tmp_path: Path):
    from almabi_dashboard_builder import load_almabi_dashboard_from_exports
    from almabi_export_parsers import parse_exports
    from almabi_pipeline import build_facts
    from almabi_test_pipeline import build_test_facts

    paths = {
        "buh": tmp_path / "buh.xlsx",
        "realization": tmp_path / "realization.xlsx",
        "cost": tmp_path / "cost.xlsx",
    }
    create_buh_workbook(paths["buh"])
    create_realization_workbook(paths["realization"])
    create_cost_workbook(paths["cost"], quantity=12.5)

    main_facts = build_facts(parse_exports(paths)).facts
    revenue = [fact for fact in main_facts if fact.kpi_l1 == "Выручка" and fact.nomenclature == "Лицензия ПО"]
    cost = [fact for fact in main_facts if fact.kpi_l1 == "Себестоимость" and fact.nomenclature == "Лицензия ПО"]
    assert revenue
    assert cost
    assert revenue[0].quantity == 12.5
    assert cost[0].quantity == 12.5

    test_facts = build_test_facts(parse_exports(paths)).facts
    test_revenue = [fact for fact in test_facts if fact.kpi_l1 == "Выручка" and fact.nomenclature == "Лицензия ПО"]
    test_cost = [fact for fact in test_facts if fact.kpi_l1 == "Себестоимость" and fact.nomenclature == "Лицензия ПО"]
    assert test_revenue
    assert test_cost
    assert test_revenue[0].quantity == 12.5
    assert test_cost[0].quantity == 12.5

    dashboard = load_almabi_dashboard_from_exports(
        paths,
        upload_names={key: path.name for key, path in paths.items()},
    )
    rows = {row["name"]: row for row in dashboard["summary_rows"]}
    drill_lines = {line["name"]: line for line in rows["Выручка"]["drill"]["total"]["lines"]}
    assert drill_lines["Лицензия ПО"]["quantity"] == 12.5
    assert drill_lines["Лицензия ПО"]["revenue"]["buh"] == 1_000_000
    assert drill_lines["Лицензия ПО"]["cost"]["buh"] == 400_000


def test_validate_export_types(tmp_path: Path):
    paths = {
        "buh": tmp_path / "buh.xlsx",
        "realization": tmp_path / "realization.xlsx",
        "cost": tmp_path / "cost.xlsx",
    }
    create_buh_workbook(paths["buh"])
    create_realization_workbook(paths["realization"])
    create_cost_workbook(paths["cost"])

    assert validate_almabi_export(paths["buh"]).export_type == "buh"
    assert validate_almabi_export(paths["realization"]).export_type == "realization"
    assert validate_almabi_export(paths["cost"]).export_type == "cost"


def test_realization_projects_columns_are_parsed(tmp_path: Path):
    path = tmp_path / "realization.xlsx"
    create_realization_workbook(path)
    from almabi_export_parsers import parse_realization

    rows = parse_realization(path)
    assert rows[0].direction == "Услуги"
    assert rows[0].project_group == "Обслуживание"
    assert rows[0].project == "Обслуживание Долго"
    assert rows[0].month == "Январь"


def test_project_index_matches_documents_by_number(tmp_path: Path):
    from almabi_pipeline import build_facts
    from almabi_export_parsers import parse_exports

    realization_path = tmp_path / "realization.xlsx"
    cost_path = tmp_path / "cost.xlsx"
    create_realization_workbook(
        realization_path,
        document="Реализация товаров и услуг 00АМ-000017 от 31.01.2026 21:00:00",
    )
    create_cost_workbook(cost_path)

    exports = parse_exports({"realization": realization_path, "cost": cost_path})
    result = build_facts(exports)
    revenue = [fact for fact in result.facts if fact.kpi_l1 == "Выручка"]
    assert revenue
    assert revenue[0].direction == "Услуги"
    assert revenue[0].project_group == "Обслуживание"


def test_cost_direction_via_contract_chain(tmp_path: Path):
    from almabi_pipeline import build_facts
    from almabi_export_parsers import parse_exports

    paths = {
        "buh": tmp_path / "buh.xlsx",
        "realization": tmp_path / "realization.xlsx",
        "cost": tmp_path / "cost.xlsx",
    }
    create_buh_workbook(paths["buh"])
    create_realization_workbook(paths["realization"])
    create_cost_workbook(paths["cost"])

    result = build_facts(parse_exports(paths))
    cost = [fact for fact in result.facts if fact.kpi_l1 == "Себестоимость"]
    assert len(cost) == 1
    assert cost[0].direction == "Услуги"
    assert cost[0].project == "Обслуживание Долго"
    assert cost[0].contract == "Д-001"


def test_cost_is_not_duplicated_when_buh_line_has_no_cost_join(tmp_path: Path):
    from almabi_pipeline import build_facts
    from almabi_export_parsers import parse_exports

    buh_path = tmp_path / "buh.xlsx"
    cost_path = tmp_path / "cost.xlsx"
    realization_path = tmp_path / "realization.xlsx"

    create_buh_workbook(buh_path)
    create_realization_workbook(realization_path)
    create_cost_workbook(cost_path, document="Реализация товаров и услуг 00АМ-000017 от 31.01.2026 21:00:00")

    workbook = Workbook()
    sheet = workbook.active
    _pad_rows(sheet, 8)
    headers = [
        "Документ",
        "Счет Дт",
        "Вид субконто2 Дт",
        "Субконто2 Дт",
        "Счет Кт",
        "Вид субконто1 Кт",
        "Субконто1 Кт",
        "Дата",
        "Сумма",
        "Сумма НУ Дт",
        "Сумма НУ Кт",
    ]
    sheet.append(headers)
    document = "Реализация товаров и услуг 00АМ-000017 от 31.01.2026 21:00:00"
    sheet.append(
        [
            document,
            "90.02.1",
            "Варианты налогообложения прибыли",
            "Общие условия налогообложения",
            "43",
            "Типы затрат",
            "Прямые",
            "15.01.2026",
            542_000_000,
            0,
            542_000_000,
        ]
    )
    sheet.append(["Итого"])
    workbook.save(buh_path)

    exports = parse_exports({"buh": buh_path, "realization": realization_path, "cost": cost_path})
    result = build_facts(exports)
    cost_facts = [fact for fact in result.facts if fact.kpi_l1 == "Себестоимость"]

    assert len(cost_facts) == 1
    assert cost_facts[0].amount_buh == -542_000_000


def _max_tree_level(node: dict) -> int:
    children = node.get("children") or []
    if not children:
        return int(node["level"])
    return max(_max_tree_level(child) for child in children)


def test_summary_hierarchy_levels_match_spec(tmp_path: Path):
    paths = {
        "buh": tmp_path / "buh.xlsx",
        "realization": tmp_path / "realization.xlsx",
        "cost": tmp_path / "cost.xlsx",
    }
    create_buh_workbook(paths["buh"])
    create_realization_workbook(paths["realization"])
    create_cost_workbook(paths["cost"])

    dashboard = load_almabi_dashboard_from_exports(
        paths,
        upload_names={key: path.name for key, path in paths.items()},
    )
    rows = {row["name"]: row for row in dashboard["summary_rows"]}

    assert _max_tree_level(rows["Выручка"]) == 5
    assert _max_tree_level(rows["Себестоимость"]) == 5
    assert rows["Выручка"]["children"][0]["level"] == 2
    assert rows["Себестоимость"]["children"][0]["level"] == 2
    assert _max_tree_level(rows["Коммерческие расходы"]) == 3
    assert _max_tree_level(rows["Операционная прибыль"]) == 3
    commercial = rows["Коммерческие расходы"]
    nelf = next(child for child in commercial["children"] if "Нельгот" in child["name"])
    assert nelf["children"], "Под льготными/нельготными должны быть договоры"
    assert _max_tree_level(rows["Прочие доходы"]) >= 2
    assert _max_tree_level(rows["Чистая прибыль"]) == 3


def test_dashboard_builder_from_exports(tmp_path: Path):
    paths = {
        "buh": tmp_path / "buh.xlsx",
        "realization": tmp_path / "realization.xlsx",
        "cost": tmp_path / "cost.xlsx",
    }
    create_buh_workbook(paths["buh"])
    create_realization_workbook(paths["realization"])
    create_cost_workbook(paths["cost"])

    dashboard = load_almabi_dashboard_from_exports(
        paths,
        upload_names={key: path.name for key, path in paths.items()},
    )

    assert dashboard["meta"]["parsed"] is True
    assert len(dashboard["summary_rows"]) == 10
    revenue = next(row for row in dashboard["summary_rows"] if row["name"] == "Выручка")
    assert revenue["total_fact"] == 1_000_000
    cost = next(row for row in dashboard["summary_rows"] if row["name"] == "Себестоимость")
    assert cost["total_fact"] == -400_000
    assert "Услуги" in {child["name"] for child in revenue["children"]}
    assert dashboard["contractor_details"]
    assert dashboard["contractor_cards"]
    assert any(item["contractor"] == "ООО Тест Клиент" for item in dashboard["contractor_details"])
    privileged = next(card for card in dashboard["contractor_cards"] if "льгот" in card["title"].casefold() and "нельгот" not in card["title"].casefold())
    assert privileged["total"] == 1_000_000
    assert privileged["rows"][0]["name"] == "ООО Тест Клиент"


def test_amortization_workbook_is_not_accepted(tmp_path: Path):
    path = tmp_path / "amort.xlsx"
    create_amort_workbook(path)
    with pytest.raises(ValueError, match="не похож"):
        validate_almabi_export(path)


def test_upload_bundle_accepts_misplaced_export_file(app_client, tmp_path: Path):
    files = {
        "buh_file": ("buh.xlsx", _workbook_bytes(create_buh_workbook, tmp_path / "buh.xlsx")),
        "realization_file": ("cost.xlsx", _workbook_bytes(create_cost_workbook, tmp_path / "cost.xlsx")),
        "cost_file": ("realization.xlsx", _workbook_bytes(create_realization_workbook, tmp_path / "realization.xlsx")),
    }

    response = app_client.post("/api/almabi/files/upload-set", files=files)
    assert response.status_code == 201
    payload = response.json()
    assert payload["saved_exports"]["cost"]["original"] == "cost.xlsx"
    assert payload["saved_exports"]["cost"]["selected_slot"] == "realization"
    assert payload["saved_exports"]["realization"]["original"] == "realization.xlsx"
    assert payload["saved_exports"]["realization"]["selected_slot"] == "cost"
    assert len(payload.get("warnings", [])) >= 2


def test_upload_bundle_builds_dashboard(app_client, tmp_path: Path):
    files = {
        "buh_file": ("buh.xlsx", _workbook_bytes(create_buh_workbook, tmp_path / "buh.xlsx")),
        "realization_file": ("realization.xlsx", _workbook_bytes(create_realization_workbook, tmp_path / "realization.xlsx")),
        "cost_file": ("cost.xlsx", _workbook_bytes(create_cost_workbook, tmp_path / "cost.xlsx")),
    }

    response = app_client.post("/api/almabi/files/upload-set", files=files)
    assert response.status_code == 201
    payload = response.json()
    assert payload["is_complete"] is True
    assert set(payload["upload_files"]) == {"buh", "realization", "cost"}

    dashboard = app_client.get("/dashboard/almabi-test")
    assert dashboard.status_code == 200
    assert "Выручка" in dashboard.text
    assert "Услуги" in dashboard.text
    assert "ООО Тест Клиент" in dashboard.text


def _workbook_bytes(factory, path: Path) -> bytes:
    factory(path)
    return path.read_bytes()
