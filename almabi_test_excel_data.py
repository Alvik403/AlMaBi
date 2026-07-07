"""Сессия и загрузка для страницы «Тест Excel»."""
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, Request, UploadFile

from almabi_file_validation import validate_almabi_export
from almabi_pq_buh_register import build_pq_buh_register_table, table_summary as buh_table_summary
from almabi_pq_cost import build_pq_cost_table, table_summary as cost_table_summary
from almabi_pq_projects import build_pq_projects_table, table_summary as projects_table_summary
from almabi_pq_revenue import build_pq_revenue_table, table_summary as revenue_table_summary
from settings import Settings

SESSION_ALMABI_TEST_EXCEL_REVENUE = "almabi_test_excel_revenue"
SESSION_ALMABI_TEST_EXCEL_COST = "almabi_test_excel_cost"
SESSION_ALMABI_TEST_EXCEL_PROJECTS = "almabi_test_excel_projects"
SESSION_ALMABI_TEST_EXCEL_BUH = "almabi_test_excel_buh"

REVENUE_FILTER_COLUMNS = ("Проект", "Группа проектов", "Направление")
COST_FILTER_COLUMNS = ("Раздел", "Проект", "Группа проектов", "Направление", "Счет")
PROJECTS_FILTER_COLUMNS = ("Раздел", "Проект", "Группа проектов", "Направление")
BUH_FILTER_COLUMNS = ("Раздел", "Основной раздел", "Вид НО", "Проект", "Группа проектов", "Направление")


def _upload_dir(settings: Settings) -> Path:
    path = settings.resolved_uploads_dir / "almabi_test_excel"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _meta_from_session(request: Request, key: str) -> dict[str, str] | None:
    stored = request.session.get(key)
    if not isinstance(stored, dict):
        return None
    original = stored.get("original")
    stored_name = stored.get("stored")
    if not original or not stored_name:
        return None
    return {"original": str(original), "stored": str(stored_name)}


def _path_from_meta(settings: Settings, meta: dict[str, str] | None) -> Path | None:
    if meta is None:
        return None
    path = _upload_dir(settings) / meta["stored"]
    return path if path.exists() else None


def get_test_excel_revenue_meta(request: Request) -> dict[str, str] | None:
    return _meta_from_session(request, SESSION_ALMABI_TEST_EXCEL_REVENUE)


def get_test_excel_cost_meta(request: Request) -> dict[str, str] | None:
    return _meta_from_session(request, SESSION_ALMABI_TEST_EXCEL_COST)


def get_test_excel_projects_meta(request: Request) -> dict[str, str] | None:
    return _meta_from_session(request, SESSION_ALMABI_TEST_EXCEL_PROJECTS)


def get_test_excel_buh_meta(request: Request) -> dict[str, str] | None:
    return _meta_from_session(request, SESSION_ALMABI_TEST_EXCEL_BUH)


def get_test_excel_revenue_path(request: Request, settings: Settings) -> Path | None:
    return _path_from_meta(settings, get_test_excel_revenue_meta(request))


def get_test_excel_cost_path(request: Request, settings: Settings) -> Path | None:
    return _path_from_meta(settings, get_test_excel_cost_meta(request))


def get_test_excel_projects_path(request: Request, settings: Settings) -> Path | None:
    return _path_from_meta(settings, get_test_excel_projects_meta(request))


def get_test_excel_buh_path(request: Request, settings: Settings) -> Path | None:
    return _path_from_meta(settings, get_test_excel_buh_meta(request))


def _path_from_session_field(request: Request, settings: Settings, session_key: str, field: str) -> Path | None:
    stored = request.session.get(session_key)
    if not isinstance(stored, dict):
        return None
    stored_name = stored.get(field)
    if not stored_name:
        return None
    path = _upload_dir(settings) / str(stored_name)
    return path if path.exists() else None


def get_test_excel_cost_path_for_buh(request: Request, settings: Settings) -> Path | None:
    path = _path_from_session_field(request, settings, SESSION_ALMABI_TEST_EXCEL_BUH, "cost_stored")
    if path is not None:
        return path
    return get_test_excel_cost_path(request, settings)


