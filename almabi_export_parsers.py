from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from almabi_excel_utils import (
    analytics_value,
    build_column_map,
    cell_value,
    find_subconto_value,
    month_name,
    normalize_header,
    normalize_text,
    parse_amount,
    parse_date,
    parse_date_from_text,
    read_sheet_rows,
    resolve_column_map,
)

PROJECT_ALIASES = {
    "проект": ("проект", "проекты.проект", "project"),
    "группа проектов": ("группа проектов", "проекты.группа проектов", "project group"),
    "направление": ("направление", "направление деятельности", "проекты.направление", "direction"),
}


def _joined(headers: list[str]) -> str:
    return " | ".join(headers)


def _is_buh_header(headers: list[str]) -> bool:
    joined = _joined(headers)
    return "документ" in joined and "сумма" in joined and "счет дт" in joined


def _is_realization_header(headers: list[str]) -> bool:
    joined = _joined(headers)
    return "выручка" in joined and (
        "номенклатура" in joined
        or "заказ клиента" in joined
        or "группа проектов" in joined
        or "направление" in joined
    )


def _is_cost_header(headers: list[str]) -> bool:
    joined = _joined(headers)
    return ("документ отгрузки" in joined or ("продукция" in joined and "себестоимость" in joined)) and (
        "себестоимость (бухг" in joined
        or "себестоимость (регл" in joined
        or "себестоимость полная" in joined
    )


def _is_amort_header(headers: list[str]) -> bool:
    joined = _joined(headers)
    if "документ отгрузки" in joined or "себестоимость (бухг" in joined:
        return False
    return "статья расходов" in joined and (
        "направление деятельности" in joined
        or "стоимость (регл.) приход" in joined
        or "регистратор" in joined
    )


def _read_project_fields(row: tuple[object, ...], column_map: dict[str, int]) -> tuple[str, str, str]:
    return (
        analytics_value(cell_value(row, column_map, "направление"), default="Без направления"),
        analytics_value(cell_value(row, column_map, "группа проектов"), default="Без группы"),
        analytics_value(cell_value(row, column_map, "проект"), default="Без проекта"),
    )


@dataclass(frozen=True)
class BuhRow:
    document: str
    account_dt: str
    account_kt: str
    amount_buh: float
    amount_nu_dt: float
    amount_nu_kt: float
    month: str | None
    tax_type: str
    expense_article: str
    contract: str
    project: str
    nomenclature_kt: str
    contractor: str


@dataclass(frozen=True)
class RealizationRow:
    document: str
    nomenclature: str
    project: str
    project_group: str
    direction: str
    revenue: float
    month: str | None


@dataclass(frozen=True)
class CostRow:
    document: str
    nomenclature: str
    account: str
    calc_article: str
    quantity: float
    amount: float
    month: str | None
    cost_section: str
    direction: str = "Без направления"
    project_group: str = "Без группы"
    project: str = "Без проекта"


@dataclass(frozen=True)
class AmortRow:
    month: str | None
    expense_article: str
    subdivision: str
    amount_nu: float
    amort_section: str


@dataclass
class ParsedExports:
    buh: list[BuhRow] = field(default_factory=list)
    realization: list[RealizationRow] = field(default_factory=list)
    cost: list[CostRow] = field(default_factory=list)
    amortization: list[AmortRow] = field(default_factory=list)


def classify_buh_section(account_dt: str, account_kt: str) -> str | None:
    if account_dt == "90.02.1":
        return "Себестоимость"
    if account_kt == "90.01.3":
        return "Выручка"
    if account_kt == "91.01":
        return "Прочие доходы"
    if account_dt == "91.02":
        return "Прочие расходы"
    if account_dt == "90.07.1":
        return "Коммерческие расходы"
    if account_dt == "90.08.1":
        return "Управленческие расходы"
    return None


def classify_cost_section(calc_article: str, account: str) -> str:
    article = calc_article.casefold()
    account_value = account.strip()
    if any(token in article for token in ("материал", "сырь", "сырье")) or account_value in {"10", "20", "10.01", "20.01"}:
        return "Материальные затраты"
    if any(token in article for token in ("фот", "оплат", "труд", "зарплат")):
        return "ФОТ"
    if "аренд" in article:
        return "Аренда (прямые)"
    if "амортиз" in article:
        return "Амортизация"
    return "Общепроизводственные затраты"


def classify_amort_section(expense_article: str) -> str:
    if "ноу-хау" in expense_article.casefold():
        return "08 Амортизация НМА"
    return "08 Амортизация ОС"


