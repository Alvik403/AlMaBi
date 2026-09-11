from __future__ import annotations

from dataclasses import dataclass

from almabi_excel_utils import contract_match_keys, document_match_keys, normalize_text
from almabi_export_parsers import BuhRow, CostRow, RealizationRow


@dataclass
class RealizationIndex:
    by_exact_operation: dict[tuple[str, str], RealizationRow]
    by_document_nomenclature: dict[tuple[str, str], RealizationRow]
    by_document: dict[str, RealizationRow]
    by_contract_nomenclature: dict[tuple[str, str], RealizationRow]
    by_contract: dict[str, RealizationRow]


def _register_row(
    target: dict,
    key: object,
    row: RealizationRow,
) -> None:
    target.setdefault(key, row)


def _contracts_for_row(row: RealizationRow, doc_contract: dict[str, str]) -> list[str]:
    contracts: list[str] = []
    if row.contract:
        contracts.append(row.contract)
    row_keys = document_match_keys(row.document)
    for document, contract in doc_contract.items():
        if contract and row_keys & document_match_keys(document):
            contracts.append(contract)
    return contracts


def build_realization_index(
    realization_rows: list[RealizationRow],
    doc_contract: dict[str, str],
) -> RealizationIndex:
    by_exact_operation: dict[tuple[str, str], RealizationRow] = {}
    by_document_nomenclature: dict[tuple[str, str], RealizationRow] = {}
    by_document: dict[str, RealizationRow] = {}
    by_contract_nomenclature: dict[tuple[str, str], RealizationRow] = {}
    by_contract: dict[str, RealizationRow] = {}

    for row in realization_rows:
        nomenclature = row.nomenclature.casefold()
        if nomenclature:
            exact_document = normalize_text(row.document).casefold()
            if exact_document:
                _register_row(by_exact_operation, (exact_document, nomenclature), row)
            for doc_key in document_match_keys(row.document):
                _register_row(by_document_nomenclature, (doc_key, nomenclature), row)
        for doc_key in document_match_keys(row.document):
            _register_row(by_document, doc_key, row)

        for contract in _contracts_for_row(row, doc_contract):
            for contract_key in contract_match_keys(contract):
                _register_row(by_contract, contract_key, row)
                if nomenclature:
                    _register_row(by_contract_nomenclature, (contract_key, nomenclature), row)

    return RealizationIndex(
        by_exact_operation=by_exact_operation,
        by_document_nomenclature=by_document_nomenclature,
        by_document=by_document,
        by_contract_nomenclature=by_contract_nomenclature,
        by_contract=by_contract,
    )


def _revenue_amounts_match(left: float, right: float) -> bool:
    left_abs = abs(float(left or 0))
    right_abs = abs(float(right or 0))
    if left_abs < 1e-9 or right_abs < 1e-9:
        return False
    if abs(left_abs - right_abs) < 0.02:
        return True
    # Выручка в бухрегистре может быть с НДС, в «Реализация проекты» — без.
    if abs(left_abs - right_abs * 1.2) < 0.02:
        return True
    if abs(left_abs * 1.2 - right_abs) < 0.02:
        return True
    return False


def lookup_realization_for_revenue_amount(
    *,
    document: str,
    amount_buh: float,
    amount_nu: float,
    rows: list[RealizationRow],
) -> RealizationRow | None:
    """Подобрать строку реализации по документу и сумме выручки."""
    if not document or not rows:
        return None
    doc_keys = document_match_keys(document)
    if not doc_keys:
        return None
    candidates = [
        row
        for row in rows
        if document_match_keys(row.document) & doc_keys and normalize_text(row.nomenclature)
    ]
    if not candidates:
        return None

    amount_targets = [float(amount_nu or 0), float(amount_buh or 0)]
    amount_matches = [
        row
        for row in candidates
        if any(_revenue_amounts_match(target, float(row.revenue or 0)) for target in amount_targets)
    ]
    if len(amount_matches) == 1:
        return amount_matches[0]
    if len(amount_matches) > 1:
        return amount_matches[0]
    if len(candidates) == 1:
        return candidates[0]
    return None


def lookup_exact_realization_operation(
    *,
    document: str,
    nomenclature: str,
    index: RealizationIndex,
) -> RealizationRow | None:
    """Строгое совпадение операции для полей новой расшифровки."""
    key = (normalize_text(document).casefold(), normalize_text(nomenclature).casefold())
    if not all(key):
        return None
    return index.by_exact_operation.get(key)


def lookup_realization_row(
    *,
    document: str,
    nomenclature: str = "",
    contract: str = "",
    index: RealizationIndex,
) -> RealizationRow | None:
    """Поиск строки «Реализация проекты»: договор+номенклатура → договор → документ+номенклатура → документ."""
    nom = nomenclature.casefold()

    if contract and nom:
        for contract_key in contract_match_keys(contract):
            match = index.by_contract_nomenclature.get((contract_key, nom))
            if match is not None:
                return match

    if contract:
        for contract_key in contract_match_keys(contract):
            match = index.by_contract.get(contract_key)
            if match is not None:
                return match

    if nom:
        for doc_key in document_match_keys(document):
            match = index.by_document_nomenclature.get((doc_key, nom))
            if match is not None:
                return match

    for doc_key in document_match_keys(document):
        match = index.by_document.get(doc_key)
        if match is not None:
            return match

    return None


def resolve_realization_match(
    *,
    buh_row: BuhRow,
    cost_match: CostRow | None,
    buh_contract: str,
    index: RealizationIndex,
    prefer_cost_chain: bool = False,
) -> RealizationRow | None:
    """
    Цепочка для себестоимости: cost (продукция) → договор → реализация проекты.
    Для доходов: документ (+ номенклатура) → реализация, с опциональным договором.
    """
    if cost_match and prefer_cost_chain:
        contract = cost_match.contract or buh_contract
        match = lookup_realization_row(
            document=cost_match.document,
            nomenclature=cost_match.nomenclature,
            contract=contract,
            index=index,
        )
        if match is not None:
            return match

    match = lookup_realization_row(
        document=buh_row.document,
        nomenclature=buh_row.nomenclature_kt,
        contract=buh_contract,
        index=index,
    )
    if match is not None:
        return match

    if cost_match and not prefer_cost_chain:
        contract = cost_match.contract or buh_contract
        return lookup_realization_row(
            document=cost_match.document,
            nomenclature=cost_match.nomenclature,
            contract=contract,
            index=index,
        )

    return None
