from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from almabi_data_source import (
    almabi_data_context,
    resolve_almabi_dashboard_data,
    set_almabi_data_source,
    store_almabi_upload,
)
from dashboard_cache import DashboardPayloadCache
from dashboard_builder import (
    COST_TYPE_META,
    build_cost_scope_data,
    build_dashboard_data,
    build_navigation_data,
    get_cost_meta_or_404,
)
from data_loader import (
    load_calculation_services_by_class,
    load_calculation_services_dataset,
    load_workbook_sheets,
)
from file_registry import FileRecord, FileRegistry
from file_validation import validate_excel_file
from logging_config import configure_logging
from settings import BASE_DIR, get_settings

settings = get_settings()
configure_logging(settings)
logger = logging.getLogger("opop_bi.app")
SESSION_ACTIVE_FILE_KEY = "active_file_id"

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app = FastAPI(title="AlMaBi BI", docs_url="/api/docs", redoc_url="/api/redoc", openapi_url="/api/openapi.json")
app.add_middleware(SessionMiddleware, secret_key=settings.session_secret, same_site="lax")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static"), check_dir=False), name="static")

file_registry = FileRegistry(settings)
file_registry.ensure_default_file(settings.default_excel_path)
dashboard_payload_cache = DashboardPayloadCache()


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or uuid4().hex
    request.state.request_id = request_id
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        logger.exception(
            "request_failed",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
            },
        )
        raise

    duration_ms = round((time.perf_counter() - started) * 1000, 2)
    response.headers["x-request-id"] = request_id
    logger.info(
        "request_completed",
        extra={
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": duration_ms,
        },
    )
    return response


def money(value: float) -> str:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        amount = 0.0
    return f"{amount:,.2f}".replace(",", " ").replace(".", ",")


def pct(value: float) -> str:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        amount = 0.0
    return f"{amount:.1f}%".replace(".", ",")


def urlquote(value: object) -> str:
    return quote(str(value or ""), safe="")


templates.env.filters["money"] = money
templates.env.filters["pct"] = pct
templates.env.filters["urlquote"] = urlquote

_URL_QUERY_KEYS = frozenset({"source"})


def template_url_for(request: Request):
    """Jinja-compatible url_for: path params для имени роута Starlette + query только для ключей из _URL_QUERY_KEYS."""

    def url_for(endpoint: str, **kwargs: Any) -> str:
        query: dict[str, str] = {}
        path_params: dict[str, Any] = {}
        for key, raw in kwargs.items():
            if key in _URL_QUERY_KEYS:
                if raw is None or raw == "":
                    continue
                query[key] = str(raw)
            else:
                path_params[key] = raw
        base = request.url_for(endpoint, **path_params)
        url = str(base)
        if query:
            url = f"{url}?{urlencode(query)}"
        return url

    return url_for


def templated(request: Request, template_name: str, context: dict[str, Any], status_code: int = 200) -> HTMLResponse:
    ctx = {
        "request": request,
        "url_for": template_url_for(request),
        "file_context": files_payload(request),
        "almabi_data_context": almabi_data_context(request, settings),
        "current_nav_tab": "dashboard",
        **context,
    }
    return templates.TemplateResponse(request, template_name, ctx, status_code=status_code)


def load_dashboard_payload(path: Path) -> tuple[dict, dict, dict]:
    dataset = load_calculation_services_dataset(path)
    overview = build_dashboard_data(dataset)
    navigation = build_navigation_data(dataset)
    return dataset, overview, navigation


def get_active_file(request: Request) -> FileRecord | None:
    raw_file_id = request.session.get(SESSION_ACTIVE_FILE_KEY)
    if raw_file_id is not None:
        try:
            file_id = int(raw_file_id)
        except (TypeError, ValueError):
            request.session.pop(SESSION_ACTIVE_FILE_KEY, None)
        else:
            record = file_registry.get_valid_by_id(file_id)
            if record:
                return record
            request.session.pop(SESSION_ACTIVE_FILE_KEY, None)

    record = file_registry.get_latest_valid()
    if record:
        request.session[SESSION_ACTIVE_FILE_KEY] = record.id
    return record


def get_active_excel_path(request: Request) -> Path:
    record = get_active_file(request)
    if not record:
        return settings.default_excel_path
    return file_registry.path_for(record)