def get_test_excel_revenue_path_for_buh(request: Request, settings: Settings) -> Path | None:
    path = _path_from_session_field(request, settings, SESSION_ALMABI_TEST_EXCEL_BUH, "revenue_stored")
    if path is not None:
        return path
    return get_test_excel_revenue_path(request, settings)


def get_test_excel_projects_path_for_cost(request: Request, settings: Settings) -> Path | None:
    cost_meta = request.session.get(SESSION_ALMABI_TEST_EXCEL_COST)
    if isinstance(cost_meta, dict):
        projects_name = cost_meta.get("projects_stored")
        if projects_name:
            path = _upload_dir(settings) / str(projects_name)
            if path.exists():
                return path
    projects_path = get_test_excel_projects_path(request, settings)
    if projects_path is not None:
        return projects_path
    return get_test_excel_revenue_path(request, settings)


def _empty_payload(*, filter_columns: tuple[str, ...]) -> dict[str, object]:
    return {
        "loaded": False,
        "file_name": None,
        "projects_file_name": None,
        "cost_file_name": None,
        "revenue_file_name": None,
        "rows": [],
        "summary": revenue_table_summary([]),
        "filter_options": {column: [] for column in filter_columns},
    }


def _aux_file_name(
    request: Request,
    settings: Settings,
    *,
    buh_meta: dict[str, str] | None,
    buh_field: str,
    fallback_meta_key: str,
    fallback_path: Path | None,
) -> str | None:
    if buh_meta and buh_meta.get(f"{buh_field}_original"):
        return str(buh_meta[f"{buh_field}_original"])
    if fallback_path is None:
        return None
    fallback_meta = _meta_from_session(request, fallback_meta_key)
    if fallback_meta and fallback_path.name == fallback_meta.get("stored"):
        original = fallback_meta.get("original")
        return str(original) if original else None
    return None


def _filter_options(rows: list[dict[str, object]], columns: tuple[str, ...]) -> dict[str, list[str]]:
    return {
        column: sorted({str(row.get(column) or "") for row in rows if row.get(column) not in (None, "")})
        for column in columns
    }


def load_test_excel_revenue_payload(request: Request, settings: Settings) -> dict[str, object]:
    meta = get_test_excel_revenue_meta(request)
    path = _path_from_meta(settings, meta)
    if meta is None or path is None:
        empty = _empty_payload(filter_columns=REVENUE_FILTER_COLUMNS)
        empty["summary"] = revenue_table_summary([])
        return empty

    rows = build_pq_revenue_table(path)
    return {
        "loaded": True,
        "file_name": meta["original"],
        "projects_file_name": None,
        "rows": rows,
        "summary": revenue_table_summary(rows),
        "filter_options": _filter_options(rows, REVENUE_FILTER_COLUMNS),
    }


def load_test_excel_cost_payload(request: Request, settings: Settings) -> dict[str, object]:
    meta = get_test_excel_cost_meta(request)
    path = _path_from_meta(settings, meta)
    if meta is None or path is None:
        empty = _empty_payload(filter_columns=COST_FILTER_COLUMNS)
        empty["summary"] = cost_table_summary([])
        return empty

    projects_path = get_test_excel_projects_path_for_cost(request, settings)
    rows = build_pq_cost_table(path, projects_path=projects_path)
    projects_name = None
    if isinstance(meta, dict) and meta.get("projects_original"):
        projects_name = str(meta["projects_original"])
    elif projects_path is not None:
        projects_meta = get_test_excel_projects_meta(request)
        if projects_meta and projects_path.name == projects_meta.get("stored"):
            projects_name = projects_meta.get("original")
        else:
            revenue_meta = get_test_excel_revenue_meta(request)
            if revenue_meta and projects_path.name == revenue_meta.get("stored"):
                projects_name = revenue_meta.get("original")

    return {
        "loaded": True,
        "file_name": meta["original"],
        "projects_file_name": projects_name,
        "rows": rows,
        "summary": cost_table_summary(rows),
        "filter_options": _filter_options(rows, COST_FILTER_COLUMNS),
    }


