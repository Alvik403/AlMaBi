"""Сессия и загрузка для отчёта «Прочие доходы» (3 файла, логика Тест Excel)."""
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, Request, UploadFile

from almabi_file_security import resolve_user_stored_xlsx
from almabi_file_validation import validate_almabi_export
from almabi_other_income_report import DETAIL_COLUMNS, build_other_income_report
from almabi_test_excel_data import (
    SESSION_ALMABI_TEST_EXCEL_BUH,
    _upload_dir as test_excel_upload_dir,
    get_test_excel_buh_meta,
    get_test_excel_buh_path,
    get_test_excel_cost_path,
    get_test_excel_cost_path_for_buh,
    get_test_excel_projects_path_for_cost,
    get_test_excel_revenue_path,
    get_test_excel_revenue_path_for_buh,
)
from settings import Settings

SESSION_ALMABI_OTHER_INCOME_REPORT = "almabi_other_income_report"


def _meta_from_session(request: Request) -> dict[str, str] | None:
    stored = request.session.get(SESSION_ALMABI_OTHER_INCOME_REPORT)
    if not isinstance(stored, dict):
        return None
    original = stored.get("original")
    stored_name = stored.get("stored")
    if not original or not stored_name:
        return None
    return {"original": str(original), "stored": str(stored_name)}


def _path_from_meta(request: Request, settings: Settings, meta: dict[str, str] | None) -> Path | None:
    if meta is None:
        return None
    return resolve_user_stored_xlsx(request, settings.resolved_uploads_dir, "almabi_test_excel", meta["stored"])


def _path_from_session_field(request: Request, settings: Settings, field: str) -> Path | None:
    stored = request.session.get(SESSION_ALMABI_OTHER_INCOME_REPORT)
    if not isinstance(stored, dict):
        return None
    stored_name = stored.get(field)
    if not stored_name:
        return None
    return resolve_user_stored_xlsx(request, settings.resolved_uploads_dir, "almabi_test_excel", stored_name)


def _resolve_buh_path(request: Request, settings: Settings) -> Path | None:
    path = _path_from_meta(request, settings, _meta_from_session(request))
    if path is not None:
        return path
    return get_test_excel_buh_path(request, settings)


def _resolve_cost_path(request: Request, settings: Settings) -> Path | None:
    path = _path_from_session_field(request, settings, "cost_stored")
    if path is not None:
        return path
    return get_test_excel_cost_path_for_buh(request, settings) or get_test_excel_cost_path(request, settings)


def _resolve_revenue_path(request: Request, settings: Settings) -> Path | None:
    path = _path_from_session_field(request, settings, "revenue_stored")
    if path is not None:
        return path
    return get_test_excel_revenue_path_for_buh(request, settings) or get_test_excel_revenue_path(request, settings)


def _file_label(
    request: Request,
    settings: Settings,
    *,
    report_field: str,
    report_original_field: str,
    fallback_session: str,
) -> str | None:
    stored = request.session.get(SESSION_ALMABI_OTHER_INCOME_REPORT)
    if isinstance(stored, dict) and stored.get(report_original_field):
        return str(stored[report_original_field])
    fallback_path = None
    if report_field == "cost_stored":
        fallback_path = get_test_excel_cost_path_for_buh(request, settings)
    elif report_field == "revenue_stored":
        fallback_path = get_test_excel_revenue_path_for_buh(request, settings)
    if fallback_path is None:
        return None
    fallback_meta = request.session.get(fallback_session)
    if isinstance(fallback_meta, dict):
        if report_field == "cost_stored" and fallback_meta.get("cost_original"):
            return str(fallback_meta["cost_original"])
        if report_field == "revenue_stored" and fallback_meta.get("revenue_original"):
            return str(fallback_meta["revenue_original"])
        original = fallback_meta.get("original")
        stored_name = fallback_meta.get("stored")
        if original and stored_name and fallback_path.name == str(stored_name):
            return str(original)
    return None


def _empty_payload() -> dict[str, object]:
    return {
        "loaded": False,
        "file_name": None,
        "cost_file_name": None,
        "revenue_file_name": None,
        "rows": [],
        "tree": [],
        "tree_by_tax": [],
        "tree_by_month": [],
        "month_table": [],
        "summary": {
            "row_count": 0,
            "total_amount": 0.0,
            "privileged_amount": 0.0,
            "non_privileged_amount": 0.0,
            "article_count": 0,
            "month_count": 0,
            "amount_column": "Сумма БУ",
            "columns": list(DETAIL_COLUMNS),
        },
    }


async def _store_uploaded_file(
    *,
    upload: UploadFile,
    upload_dir: Path,
    prefix: str,
) -> tuple[str, str, Path]:
    if not upload.filename:
        raise HTTPException(status_code=400, detail="Имя файла не указано")
    contents = await upload.read()
    if not contents:
        raise HTTPException(status_code=400, detail="Файл пустой")
    incoming_path = upload_dir / f"incoming-{uuid4().hex}.xlsx"
    stored_name = f"{prefix}-{uuid4().hex}.xlsx"
    final_path = upload_dir / stored_name
    incoming_path.write_bytes(contents)
    incoming_path.replace(final_path)
    return upload.filename, stored_name, final_path


