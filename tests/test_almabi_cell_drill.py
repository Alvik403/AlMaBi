from __future__ import annotations

from almabi_dashboard_builder import (
    NON_PRIVILEGED_BUCKET,
    PRIVILEGED_BUCKET,
    _build_drill_data,
    _build_revenue_cost_drill,
    _build_summary_rows,
)
from almabi_pipeline import Fact


def _fact(**kwargs: object) -> Fact:
    defaults = {
        "kpi_l1": "Прочие расходы",
        "month": "Январь",
        "amount_buh": -100.0,
        "amount_nu": -100.0,
        "expense_article": "Проценты",
        "tax_type": "Общие условия налогообложения",
    }
    defaults.update(kwargs)
    return Fact(**defaults)  # type: ignore[arg-type]


def test_build_drill_data_splits_articles_by_tax_bucket():
    drill = _build_drill_data(
        [
            _fact(
                expense_article="Проценты",
                tax_type="Доходы по льготируемым видам деятельности",
                amount_buh=-50,
                amount_nu=-40,
            ),
            _fact(
                expense_article="Проценты",
                tax_type="Общие условия налогообложения",
                amount_buh=-150,
                amount_nu=-120,
            ),
            _fact(
                expense_article="Штрафы",
                month="Февраль",
                amount_buh=-20,
                amount_nu=-20,
            ),
        ]
    )

    jan = drill["months"]["Январь"]["articles"]
    interest = next(item for item in jan if item["name"] == "Проценты")
    assert interest[PRIVILEGED_BUCKET]["buh"] == -50
    assert interest[NON_PRIVILEGED_BUCKET]["buh"] == -150

    feb = drill["months"]["Февраль"]["articles"]
    assert len(feb) == 1
    assert feb[0]["name"] == "Штрафы"


def test_build_drill_data_sorts_articles_by_abs_amount_desc():
    drill = _build_drill_data(
        [
            _fact(expense_article="Малый", amount_buh=-10, amount_nu=-10),
            _fact(expense_article="Крупный", amount_buh=-500, amount_nu=-500),
            _fact(expense_article="Средний", amount_buh=-100, amount_nu=-100),
        ]
    )
    names = [item["name"] for item in drill["total"]["articles"]]
    assert names == ["Крупный", "Средний", "Малый"]


def test_build_revenue_cost_drill_pairs_nomenclature_lines():
    drill = _build_revenue_cost_drill(
        [
            _fact(
                kpi_l1="Выручка",
                direction="Услуги",
                project_group="Обслуживание",
                project="Обслуживание Долго",
                nomenclature="Лицензия А",
                amount_buh=1_000_000,
                amount_nu=1_000_000,
                quantity=1,
            ),
            _fact(
                kpi_l1="Выручка",
                direction="Услуги",
                project_group="Обслуживание",
                project="Обслуживание Долго",
                nomenclature="Лицензия Б",
                amount_buh=200_000,
                amount_nu=200_000,
                quantity=1,
            ),
        ],
        [
            _fact(
                kpi_l1="Себестоимость",
                direction="Услуги",
                project_group="Обслуживание",
                project="Обслуживание Долго",
                nomenclature="Лицензия А",
                amount_buh=-400_000,
                amount_nu=-400_000,
                quantity=1,
            ),
            _fact(
                kpi_l1="Себестоимость",
                direction="Услуги",
                project_group="Обслуживание",
                project="Обслуживание Долго",
                nomenclature="Лицензия Б",
                amount_buh=-50_000,
                amount_nu=-50_000,
                quantity=2,
            ),
        ],
    )

    assert drill["type"] == "revenue_cost"
    lines = drill["total"]["lines"]
    assert [item["name"] for item in lines] == ["Лицензия А", "Лицензия Б"]

    first = lines[0]
    assert first["quantity"] == 1
    assert first["revenue"]["buh"] == 1_000_000
    assert first["cost"]["buh"] == 400_000
    assert first["profit"]["buh"] == 600_000
    assert first["margin"]["buh"] == 60.0

    tree = drill["total"]["tree"]
    assert len(tree) == 1
    assert tree[0]["name"] == "Услуги"
    assert tree[0]["expandable"] is True
    assert tree[0]["revenue"]["buh"] == 1_200_000
    group = tree[0]["children"][0]
    assert group["name"] == "Обслуживание"
    project = group["children"][0]
    assert project["name"] == "Обслуживание Долго"
    assert project["expandable"] is True
    leaves = project["children"]
    assert [item["name"] for item in leaves] == ["Лицензия А", "Лицензия Б"]
    assert leaves[0]["expandable"] is False
    assert leaves[1]["quantity"] == 2
    assert leaves[1]["profit"]["buh"] == 150_000