def load_test_excel_projects_payload(request: Request, settings: Settings) -> dict[str, object]:
    meta = get_test_excel_projects_meta(request)
    path = _path_from_meta(settings, meta)
    if meta is None or path is None:
        empty = _empty_payload(filter_columns=PROJECTS_FILTER_COLUMNS)
        empty["summary"] = projects_table_summary([])
        return empty

    rows = build_pq_projects_table(path)
    return {
        "loaded": True,
        "file_name": meta["original"],
        "projects_file_name": None,
        "rows": rows,
        "summary": projects_table_summary(rows),
        "filter_options": _filter_options(rows, PROJECTS_FILTER_COLUMNS),
    }


def load_test_excel_buh_payload(request: Request, settings: Settings) -> dict[str, object]:
    meta = get_test_excel_buh_meta(request)
    path = _path_from_meta(settings, meta)
    if meta is None or path is None:
        empty = _empty_payload(filter_columns=BUH_FILTER_COLUMNS)
        empty["summary"] = buh_table_summary([])
        return empty

    cost_path = get_test_excel_cost_path_for_buh(request, settings)
    revenue_path = get_test_excel_revenue_path_for_buh(request, settings)
    projects_path = get_test_excel_projects_path_for_cost(request, settings)
    rows = build_pq_buh_register_table(
        path,
        cost_path=cost_path,
        revenue_path=revenue_path,
        projects_path=projects_path,
    )

    return {
        "loaded": True,
        "file_name": meta["original"],
        "projects_file_name": None,
        "cost_file_name": _aux_file_name(
            request,
            settings,
            buh_meta=meta,
            buh_field="cost",
            fallback_meta_key=SESSION_ALMABI_TEST_EXCEL_COST,
            fallback_path=cost_path,
        ),
        "revenue_file_name": _aux_file_name(
            request,
            settings,
            buh_meta=meta,
            buh_field="revenue",
            fallback_meta_key=SESSION_ALMABI_TEST_EXCEL_REVENUE,
            fallback_path=revenue_path,
        ),
        "rows": rows,
        "summary": buh_table_summary(rows),
        "filter_options": _filter_options(rows, BUH_FILTER_COLUMNS),
    }


