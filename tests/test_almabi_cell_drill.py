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

    group_a = next(child for child in resale["children"] if child["name"] == "Группа А")
    assert group_a["drill"]["total"]["path"] == ["project"]
    assert {line["name"] for line in group_a["drill"]["total"]["lines"]} == {"Товар 1", "Товар 2"}

    project = next(child for child in group_a["children"] if child["name"] == "Прочие проекты")
    assert project["drill"]["total"]["path"] == []
    assert {line["name"] for line in project["drill"]["total"]["lines"]} == {"Товар 1", "Товар 2"}

    cost = by_name["Себестоимость"]
    resale_cost = next(child for child in cost["children"] if child["name"] == "Перепродажа")
    assert resale_cost["drill"]["type"] == "revenue_cost"
    assert resale_cost["drill"]["total"]["path"] == ["project_group", "project"]
    lines_by_name = {line["name"]: line for line in resale_cost["drill"]["total"]["lines"]}
    assert set(lines_by_name) == {"Товар 1", "Товар 2"}
    assert lines_by_name["Товар 1"]["cost"]["buh"] == 400
    assert lines_by_name["Товар 2"]["cost"]["buh"] == 0


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
                direction="ФОТ",
                amount_buh=-80,
                amount_nu=-80,
            ),
            _fact(
                kpi_l1="Себестоимость",
                direction="Материальные затраты",
                amount_buh=-500,
                amount_nu=-500,
            ),
            _fact(
                kpi_l1="Себестоимость",
                direction="Аренда (прямые)",
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