def test_build_revenue_cost_drill_merges_oez_nomenclature_variants():
    drill = _build_revenue_cost_drill(
        [
            _fact(
                kpi_l1="Выручка",
                direction="Услуги",
                nomenclature="ОЭЗ Работы по техническому обслуживанию",
                amount_buh=12_000_000,
                amount_nu=10_000_000,
                quantity=1,
            ),
        ],
        [
            _fact(
                kpi_l1="Себестоимость",
                direction="Услуги",
                nomenclature="ОЭЗ (ппу) Работы по техническому обслуживанию, ремонту ппу",
                amount_buh=-4_289_833,
                amount_nu=-4_289_833,
                quantity=1,
            ),
            _fact(
                kpi_l1="Себестоимость",
                direction="Услуги",
                nomenclature="ОЭЗ Работы по техническому обслуживанию",
                amount_buh=-2_711_292,
                amount_nu=-2_711_292,
                quantity=1,
            ),
        ],
    )

    lines = drill["total"]["lines"]
    assert len(lines) == 1
    line = lines[0]
    assert line["name"] == "ОЭЗ Работы по техническому обслуживанию"
    assert line["revenue"]["buh"] == 10_000_000
    assert line["cost"]["buh"] == 4_289_833 + 2_711_292
    assert line["quantity"] == 1


def test_build_revenue_cost_drill_uses_ex_vat_revenue_amount():
    drill = _build_revenue_cost_drill(
        [
            _fact(
                kpi_l1="Выручка",
                nomenclature="Комплект А",
                amount_buh=1_220_000,
                amount_nu=1_000_000,
                quantity=3,
            ),
        ],
        [
            _fact(
                kpi_l1="Себестоимость",
                nomenclature="Комплект А",
                amount_buh=-400_000,
                amount_nu=-400_000,
                quantity=3,
            ),
        ],
    )
    line = drill["total"]["lines"][0]
    assert line["revenue"]["buh"] == 1_000_000
    assert line["revenue"]["nu"] == 1_000_000
    assert line["revenue"]["buh"] != 1_220_000
    assert line["cost"]["buh"] == 400_000
    assert line["profit"]["buh"] == 600_000
    assert line["quantity"] == 3