def load_test_excel_page_payload(request: Request, settings: Settings) -> dict[str, object]:
    return {
        "revenue": load_test_excel_revenue_payload(request, settings),
        "cost": load_test_excel_cost_payload(request, settings),
        "projects": load_test_excel_projects_payload(request, settings),
        "buh": load_test_excel_buh_payload(request, settings),
        "active_tab": request.query_params.get("tab", "revenue"),
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


async def store_test_excel_revenue_upload(request: Request, settings: Settings, file: UploadFile) -> dict[str, object]:
    upload_dir = _upload_dir(settings)
    try:
        original, stored_name, final_path = await _store_uploaded_file(
            upload=file,
            upload_dir=upload_dir,
            prefix="revenue",
        )
        try:
            validation = validate_almabi_export(final_path, expected_type="realization")
        except ValueError as exc:
            final_path.unlink(missing_ok=True)
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        rows = build_pq_revenue_table(final_path)
        if not rows:
            final_path.unlink(missing_ok=True)
            raise HTTPException(
                status_code=400,
                detail="Не удалось построить таблицу «Выручка». Проверьте структуру выгрузки.",
            )

        request.session[SESSION_ALMABI_TEST_EXCEL_REVENUE] = {
            "original": original,
            "stored": stored_name,
        }
        payload = load_test_excel_revenue_payload(request, settings)
        payload["validation"] = validation.to_dict()
        return payload
    finally:
        await file.close()


async def store_test_excel_cost_upload(
    request: Request,
    settings: Settings,
    *,
    cost_file: UploadFile,
    projects_file: UploadFile | None = None,
) -> dict[str, object]:
    upload_dir = _upload_dir(settings)
    cost_final: Path | None = None
    projects_final: Path | None = None
    projects_original: str | None = None
    projects_stored: str | None = None

    try:
        cost_original, cost_stored, cost_final = await _store_uploaded_file(
            upload=cost_file,
            upload_dir=upload_dir,
            prefix="cost",
        )
        try:
            validation = validate_almabi_export(cost_final, expected_type="cost")
        except ValueError as exc:
            cost_final.unlink(missing_ok=True)
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        if projects_file is not None and projects_file.filename:
            projects_original, projects_stored, projects_final = await _store_uploaded_file(
                upload=projects_file,
                upload_dir=upload_dir,
                prefix="projects",
            )
            try:
                validate_almabi_export(projects_final, expected_type="realization")
            except ValueError as exc:
                projects_final.unlink(missing_ok=True)
                cost_final.unlink(missing_ok=True)
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        else:
            projects_final = get_test_excel_projects_path_for_cost(request, settings)

        rows = build_pq_cost_table(cost_final, projects_path=projects_final)
        if not rows:
            cost_final.unlink(missing_ok=True)
            if projects_final and projects_stored:
                projects_final.unlink(missing_ok=True)
            raise HTTPException(
                status_code=400,
                detail="Не удалось построить таблицу «Себестоимость». Проверьте структуру выгрузки.",
            )

        session_payload: dict[str, str] = {
            "original": cost_original,
            "stored": cost_stored,
        }
        if projects_original and projects_stored:
            session_payload["projects_original"] = projects_original
            session_payload["projects_stored"] = projects_stored
        request.session[SESSION_ALMABI_TEST_EXCEL_COST] = session_payload

        payload = load_test_excel_cost_payload(request, settings)
        payload["validation"] = validation.to_dict()
        return payload
    finally:
        await cost_file.close()
        if projects_file is not None:
            await projects_file.close()


async def store_test_excel_projects_upload(request: Request, settings: Settings, file: UploadFile) -> dict[str, object]:
    upload_dir = _upload_dir(settings)
    try:
        original, stored_name, final_path = await _store_uploaded_file(
            upload=file,
            upload_dir=upload_dir,
            prefix="projects",
        )
        try:
            validation = validate_almabi_export(final_path, expected_type="realization")
        except ValueError as exc:
            final_path.unlink(missing_ok=True)
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        rows = build_pq_projects_table(final_path)
        if not rows:
            final_path.unlink(missing_ok=True)
            raise HTTPException(
                status_code=400,
                detail="Не удалось построить таблицу «Проекты». Проверьте структуру выгрузки.",
            )

        request.session[SESSION_ALMABI_TEST_EXCEL_PROJECTS] = {
            "original": original,
            "stored": stored_name,
        }
        payload = load_test_excel_projects_payload(request, settings)
        payload["validation"] = validation.to_dict()
        return payload
    finally:
        await file.close()


async def store_test_excel_buh_upload(
    request: Request,
    settings: Settings,
    *,
    buh_file: UploadFile,
    cost_file: UploadFile | None = None,
    revenue_file: UploadFile | None = None,
) -> dict[str, object]:
    upload_dir = _upload_dir(settings)
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
            prefix="buh",
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
                prefix="cost",
            )
            try:
                validate_almabi_export(cost_final, expected_type="cost")
            except ValueError as exc:
                cost_final.unlink(missing_ok=True)
                buh_final.unlink(missing_ok=True)
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        else:
            cost_final = get_test_excel_cost_path_for_buh(request, settings)

        if revenue_file is not None and revenue_file.filename:
            revenue_original, revenue_stored, revenue_final = await _store_uploaded_file(
                upload=revenue_file,
                upload_dir=upload_dir,
                prefix="revenue",
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
            revenue_final = get_test_excel_revenue_path_for_buh(request, settings)

        projects_final = get_test_excel_projects_path_for_cost(request, settings)
        rows = build_pq_buh_register_table(
            buh_final,
            cost_path=cost_final,
            revenue_path=revenue_final,
            projects_path=projects_final,
        )
        if not rows:
            buh_final.unlink(missing_ok=True)
            if cost_final and cost_stored:
                cost_final.unlink(missing_ok=True)
            if revenue_final and revenue_stored:
                revenue_final.unlink(missing_ok=True)
            raise HTTPException(
                status_code=400,
                detail="Не удалось построить таблицу «Бух.регистр». Проверьте структуру выгрузки.",
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
        request.session[SESSION_ALMABI_TEST_EXCEL_BUH] = session_payload

        payload = load_test_excel_buh_payload(request, settings)
        payload["validation"] = validation.to_dict()
        return payload
    finally:
        await buh_file.close()
        if cost_file is not None:
            await cost_file.close()
        if revenue_file is not None:
            await revenue_file.close()