def _extract_tax_type(column_map: dict[str, int], row: tuple[object, ...]) -> str:
    for side in ("дт", "кт"):
        value = find_subconto_value(column_map, row, side=side, kind_marker="налогооблож")
        if value:
            return value
    return "Общие условия налогообложения"


def _extract_expense_article(column_map: dict[str, int], row: tuple[object, ...]) -> str:
    for side in ("дт", "кт"):
        value = find_subconto_value(column_map, row, side=side, kind_marker="статьи затрат")
        if value:
            return value
    return ""


def _extract_contract(column_map: dict[str, int], row: tuple[object, ...]) -> str:
    direct = normalize_text(cell_value(row, column_map, "договор", "contract"))
    if direct:
        return direct
    for side in ("дт", "кт"):
        value = find_subconto_value(column_map, row, side=side, kind_marker="договор")
        if value:
            return value
    return ""


def _extract_contractor(column_map: dict[str, int], row: tuple[object, ...]) -> str:
    for side in ("дт", "кт"):
        value = find_subconto_value(column_map, row, side=side, kind_marker="контрагент")
        if value:
            return value
    direct = normalize_text(cell_value(row, column_map, "контрагент", "контрагенты", "покупатель", "клиент"))
    if direct:
        return direct
    for side in ("дт", "кт"):
        for level in (1, 2, 3):
            kind = normalize_text(cell_value(row, column_map, f"вид субконто{level} {side}"))
            if "контрагент" in kind.casefold():
                return normalize_text(cell_value(row, column_map, f"субконто{level} {side}"))
    return ""


def _extract_nomenclature_kt(column_map: dict[str, int], row: tuple[object, ...]) -> str:
    value = find_subconto_value(column_map, row, side="кт", kind_marker="номенклатур")
    if value:
        return value
    return normalize_text(cell_value(row, column_map, "субконто1 кт"))


def parse_buh_register(path: Path) -> list[BuhRow]:
    headers, rows = read_sheet_rows(path, skip_rows=8, remove_last=1, header_matcher=_is_buh_header)
    column_map = build_column_map(normalize_header(item) for item in headers)
    parsed: list[BuhRow] = []

    for row in rows:
        document = normalize_text(cell_value(row, column_map, "документ", "document"))
        if not document:
            continue
        amount_buh = parse_amount(cell_value(row, column_map, "сумма", "sum buh"))
        amount_nu_dt = parse_amount(cell_value(row, column_map, "сумма ну дт", "sum nu dt"))
        amount_nu_kt = parse_amount(cell_value(row, column_map, "сумма ну кт", "sum nu kt"))
        if not amount_buh and not amount_nu_dt and not amount_nu_kt:
            continue

        parsed.append(
            BuhRow(
                document=document,
                account_dt=normalize_text(cell_value(row, column_map, "счет дт", "account dt")),
                account_kt=normalize_text(cell_value(row, column_map, "счет кт", "account kt")),
                amount_buh=amount_buh,
                amount_nu_dt=amount_nu_dt,
                amount_nu_kt=amount_nu_kt,
                month=month_name(parse_date(cell_value(row, column_map, "дата", "date"))),
                tax_type=_extract_tax_type(column_map, row),
                expense_article=_extract_expense_article(column_map, row),
                contract=_extract_contract(column_map, row),
                project=normalize_text(
                    cell_value(row, column_map, "проект (договоры с контрагентами)", "project")
                ),
                nomenclature_kt=_extract_nomenclature_kt(column_map, row),
                contractor=_extract_contractor(column_map, row),
            )
        )
    return parsed


def _map_realization_headers(headers: list[str]) -> dict[str, int]:
    aliases = {
        "документ": (
            "заказ клиента / реализация",
            "заказ клиента",
            "реализация товаров и услуг",
            "реализация",
            "документ",
            "document",
        ),
        "номенклатура": ("номенклатура", "sku", "продукция"),
        "выручка": ("выручка", "revenue"),
        "дата": ("регистратор.дата", "дата", "date"),
        **PROJECT_ALIASES,
    }
    return resolve_column_map(headers, aliases)


def _resolve_month(document: str, raw_date: object) -> str | None:
    return month_name(parse_date(raw_date)) or month_name(parse_date_from_text(document))