def test_summary_rows_include_drill_only_for_allowed_kpis():
    rows = _build_summary_rows(
        [
            _fact(
                kpi_l1="Коммерческие расходы",
                contract="Договор 1",
                expense_article="",
                amount_buh=-300,
            ),
            _fact(
                kpi_l1="Коммерческие расходы",
                contract="Договор 2",
                expense_article="",
                tax_type="Доходы по льготируемым видам деятельности",
                amount_buh=-100,
            ),
            _fact(
                kpi_l1="Прочие расходы",
                expense_article="Штрафы",
                amount_buh=-50,
            ),
            _fact(
                kpi_l1="Прочие доходы",
                expense_article="Проценты",
                amount_buh=400,
                amount_nu=400,
            ),
            _fact(
                kpi_l1="Выручка",
                direction="Услуги",
                nomenclature="Лицензия ПО",
                amount_buh=1_000,
                amount_nu=1_000,
                quantity=1,
            ),
            _fact(
                kpi_l1="Выручка",
                direction="Товары",
                nomenclature="Товар А",
                amount_buh=200,
                amount_nu=200,
                quantity=1,
            ),
            _fact(
                kpi_l1="Себестоимость",
                direction="Услуги",
                nomenclature="Лицензия ПО",
                amount_buh=-400,
                amount_nu=-400,
                quantity=1,
            ),
        ]
    )
    by_name = {row["name"]: row for row in rows}

    commercial = by_name["Коммерческие расходы"]
    assert "drill" in commercial
    assert commercial["drill"]["type"] == "articles"
    articles = commercial["drill"]["total"]["articles"]
    assert [item["name"] for item in articles] == ["Договор 1", "Договор 2"]

    assert "drill" not in by_name["Операционная прибыль"]

    income = by_name["Прочие доходы"]
    expense = by_name["Прочие расходы"]
    assert income["drill"]["type"] == "other_pnl"
    assert expense["drill"]["type"] == "other_pnl"
    assert income["drill"] is expense["drill"]
    sections = {section["name"]: section for section in income["drill"]["total"]["sections"]}
    assert sections["Прочие доходы"]["articles"][0]["name"] == "Проценты"
    assert sections["Прочие расходы"]["articles"][0]["name"] == "Штрафы"

    revenue = by_name["Выручка"]
    cost = by_name["Себестоимость"]
    assert revenue["drill"]["type"] == "revenue_cost"
    assert cost["drill"]["type"] == "revenue_cost"
    lines = revenue["drill"]["total"]["lines"]
    assert lines[0]["name"] == "Лицензия ПО"
    assert lines[0]["revenue"]["buh"] == 1_000
    assert lines[0]["cost"]["buh"] == 400
    assert lines[0]["profit"]["buh"] == 600

    directions = [child["name"] for child in revenue["children"]]
    assert directions == ["Услуги", "Товары"]

    uslugi = next(child for child in revenue["children"] if child["name"] == "Услуги")
    assert uslugi["drill"]["type"] == "revenue_cost"
    assert uslugi["drill"]["total"]["path"] == ["project_group", "project"]
    uslugi_lines = uslugi["drill"]["total"]["lines"]
    assert [line["name"] for line in uslugi_lines] == ["Лицензия ПО"]
    assert uslugi_lines[0]["revenue"]["buh"] == 1_000

    tovary = next(child for child in revenue["children"] if child["name"] == "Товары")
    assert [line["name"] for line in tovary["drill"]["total"]["lines"]] == ["Товар А"]
    assert tovary["drill"]["total"]["lines"][0]["revenue"]["buh"] == 200