def load_active_dashboard_payload(request: Request) -> tuple[dict, dict, dict]:
    record = get_active_file(request)
    if not record:
        raise HTTPException(status_code=404, detail=f"Файл не найден: {settings.default_excel_path}")

    path = file_registry.path_for(record)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Файл не найден: {path}")

    return dashboard_payload_cache.get(record.id, path, load_dashboard_payload)


def set_active_file(request: Request, file_id: int) -> FileRecord:
    record = file_registry.get_valid_by_id(file_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Файл не найден: {file_id}")
    request.session[SESSION_ACTIVE_FILE_KEY] = record.id
    logger.info(
        "active_file_changed",
        extra={"request_id": getattr(request.state, "request_id", None), "file_id": record.id},
    )
    return record


def files_payload(request: Request) -> dict:
    active = get_active_file(request)
    latest = file_registry.get_latest_valid()
    return {
        "active_file_id": active.id if active else None,
        "latest_file_id": latest.id if latest else None,
        "has_newer_version": bool(active and latest and active.id != latest.id),
        "files": [record.to_dict() for record in file_registry.list_files()],
    }


def store_valid_excel_upload(
    request: Request,
    file: UploadFile,
    *,
    original_name: str,
    accepted_event: str,
    rejected_event: str,
) -> tuple[FileRecord, Any]:
    if not original_name:
        raise HTTPException(status_code=400, detail="Имя файла не передано")
    if Path(original_name).suffix.casefold() != ".xlsx":
        raise HTTPException(status_code=400, detail="Поддерживаются только файлы .xlsx")

    incoming_dir = settings.resolved_uploads_dir / ".incoming"
    incoming_dir.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid4().hex}.xlsx"
    temp_path = incoming_dir / stored_name
    final_path = settings.resolved_uploads_dir / stored_name

    try:
        with temp_path.open("wb") as output:
            while chunk := file.file.read(1024 * 1024):
                output.write(chunk)
        if temp_path.stat().st_size == 0:
            raise ValueError("Файл пустой")

        validation = validate_excel_file(temp_path)
        temp_path.replace(final_path)
        record = file_registry.add_valid_upload(
            original_name=original_name,
            stored_name=stored_name,
            path=final_path,
        )
        request.session[SESSION_ACTIVE_FILE_KEY] = record.id
        dashboard_payload_cache.invalidate(record.id)
        logger.info(
            accepted_event,
            extra={
                "request_id": getattr(request.state, "request_id", None),
                "file_id": record.id,
                "original_name": original_name,
                "stored_name": stored_name,
                "service_count": validation.service_count,
                "class_count": validation.class_count,
            },
        )
        return record, validation
    except ValueError as exc:
        temp_path.unlink(missing_ok=True)
        logger.warning(
            rejected_event,
            extra={
                "request_id": getattr(request.state, "request_id", None),
                "original_name": original_name,
                "error": str(exc),
            },
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def get_class_or_404(navigation: dict, class_name: str) -> dict:
    class_row = navigation["class_index"].get(class_name)
    if not class_row:
        raise HTTPException(status_code=404, detail=f"Класс не найден: {class_name}")
    return class_row


def get_service_or_404(navigation: dict, class_name: str, service_name: str) -> dict:
    service = navigation["service_index"].get((class_name, service_name))
    if not service:
        raise HTTPException(status_code=404, detail=f"Услуга не найдена: {service_name}")
    return service


def render_dashboard_error(request: Request, error: str, status_code: int = 500) -> HTMLResponse:
    url_fn = template_url_for(request)
    return templated(
        request,
        "dashboard_error.html",
        {
            "error": error,
            "current_level": 1,
            "current_class_name": None,
            "current_service_name": None,
            "current_cost_title": None,
            "current_cost_key": None,
            "navigation_mode": "class",
            "breadcrumbs": [{"name": "Главная", "href": url_fn("dashboard_home")}],
        },
        status_code=status_code,
    )


@app.exception_handler(HTTPException)
async def dashboard_http_exception_handler(request: Request, exc: HTTPException):
    if exc.status_code != 404:
        return await http_exception_handler(request, exc)
    detail = exc.detail
    message = detail if isinstance(detail, str) else str(detail)
    return render_dashboard_error(request, message, status_code=404)


@app.get("/api/files")
def api_files(request: Request) -> dict:
    return files_payload(request)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/ready")
def ready() -> JSONResponse:
    checks: dict[str, bool | str | None] = {
        "database": False,
        "uploads_dir": False,
        "latest_file": False,
        "latest_file_id": None,
    }

    try:
        with file_registry.connect() as conn:
            conn.execute("SELECT 1").fetchone()
        checks["database"] = True
    except Exception as exc:
        checks["database_error"] = str(exc)

    uploads_dir = settings.resolved_uploads_dir
    checks["uploads_dir"] = uploads_dir.exists() and uploads_dir.is_dir()

    latest = file_registry.get_latest_valid()
    if latest:
        latest_path = file_registry.path_for(latest)
        checks["latest_file"] = latest_path.exists()
        checks["latest_file_id"] = latest.id
        checks["latest_file_path"] = str(latest_path)

    is_ready = bool(checks["database"] and checks["uploads_dir"] and checks["latest_file"])
    return JSONResponse(
        {"status": "ready" if is_ready else "not_ready", "checks": checks},
        status_code=200 if is_ready else 503,
    )


@app.post("/api/session/active-file/{file_id}")
def api_set_active_file(request: Request, file_id: int) -> dict:
    record = set_active_file(request, file_id)
    return {
        "active_file_id": record.id,
        "file": record.to_dict(),
        "files": files_payload(request),
    }


@app.get("/api/excel/active", name="api_excel_active")
def api_excel_active(request: Request) -> FileResponse:
    record = get_active_file(request)
    if not record:
        raise HTTPException(status_code=404, detail="Активный Excel-файл не найден")
    path = file_registry.path_for(record)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Файл не найден: {path}")
    return FileResponse(
        path,
        filename=record.original_name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.post("/api/excel/save-version")
def api_excel_save_version(request: Request, file: UploadFile = File(...)) -> JSONResponse:
    original_name = Path(file.filename or "excel-editor-version.xlsx").name
    try:
        record, validation = store_valid_excel_upload(
            request,
            file,
            original_name=original_name,
            accepted_event="excel_editor_version_saved",
            rejected_event="excel_editor_version_rejected",
        )
        return JSONResponse(
            {
                "file": record.to_dict(),
                "validation": validation.to_dict(),
                "files": files_payload(request),
            },
            status_code=201,
        )
    finally:
        file.file.close()


@app.post("/api/files/upload")
def api_upload_file(request: Request, file: UploadFile = File(...)) -> JSONResponse:
    original_name = Path(file.filename or "").name
    try:
        record, validation = store_valid_excel_upload(
            request,
            file,
            original_name=original_name,
            accepted_event="excel_upload_accepted",
            rejected_event="excel_upload_rejected",
        )
        return JSONResponse(
            {
                "file": record.to_dict(),
                "validation": validation.to_dict(),
                "files": files_payload(request),
            },
            status_code=201,
        )
    finally:
        file.file.close()


@app.get("/", response_class=HTMLResponse, name="index")
def index(request: Request):
    return RedirectResponse(url=template_url_for(request)("almabi_dashboard"), status_code=307)


def require_debug_enabled() -> None:
    if not settings.debug:
        raise HTTPException(status_code=404, detail="Debug-раздел отключён")


@app.get("/debug", response_class=HTMLResponse, name="debug_home")
def debug_home(request: Request):
    require_debug_enabled()
    return templated(request, "debug_home.html", {})


@app.get("/debug/excel", response_class=HTMLResponse, name="excel_debug")
def excel_debug(request: Request):
    require_debug_enabled()
    excel_path = get_active_excel_path(request)
    if not excel_path.exists():
        return templated(
            request,
            "excel_debug.html",
            {"error": f"Файл не найден: {excel_path}", "sheets": []},
        )
    sheets = load_workbook_sheets(excel_path)
    return templated(request, "excel_debug.html", {"error": None, "sheets": sheets})


@app.get("/debug/calculation-services", response_class=HTMLResponse, name="calculation_services_debug")
def calculation_services_debug(request: Request):
    require_debug_enabled()
    excel_path = get_active_excel_path(request)
    if not excel_path.exists():
        return templated(
            request,
            "calculation_services_debug.html",
            {"error": f"Файл не найден: {excel_path}", "class_tables": []},
        )
    try:
        class_tables = load_calculation_services_by_class(excel_path)
        return templated(
            request,
            "calculation_services_debug.html",
            {"error": None, "class_tables": class_tables},
        )
    except Exception as exc:
        return templated(
            request,
            "calculation_services_debug.html",
            {
                "error": f"Ошибка обработки листа 'Калькуляция': {exc}",
                "class_tables": [],
            },
        )


@app.get("/dashboard", response_class=HTMLResponse, name="dashboard_home")
def dashboard_home(request: Request):
    url_fn = template_url_for(request)
    try:
        _, overview, navigation = load_active_dashboard_payload(request)
        service_picker = [
            {
                "label": item["label"],
                "href": url_fn(
                    "dashboard_service",
                    class_name=item["class_name"],
                    service_name=item["service_name"],
                ),
            }
            for item in navigation["service_picker"]
        ]

        return templated(
            request,
            "dashboard_home.html",
            {
                "overview": overview,
                "navigation": navigation,
                "service_picker": service_picker,
                "cost_drill_links": {
                    key: url_fn("dashboard_cost_overview", cost_key=key) for key in COST_TYPE_META
                },
                "current_level": 1,
                "current_class_name": None,
                "current_service_name": None,
                "current_cost_title": None,
                "current_cost_key": None,
                "navigation_mode": "class",
                "breadcrumbs": [{"name": "Главная", "href": url_fn("dashboard_home")}],
            },
        )
    except HTTPException:
        raise
    except Exception as exc:
        return render_dashboard_error(request, f"Ошибка построения дашборда: {exc}")


@app.get("/api/almabi/data-source")
def api_almabi_data_source(request: Request) -> dict:
    return almabi_data_context(request, settings)


@app.post("/api/almabi/data-source/{source}")
def api_set_almabi_data_source(request: Request, source: str) -> dict:
    set_almabi_data_source(request, source)
    return almabi_data_context(request, settings)


@app.post("/api/almabi/files/upload")
def api_almabi_upload_file(request: Request, file: UploadFile = File(...)) -> JSONResponse:
    try:
        payload = store_almabi_upload(request, settings, file)
        return JSONResponse(
            {
                **payload,
                "context": almabi_data_context(request, settings),
            },
            status_code=201,
        )
    finally:
        file.file.close()


@app.get("/dashboard/almabi", response_class=HTMLResponse, name="almabi_dashboard")
def almabi_dashboard(request: Request):
    url_fn = template_url_for(request)
    return templated(
        request,
        "almabi_dashboard.html",
        {
            "dashboard": resolve_almabi_dashboard_data(request, settings),
            "current_nav_tab": "almabi",
            "current_level": 1,
            "current_class_name": None,
            "current_service_name": None,
            "current_cost_title": None,
            "current_cost_key": None,
            "navigation_mode": "almabi",
            "breadcrumbs": [{"name": "AlMaBi BI", "href": url_fn("almabi_dashboard")}],
        },
    )


@app.get("/dashboard/excel", response_class=HTMLResponse, name="dashboard_excel_editor")
def dashboard_excel_editor(request: Request):
    record = get_active_file(request)
    if not record:
        return render_dashboard_error(request, "Активный Excel-файл не найден", status_code=404)
    path = file_registry.path_for(record)
    if not path.exists():
        return render_dashboard_error(request, f"Файл не найден: {path}", status_code=404)

    return templated(
        request,
        "dashboard_excel_editor.html",
        {
            "active_file": record.to_dict(),
            "current_nav_tab": "excel",
            "current_level": 0,
            "current_class_name": None,
            "current_service_name": None,
            "current_cost_title": None,
            "current_cost_key": None,
            "navigation_mode": "excel",
        },
    )


@app.get("/dashboard/cost/{cost_key}", response_class=HTMLResponse, name="dashboard_cost_overview")
def dashboard_cost_overview(request: Request, cost_key: str):
    url_fn = template_url_for(request)
    try:
        _, overview, navigation = load_active_dashboard_payload(request)
        cost_scope = build_cost_scope_data(navigation["services"], cost_key)
        cost_meta = cost_scope["meta"]

        for row in cost_scope["class_rows"]:
            row["href"] = url_fn(
                "dashboard_cost_class",
                cost_key=cost_key,
                class_name=row["class_name"],
            )

        for row in cost_scope["service_rows"]:
            row["class_href"] = url_fn(
                "dashboard_cost_class",
                cost_key=cost_key,
                class_name=row["class_name"],
            )
            row["service_href"] = url_fn(
                "dashboard_cost_detail",
                class_name=row["class_name"],
                service_name=row["service_name"],
                cost_key=cost_key,
                source="cost",
            )

        breadcrumbs = [
            {"name": "Главная", "href": url_fn("dashboard_home")},
            {
                "name": cost_meta["title"],
                "href": url_fn("dashboard_cost_overview", cost_key=cost_key),
            },
        ]

        return templated(
            request,
            "dashboard_cost_overview.html",
            {
                "overview": overview,
                "navigation": navigation,
                "cost_scope": cost_scope,
                "cost_meta": cost_meta,
                "current_level": 2,
                "current_class_name": None,
                "current_service_name": None,
                "current_cost_title": cost_meta["title"],
                "current_cost_key": cost_key,
                "navigation_mode": "cost",
                "breadcrumbs": breadcrumbs,
            },
        )
    except HTTPException:
        raise
    except Exception as exc:
        return render_dashboard_error(request, f"Ошибка построения среза затрат: {exc}")


@app.get(
    "/dashboard/cost/{cost_key}/class/{class_name:path}",
    response_class=HTMLResponse,
    name="dashboard_cost_class",
)
def dashboard_cost_class(request: Request, cost_key: str, class_name: str):
    url_fn = template_url_for(request)
    try:
        _, overview, navigation = load_active_dashboard_payload(request)
        class_row = get_class_or_404(navigation, class_name)
        cost_scope = build_cost_scope_data(class_row["services"], cost_key)
        global_scope = build_cost_scope_data(navigation["services"], cost_key)
        cost_meta = cost_scope["meta"]

        global_classes = global_scope["class_rows"]
        class_rank = next(
            (idx + 1 for idx, row in enumerate(global_classes) if row["class_name"] == class_name),
            0,
        )
        class_share_global = next(
            (row.get("share_in_scope", 0.0) for row in global_classes if row["class_name"] == class_name),
            0.0,
        )

        for row in cost_scope["service_rows"]:
            row["service_href"] = url_fn(
                "dashboard_cost_detail",
                class_name=class_name,
                service_name=row["service_name"],
                cost_key=cost_key,
                source="cost",
            )

        breadcrumbs = [
            {"name": "Главная", "href": url_fn("dashboard_home")},
            {
                "name": cost_meta["title"],
                "href": url_fn("dashboard_cost_overview", cost_key=cost_key),
            },
            {
                "name": class_name,
                "href": url_fn(
                    "dashboard_cost_class",
                    cost_key=cost_key,
                    class_name=class_name,
                ),
            },
        ]

        return templated(
            request,
            "dashboard_cost_class.html",
            {
                "overview": overview,
                "navigation": navigation,
                "class_row": class_row,
                "cost_scope": cost_scope,
                "cost_meta": cost_meta,
                "class_rank": class_rank,
                "class_share_global": class_share_global,
                "current_level": 3,
                "current_class_name": class_name,
                "current_service_name": None,
                "current_cost_title": cost_meta["title"],
                "current_cost_key": cost_key,
                "navigation_mode": "cost",
                "breadcrumbs": breadcrumbs,
            },
        )
    except HTTPException:
        raise
    except Exception as exc:
        return render_dashboard_error(request, f"Ошибка построения среза класса: {exc}")


@app.get(
    "/dashboard/class/{class_name:path}/service/{service_name:path}/cost/{cost_key}",
    response_class=HTMLResponse,
    name="dashboard_cost_detail",
)
def dashboard_cost_detail(
    request: Request,
    class_name: str,
    service_name: str,
    cost_key: str,
    source: str | None = Query(None),
):
    url_fn = template_url_for(request)
    src = (source or "").strip().casefold()

    if cost_key not in COST_TYPE_META:
        raise HTTPException(status_code=404, detail=f"Тип затрат не найден: {cost_key}")

    try:
        _, overview, navigation = load_active_dashboard_payload(request)
        class_row = get_class_or_404(navigation, class_name)
        service = get_service_or_404(navigation, class_name, service_name)
        meta = get_cost_meta_or_404(cost_key)

        selected_value = float(service.get(meta["field"], 0.0))
        selected_share = (
            (selected_value / float(service["total_cost"]) * 100.0) if float(service["total_cost"]) else 0.0
        )

        details = service.get(meta["details_field"], {}) or {}
        detail_rows = []
        for component, value in details.items():
            value_float = float(value)
            if value_float == 0:
                continue
            detail_rows.append(
                {
                    "component": component,
                    "value": value_float,
                    "share": (value_float / selected_value * 100.0) if selected_value else 0.0,
                }
            )
        detail_rows.sort(key=lambda row: row["value"], reverse=True)

        peer_rows = []
        for peer in class_row["services"]:
            peer_value = float(peer.get(meta["field"], 0.0))
            peer_rows.append(
                {
                    "service_name": peer["service_name"],
                    "value": peer_value,
                    "is_current": peer["service_name"] == service_name,
                    "href": url_fn(
                        "dashboard_cost_detail",
                        class_name=class_name,
                        service_name=peer["service_name"],
                        cost_key=cost_key,
                        source="cost" if src == "cost" else "",
                    ),
                }
            )
        peer_rows.sort(key=lambda row: row["value"], reverse=True)
        ranking = next((idx + 1 for idx, row in enumerate(peer_rows) if row["is_current"]), 0)

        breadcrumbs = [
            {"name": "Главная", "href": url_fn("dashboard_home")},
            {
                "name": class_name,
                "href": url_fn("dashboard_class", class_name=class_name),
            },
            {
                "name": service_name,
                "href": url_fn(
                    "dashboard_service",
                    class_name=class_name,
                    service_name=service_name,
                ),
            },
            {
                "name": meta["title"],
                "href": url_fn(
                    "dashboard_cost_detail",
                    class_name=class_name,
                    service_name=service_name,
                    cost_key=cost_key,
                ),
            },
        ]

        return templated(
            request,
            "dashboard_cost_detail.html",
            {
                "overview": overview,
                "navigation": navigation,
                "class_row": class_row,
                "service": service,
                "cost_key": cost_key,
                "cost_meta": meta,
                "selected_value": selected_value,
                "selected_share": selected_share,
                "detail_rows": detail_rows,
                "peer_rows": peer_rows,
                "ranking": ranking,
                "current_level": 4,
                "current_class_name": class_name,
                "current_service_name": service_name,
                "current_cost_title": meta["title"],
                "current_cost_key": cost_key,
                "navigation_mode": "cost" if src == "cost" else "class",
                "cost_overview_href": url_fn("dashboard_cost_overview", cost_key=cost_key),
                "cost_class_href": url_fn(
                    "dashboard_cost_class",
                    cost_key=cost_key,
                    class_name=class_name,
                ),
                "breadcrumbs": breadcrumbs,
            },
        )
    except HTTPException:
        raise
    except Exception as exc:
        return render_dashboard_error(request, f"Ошибка построения страницы затрат: {exc}")


@app.get(
    "/dashboard/class/{class_name:path}/service/{service_name:path}",
    response_class=HTMLResponse,
    name="dashboard_service",
)
def dashboard_service(request: Request, class_name: str, service_name: str):
    url_fn = template_url_for(request)
    try:
        _, overview, navigation = load_active_dashboard_payload(request)
        class_row = get_class_or_404(navigation, class_name)
        service = get_service_or_404(navigation, class_name, service_name)

        total_cost = float(service["total_cost"])
        cost_cards = []
        for cost_key, meta in COST_TYPE_META.items():
            amount = float(service[meta["field"]])
            share = (amount / total_cost * 100.0) if total_cost else 0.0
            cost_cards.append(
                {
                    "key": cost_key,
                    "title": meta["title"],
                    "amount": amount,
                    "share": share,
                    "color": meta["color"],
                    "href": url_fn(
                        "dashboard_cost_detail",
                        class_name=class_name,
                        service_name=service_name,
                        cost_key=cost_key,
                    ),
                }
            )

        peer_services = class_row["services"]
        peer_labels = [item["service_name"] for item in peer_services]
        peer_totals = [item["total_cost"] for item in peer_services]
        component_rows = []
        for _, meta in COST_TYPE_META.items():
            details = service.get(meta["details_field"], {}) or {}
            for component, value in details.items():
                value_float = float(value)
                if value_float == 0:
                    continue
                component_rows.append(
                    {
                        "type": meta["title"],
                        "component": component,
                        "value": value_float,
                    }
                )
        component_rows.sort(key=lambda row: row["value"], reverse=True)

        breadcrumbs = [
            {"name": "Главная", "href": url_fn("dashboard_home")},
            {
                "name": class_name,
                "href": url_fn("dashboard_class", class_name=class_name),
            },
            {
                "name": service_name,
                "href": url_fn(
                    "dashboard_service",
                    class_name=class_name,
                    service_name=service_name,
                ),
            },
        ]

        return templated(
            request,
            "dashboard_service.html",
            {
                "overview": overview,
                "navigation": navigation,
                "class_row": class_row,
                "service": service,
                "cost_cards": cost_cards,
                "peer_labels": peer_labels,
                "peer_totals": peer_totals,
                "component_rows": component_rows[:25],
                "current_level": 3,
                "current_class_name": class_name,
                "current_service_name": service_name,
                "current_cost_title": None,
                "current_cost_key": None,
                "navigation_mode": "class",
                "breadcrumbs": breadcrumbs,
            },
        )
    except HTTPException:
        raise
    except Exception as exc:
        return render_dashboard_error(request, f"Ошибка построения страницы услуги: {exc}")


@app.get("/dashboard/class/{class_name:path}", response_class=HTMLResponse, name="dashboard_class")
def dashboard_class(request: Request, class_name: str):
    url_fn = template_url_for(request)
    try:
        _, overview, navigation = load_active_dashboard_payload(request)
        class_row = get_class_or_404(navigation, class_name)
        services = class_row["services"]
        service_labels = [service["service_name"] for service in services]
        service_totals = [service["total_cost"] for service in services]
        cost_structure = [
            class_row["totals"]["direct"],
            class_row["totals"]["indirect"],
            class_row["totals"]["ineff"],
        ]

        breadcrumbs = [
            {"name": "Главная", "href": url_fn("dashboard_home")},
            {
                "name": class_name,
                "href": url_fn("dashboard_class", class_name=class_name),
            },
        ]

        return templated(
            request,
            "dashboard_class.html",
            {
                "overview": overview,
                "navigation": navigation,
                "class_row": class_row,
                "service_labels": service_labels,
                "service_totals": service_totals,
                "cost_structure": cost_structure,
                "class_cost_links": {
                    key: url_fn("dashboard_cost_class", cost_key=key, class_name=class_name)
                    for key in COST_TYPE_META
                },
                "current_level": 2,
                "current_class_name": class_name,
                "current_service_name": None,
                "current_cost_title": None,
                "current_cost_key": None,
                "navigation_mode": "class",
                "breadcrumbs": breadcrumbs,
            },
        )
    except HTTPException:
        raise
    except Exception as exc:
        return render_dashboard_error(request, f"Ошибка построения страницы класса: {exc}")


@app.get("/dashboard/legacy", response_class=HTMLResponse, name="dashboard_legacy")
def dashboard_legacy(request: Request):
    excel_path = get_active_excel_path(request)
    if not excel_path.exists():
        return templated(
            request,
            "dashboard.html",
            {"error": f"Файл не найден: {excel_path}", "dashboard": None},
        )

    try:
        dataset = load_calculation_services_dataset(excel_path)
        dashboard_data = build_dashboard_data(dataset)
        return templated(request, "dashboard.html", {"error": None, "dashboard": dashboard_data})
    except Exception as exc:
        return templated(
            request,
            "dashboard.html",
            {"error": f"Ошибка построения дашборда: {exc}", "dashboard": None},
        )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.debug,
        reload_excludes=["logs/*", "runtime/*", "uploads/*", "data/*", "*.sqlite3"],
        factory=False,
    )