def parse_realization(path: Path) -> list[RealizationRow]:
    headers, rows = read_sheet_rows(path, skip_rows=7, remove_last=1, header_matcher=_is_realization_header)
    column_map = _map_realization_headers(headers)
    parsed: list[RealizationRow] = []

    for row in rows:
        document = normalize_text(cell_value(row, column_map, "документ"))
        revenue = parse_amount(cell_value(row, column_map, "выручка"))
        if not document or not revenue:
            continue
        direction, project_group, project = _read_project_fields(row, column_map)
        parsed.append(
            RealizationRow(
                document=document,
                nomenclature=normalize_text(cell_value(row, column_map, "номенклатура")),
                project=project,
                project_group=project_group,
                direction=direction,
                revenue=revenue,
                month=_resolve_month(document, cell_value(row, column_map, "дата")),
            )
        )
    return parsed


def _map_cost_headers(headers: list[str]) -> dict[str, int]:
    aliases = {
        "номенклатура": ("продукция", "номенклатура", "sku"),
        "счет": ("счет", "account"),
        "статья калькуляции": ("статья калькуляции", "calc article"),
        "документ": ("документ отгрузки", "документ", "document", "реализация"),
        "количество": ("количество продаж", "количество", "quantity"),
        "сумма": (
            "себестоимость (бухг. учет)",
            "себестоимость (регл. учет)",
            "себестоимость полная",
            "себестоимость",
            "сумма",
            "sum",
        ),
        "дата": ("дата", "date", "регистратор.дата", "дата записи"),
        **PROJECT_ALIASES,
    }
    return resolve_column_map(headers, aliases)


def parse_cost(path: Path) -> list[CostRow]:
    headers, rows = read_sheet_rows(path, skip_rows=5, remove_last=38, header_matcher=_is_cost_header)
    column_map = _map_cost_headers(headers)
    parsed: list[CostRow] = []

    for row in rows:
        document = normalize_text(cell_value(row, column_map, "документ"))
        amount = parse_amount(cell_value(row, column_map, "сумма"))
        if not document or not amount:
            continue
        account = normalize_text(cell_value(row, column_map, "счет")) or "20"
        calc_article = normalize_text(cell_value(row, column_map, "статья калькуляции")) or "Сырье и материалы"
        direction, project_group, project = _read_project_fields(row, column_map)
        parsed.append(
            CostRow(
                document=document,
                nomenclature=normalize_text(cell_value(row, column_map, "номенклатура")),
                account=account,
                calc_article=calc_article,
                quantity=parse_amount(cell_value(row, column_map, "количество")),
                amount=amount,
                month=_resolve_month(document, cell_value(row, column_map, "дата")),
                cost_section=classify_cost_section(calc_article, account),
                direction=direction,
                project_group=project_group,
                project=project,
            )
        )
    return parsed


def _map_amort_headers(headers: list[str]) -> dict[str, int]:
    aliases = {
        "дата": ("дата записи", "регистратор.дата", "регистратор", "дата", "date"),
        "статья расходов": ("статья расходов", "expense article"),
        "сумма ну": (
            "стоимость (регл.) приход",
            "стоимость запасов",
            "стоимость",
            "сумма ну",
            "amount",
        ),
        "подразделение": ("подразделение", "subdivision"),
        "направление": ("направление деятельности", "направление", "direction"),
    }
    return resolve_column_map(headers, aliases)


def parse_amortization(path: Path) -> list[AmortRow]:
    headers, rows = read_sheet_rows(path, skip_rows=8, remove_last=1, header_matcher=_is_amort_header)
    column_map = _map_amort_headers(headers)
    parsed: list[AmortRow] = []

    for row in rows:
        amount_nu = parse_amount(cell_value(row, column_map, "сумма ну"))
        if not amount_nu:
            continue
        expense_article = normalize_text(cell_value(row, column_map, "статья расходов")) or "Амортизация"
        date_value = cell_value(row, column_map, "дата")
        parsed.append(
            AmortRow(
                month=month_name(parse_date(date_value)) or month_name(parse_date_from_text(date_value)),
                expense_article=expense_article,
                subdivision=normalize_text(cell_value(row, column_map, "подразделение")),
                amount_nu=amount_nu,
                amort_section=classify_amort_section(expense_article),
            )
        )
    return parsed


def parse_exports(paths: dict[str, Path]) -> ParsedExports:
    return ParsedExports(
        buh=parse_buh_register(paths["buh"]) if "buh" in paths else [],
        realization=parse_realization(paths["realization"]) if "realization" in paths else [],
        cost=parse_cost(paths["cost"]) if "cost" in paths else [],
        amortization=parse_amortization(paths["amortization"]) if "amortization" in paths else [],
    )