def test_revenue_cost_level_drills_follow_hierarchy():
    rows = _build_summary_rows(
        [
            _fact(
                kpi_l1="Выручка",
                direction="Перепродажа",
                project_group="Группа А",
                project="Прочие проекты",
                contract="Договор 1",
                nomenclature="Товар 1",
                amount_buh=1_000,
                amount_nu=1_000,
                quantity=2,
            ),
            _fact(
                kpi_l1="Выручка",
                direction="Перепродажа",
                project_group="Группа А",
                project="Прочие проекты",
                contract="Договор 1",
                nomenclature="Товар 2",
                amount_buh=500,
                amount_nu=500,
                quantity=1,
            ),
            _fact(
                kpi_l1="Выручка",
                direction="Услуги",
                project_group="Группа Б",
                project="Проект Б",
                contract="Договор 2",
                nomenclature="Услуга",
                amount_buh=300,
                amount_nu=300,
                quantity=1,
            ),
            _fact(
                kpi_l1="Себестоимость",
                cost_section="Товары",
                direction="Перепродажа",
                project_group="Группа А",
                project="Прочие проекты",
                nomenclature="Товар 1",
                amount_buh=-400,
                amount_nu=-400,
                quantity=2,
            ),
        ]
    )
    by_name = {row["name"]: row for row in rows}
    revenue = by_name["Выручка"]
    resale = next(child for child in revenue["children"] if child["name"] == "Перепродажа")
    assert resale["drill"]["type"] == "revenue_cost"
    assert resale["drill"]["total"]["path"] == ["project_group", "project"]
    assert {line["name"] for line in resale["drill"]["total"]["lines"]} == {"Товар 1", "Товар 2"}
    resale_lines = {line["name"]: line for line in resale["drill"]["total"]["lines"]}
    assert resale_lines["Товар 1"]["revenue"]["buh"] == 1_000
    assert resale_lines["Товар 1"]["cost"]["buh"] == 400
    assert resale_lines["Товар 2"]["revenue"]["buh"] == 500
    assert resale_lines["Товар 2"]["cost"]["buh"] == 0

    group_a = next(child for child in resale["children"] if child["name"] == "Группа А")
    assert group_a["drill"]["total"]["path"] == ["project"]
    assert {line["name"] for line in group_a["drill"]["total"]["lines"]} == {"Товар 1", "Товар 2"}

    project = next(child for child in group_a["children"] if child["name"] == "Прочие проекты")
    assert project["drill"]["total"]["path"] == []
    assert {line["name"] for line in project["drill"]["total"]["lines"]} == {"Товар 1", "Товар 2"}

    cost = by_name["Себестоимость"]
    assert cost["drill"]["total"]["path"] == ["cost_section", "direction", "project_group"]
    section = next(child for child in cost["children"] if child["name"] == "Товары")
    assert section["drill"]["type"] == "revenue_cost"
    assert section["drill"]["total"]["path"] == ["direction", "project_group"]
    resale_cost = next(child for child in section["children"] if child["name"] == "Перепродажа")
    assert resale_cost["drill"]["total"]["path"] == ["project_group"]
    lines_by_name = {line["name"]: line for line in resale_cost["drill"]["total"]["lines"]}
    assert set(lines_by_name) == {"Товар 1"}
    assert lines_by_name["Товар 1"]["cost"]["buh"] == 400
    assert lines_by_name["Товар 1"]["revenue"]["buh"] == 1_000
    assert lines_by_name["Товар 1"]["profit"]["buh"] == 600


def test_revenue_cost_quantity_keeps_real_values_without_fake_ones():
    drill = _build_revenue_cost_drill(
        [
            _fact(
                kpi_l1="Выручка",
                nomenclature="Товар",
                amount_buh=10_000,
                amount_nu=10_000,
                quantity=12.5,
            ),
            _fact(
                kpi_l1="Выручка",
                nomenclature="Без количества",
                amount_buh=1_000,
                amount_nu=1_000,
                quantity=0,
            ),
        ],
        [
            _fact(
                kpi_l1="Себестоимость",
                nomenclature="Товар",
                amount_buh=-4_000,
                amount_nu=-4_000,
                quantity=12.5,
            ),
        ],
    )
    lines = {line["name"]: line for line in drill["total"]["lines"]}
    assert lines["Товар"]["quantity"] == 12.5
    assert lines["Товар"]["revenue"]["buh"] == 10_000
    assert lines["Товар"]["cost"]["buh"] == 4_000
    assert lines["Без количества"]["quantity"] == 0
    assert lines["Без количества"]["revenue"]["buh"] == 1_000


def test_revenue_drill_hides_cost_only_and_attaches_exact_name():
    drill = _build_revenue_cost_drill(
        [
            _fact(
                kpi_l1="Выручка",
                direction="Услуги",
                nomenclature="Настольный ЯМР Spinsolve",
                amount_buh=341_849,
                amount_nu=341_849,
                quantity=1,
            ),
        ],
        [
            _fact(
                kpi_l1="Себестоимость",
                direction="Перепродажа",
                nomenclature="Настольный ЯМР Spinsolve",
                amount_buh=-40_000,
                amount_nu=-40_000,
                quantity=1,
            ),
            _fact(
                kpi_l1="Себестоимость",
                direction="Перепродажа",
                nomenclature="139570, Набор цветных фильтров Pt-Co",
                amount_buh=-605,
                amount_nu=-605,
                quantity=1,
            ),
        ],
        base="revenue",
    )
    lines = {line["name"]: line for line in drill["total"]["lines"]}
    assert set(lines) == {"Настольный ЯМР Spinsolve"}
    assert lines["Настольный ЯМР Spinsolve"]["revenue"]["buh"] == 341_849
    assert lines["Настольный ЯМР Spinsolve"]["cost"]["buh"] == 40_000
    assert lines["Настольный ЯМР Spinsolve"]["profit"]["buh"] == 301_849
    assert abs(lines["Настольный ЯМР Spinsolve"]["margin"]["buh"] - 88.3) < 0.05
    tree_names = [node["name"] for node in drill["total"]["tree"]]
    assert tree_names == ["Услуги"]