def load_other_income_report_payload(request: Request, settings: Settings) -> dict[str, object]:
    buh_path = _resolve_buh_path(request, settings)
    meta = _meta_from_session(request)
    if buh_path is None:
        return _empty_payload()

    cost_path = _resolve_cost_path(request, settings)
    revenue_path = _resolve_revenue_path(request, settings)
    projects_path = get_test_excel_projects_path_for_cost(request, settings) or revenue_path

    payload = build_other_income_report(
        buh_path=buh_path,
        cost_path=cost_path,
        revenue_path=revenue_path,
        projects_path=projects_path,
    )
    payload["file_name"] = (
        meta["original"]
        if meta
        else (get_test_excel_buh_meta(request) or {}).get("original")
        or buh_path.name
    )
    payload["cost_file_name"] = _file_label(
        request,
        settings,
        report_field="cost_stored",
        report_original_field="cost_original",
        fallback_session=SESSION_ALMABI_TEST_EXCEL_BUH,
    )
    payload["revenue_file_name"] = _file_label(
        request,
        settings,
        report_field="revenue_stored",
        report_original_field="revenue_original",
        fallback_session=SESSION_ALMABI_TEST_EXCEL_BUH,
    )
    return payload


async def store_other_income_report_upload(
    request: Request,
    settings: Settings,
    *,
    buh_file: UploadFile,
    cost_file: UploadFile | None = None,
    revenue_file: UploadFile | None = None,
) -> dict[str, object]:
    upload_dir = test_excel_upload_dir(settings, request)
    buh_final: Path | None = None
    cost_final: Path | None = None
    revenue_final: Path | None = None
    cost_original: str | None = None
    cost_stored: str | None = None
    revenue_original: str | None = None
    revenue_stored: str | None = None

    try:
        buh_original, buh_stored, buh_final = await _store_uploaded_file(
            upload=buh_file,
            upload_dir=upload_dir,
            prefix="other-income-report-buh",
        )
        try:
            validation = validate_almabi_export(buh_final, expected_type="buh")
        except ValueError as exc:
            buh_final.unlink(missing_ok=True)
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        if cost_file is not None and cost_file.filename:
            cost_original, cost_stored, cost_final = await _store_uploaded_file(
                upload=cost_file,
                upload_dir=upload_dir,
                prefix="other-income-report-cost",
            )
            try:
                validate_almabi_export(cost_final, expected_type="cost")
            except ValueError as exc:
                cost_final.unlink(missing_ok=True)
                buh_final.unlink(missing_ok=True)
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        else:
            cost_final = _resolve_cost_path(request, settings)

        if revenue_file is not None and revenue_file.filename:
            revenue_original, revenue_stored, revenue_final = await _store_uploaded_file(
                upload=revenue_file,
                upload_dir=upload_dir,
                prefix="other-income-report-revenue",
            )
            try:
                validate_almabi_export(revenue_final, expected_type="realization")
            except ValueError as exc:
                revenue_final.unlink(missing_ok=True)
                if cost_final and cost_stored:
                    cost_final.unlink(missing_ok=True)
                buh_final.unlink(missing_ok=True)
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        else:
            revenue_final = _resolve_revenue_path(request, settings)

        projects_path = get_test_excel_projects_path_for_cost(request, settings) or revenue_final
        report = build_other_income_report(
            buh_path=buh_final,
            cost_path=cost_final,
            revenue_path=revenue_final,
            projects_path=projects_path,
        )
        if not report["rows"]:
            buh_final.unlink(missing_ok=True)
            if cost_final and cost_stored:
                cost_final.unlink(missing_ok=True)
            if revenue_final and revenue_stored:
                revenue_final.unlink(missing_ok=True)
            raise HTTPException(
                status_code=400,
                detail="Не удалось собрать отчёт: в бухрегистре нет строк «Прочие доходы».",
            )

        session_payload: dict[str, str] = {
            "original": buh_original,
            "stored": buh_stored,
        }
        if cost_original and cost_stored:
            session_payload["cost_original"] = cost_original
            session_payload["cost_stored"] = cost_stored
        if revenue_original and revenue_stored:
            session_payload["revenue_original"] = revenue_original
            session_payload["revenue_stored"] = revenue_stored
        request.session[SESSION_ALMABI_OTHER_INCOME_REPORT] = session_payload

        payload = load_other_income_report_payload(request, settings)
        payload["validation"] = validation.to_dict()
        return payload
    finally:
        await buh_file.close()
        if cost_file is not None:
            await cost_file.close()
        if revenue_file is not None:
            await revenue_file.close()