def test_cost_drill_keeps_cost_rows_and_attaches_matching_revenue():
    drill = _build_revenue_cost_drill(
        [
            _fact(
                kpi_l1="Выручка",
                direction="Услуги",
                nomenclature="Настольный ЯМР Spinsolve",
                amount_buh=341_849,
                amount_nu=341_849,
                quantity=1,
            ),
            _fact(
                kpi_l1="Выручка",
                nomenclature="Только продажа",
                amount_buh=50_000,
                amount_nu=50_000,
                quantity=1,
            ),
        ],
        [
            _fact(
                kpi_l1="Себестоимость",
                nomenclature="Настольный ЯМР Spinsolve",
                amount_buh=-40_000,
                amount_nu=-40_000,
                quantity=1,
            ),
            _fact(
                kpi_l1="Себестоимость",
                nomenclature="139570, Набор цветных фильтров Pt-Co",
                amount_buh=-605,
                amount_nu=-605,
                quantity=1,
            ),
        ],
        base="cost",
    )
    lines = {line["name"]: line for line in drill["total"]["lines"]}
    assert set(lines) == {
        "Настольный ЯМР Spinsolve",
        "139570, Набор цветных фильтров Pt-Co",
    }
    assert lines["Настольный ЯМР Spinsolve"]["revenue"]["buh"] == 341_849
    assert lines["Настольный ЯМР Spinsolve"]["cost"]["buh"] == 40_000
    assert lines["139570, Набор цветных фильтров Pt-Co"]["revenue"]["buh"] == 0
    assert lines["139570, Набор цветных фильтров Pt-Co"]["cost"]["buh"] == 605


def test_revenue_cost_drill_matches_name_case_insensitively():
    drill = _build_revenue_cost_drill(
        [
            _fact(
                kpi_l1="Выручка",
                nomenclature="Лицензия ПО",
                amount_buh=1_000,
                amount_nu=1_000,
                quantity=1,
            ),
        ],
        [
            _fact(
                kpi_l1="Себестоимость",
                nomenclature="лицензия по",
                amount_buh=-400,
                amount_nu=-400,
                quantity=1,
            ),
        ],
    )
    assert len(drill["total"]["lines"]) == 1
    line = drill["total"]["lines"][0]
    assert line["revenue"]["buh"] == 1_000
    assert line["cost"]["buh"] == 400
    assert line["profit"]["buh"] == 600


def test_revenue_month_drill_attaches_same_document_cost_from_later_month():
    drill = _build_revenue_cost_drill(
        [
            _fact(
                kpi_l1="Выручка",
                nomenclature="Настольный двухканальный ЯМР-спектрометр Spinsolve 90 Carbon",
                amount_buh=46_090,
                amount_nu=46_090,
                quantity=1,
                period="2026-01",
                month="Январь",
                document="Реализация 00БП-15 от 15.01.2026",
            ),
        ],
        [
            _fact(
                kpi_l1="Себестоимость",
                nomenclature="Настольный двухканальный ЯМР-спектрометр Spinsolve 90 Carbon",
                amount_buh=-40_000,
                amount_nu=-40_000,
                quantity=1,
                period="2026-02",
                month="Февраль",
                document="Реализация 00БП-15 от 15.01.2026",
            ),
        ],
    )
    january = {line["name"]: line for line in drill["months"]["2026-01"]["lines"]}
    line = january["Настольный двухканальный ЯМР-спектрометр Spinsolve 90 Carbon"]
    assert line["revenue"]["buh"] == 46_090
    assert line["cost"]["buh"] == 40_000
    assert line["profit"]["buh"] == 6_090


def test_revenue_month_drill_does_not_take_other_month_cost_without_document():
    drill = _build_revenue_cost_drill(
        [
            _fact(
                kpi_l1="Выручка",
                nomenclature="Настольный ЯМР Spinsolve",
                amount_buh=46_090,
                amount_nu=46_090,
                quantity=1,
                period="2026-01",
                month="Январь",
            ),
        ],
        [
            _fact(
                kpi_l1="Себестоимость",
                nomenclature="Настольный ЯМР Spinsolve",
                amount_buh=-40_000,
                amount_nu=-40_000,
                quantity=1,
                period="2026-02",
                month="Февраль",
            ),
            _fact(
                kpi_l1="Себестоимость",
                nomenclature="Другой товар",
                amount_buh=-1_000,
                amount_nu=-1_000,
                quantity=1,
                period="2026-01",
                month="Январь",
            ),
        ],
    )
    january = {line["name"]: line for line in drill["months"]["2026-01"]["lines"]}
    assert january["Настольный ЯМР Spinsolve"]["cost"]["buh"] == 0
    assert january["Настольный ЯМР Spinsolve"]["revenue"]["buh"] == 46_090
    assert "Другой товар" not in january


def test_revenue_month_drill_does_not_take_other_year_cost_even_with_document():
    drill = _build_revenue_cost_drill(
        [
            _fact(
                kpi_l1="Выручка",
                nomenclature="Настольный ЯМР Spinsolve",
                amount_buh=46_090,
                amount_nu=46_090,
                quantity=1,
                period="2026-01",
                month="Январь",
                document="Реализация 00БП-15",
            ),
        ],
        [
            _fact(
                kpi_l1="Себестоимость",
                nomenclature="Настольный ЯМР Spinsolve",
                amount_buh=-40_000,
                amount_nu=-40_000,
                quantity=1,
                period="2025-12",
                month="Декабрь",
                document="Реализация 00БП-15",
            ),
        ],
    )
    january = {line["name"]: line for line in drill["months"]["2026-01"]["lines"]}
    assert january["Настольный ЯМР Spinsolve"]["cost"]["buh"] == 0


def test_build_other_pnl_drill_is_shared_for_income_and_expense():
    from almabi_dashboard_builder import _build_other_pnl_drill

    drill = _build_other_pnl_drill(
        [
            _fact(
                kpi_l1="Прочие доходы",
                expense_article="Проценты",
                amount_buh=400_000,
                amount_nu=400_000,
            ),
            _fact(
                kpi_l1="Прочие доходы",
                expense_article="Курсовые разницы",
                tax_type="Доходы по льготируемым видам деятельности",
                amount_buh=50_000,
                amount_nu=50_000,
            ),
        ],
        [
            _fact(
                kpi_l1="Прочие расходы",
                expense_article="Штрафы",
                amount_buh=-20_000,
                amount_nu=-20_000,
            ),
        ],
    )
    assert drill["type"] == "other_pnl"
    sections = {section["name"]: section["articles"] for section in drill["total"]["sections"]}
    assert [item["name"] for item in sections["Прочие доходы"]] == ["Проценты", "Курсовые разницы"]
    assert sections["Прочие расходы"][0]["name"] == "Штрафы"


def test_group_tree_sorts_children_by_abs_amount_desc():
    rows = _build_summary_rows(
        [
            _fact(
                kpi_l1="Себестоимость",
                cost_section="ФОТ",
                amount_buh=-80,
                amount_nu=-80,
            ),
            _fact(
                kpi_l1="Себестоимость",
                cost_section="Материальные затраты",
                amount_buh=-500,
                amount_nu=-500,
            ),
            _fact(
                kpi_l1="Себестоимость",
                cost_section="Аренда (прямые)",
                amount_buh=-120,
                amount_nu=-120,
            ),
        ]
    )
    cost = next(row for row in rows if row["name"] == "Себестоимость")
    assert [child["name"] for child in cost["children"]] == [
        "Материальные затраты",
        "Аренда (прямые)",
        "ФОТ",
    ]
