from __future__ import annotations

import logging
import secrets
import time
from typing import Any
from urllib.parse import quote, urlencode
from uuid import uuid4

from fastapi import FastAPI, File, Form, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from almabi_auth import (
    AuthMiddleware,
    LoginThrottle,
    SESSION_CSRF_KEY,
    SESSION_TOKEN_KEY,
    SESSION_USER_ID_KEY,
)
from almabi_auth_store import AuthStore, AuthStoreError, normalize_username
from almabi_http_security import (
    RequestBodyLimitMiddleware,
    RequestTimeoutMiddleware,
    SecurityHeadersMiddleware,
)
from almabi_data_source import (
    adopt_latest_user_uploads,
    almabi_data_context,
    store_almabi_upload,
    store_almabi_upload_bundle,
)
from almabi_cost_report_data import load_cost_report_payload, store_cost_report_upload
from almabi_operating_profit_report_data import load_operating_profit_report_payload, store_operating_profit_report_upload
from almabi_profit_before_tax_report_data import load_profit_before_tax_report_payload, store_profit_before_tax_report_upload
from almabi_taxes_report_data import load_taxes_report_payload, store_taxes_report_upload
from almabi_net_profit_report_data import load_net_profit_report_payload, store_net_profit_report_upload
from almabi_management_expense_report_data import load_management_expense_report_payload, store_management_expense_report_upload
from almabi_commercial_expense_report_data import load_commercial_expense_report_payload, store_commercial_expense_report_upload
from almabi_other_expense_report_data import load_other_expense_report_payload, store_other_expense_report_upload
from almabi_other_income_report_data import load_other_income_report_payload, store_other_income_report_upload
from almabi_revenue_report_data import load_revenue_report_payload, store_revenue_report_upload
from almabi_test_data import resolve_almabi_dashboard_api_data, resolve_almabi_dashboard_data
from almabi_test_excel_data import (
    load_test_excel_buh_payload,
    load_test_excel_cost_payload,
    load_test_excel_page_payload,
    load_test_excel_projects_payload,
    load_test_excel_revenue_payload,
    store_test_excel_buh_upload,
    store_test_excel_cost_upload,
    store_test_excel_projects_upload,
    store_test_excel_revenue_upload,
)
from branding import ALMABI_NAV_TABS, APP_BRAND
from logging_config import configure_logging
from settings import BASE_DIR, get_settings

settings = get_settings()
configure_logging(settings)
logger = logging.getLogger("almabi.app")
auth_store = AuthStore(settings.resolved_auth_db)
login_throttle = LoginThrottle()

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app = FastAPI(title=APP_BRAND, docs_url="/api/docs", redoc_url="/api/redoc", openapi_url="/api/openapi.json")
app.add_middleware(
    RequestBodyLimitMiddleware,
    max_bytes=settings.max_upload_bytes,
    uploads_dir=settings.resolved_uploads_dir,
    quota_bytes=settings.upload_quota_bytes,
)
app.add_middleware(RequestTimeoutMiddleware, timeout_seconds=settings.request_timeout_seconds)
app.add_middleware(SecurityHeadersMiddleware, hsts=settings.session_https_only)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_host_list)
app.add_middleware(AuthMiddleware, store=auth_store, enabled=settings.auth_enabled)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    same_site="lax",
    https_only=settings.session_https_only,
    max_age=settings.session_max_age_seconds,
)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static"), check_dir=False), name="static")

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
    return f"{amount:,.0f}".replace(",", " ")


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

_URL_QUERY_KEYS = frozenset({"source", "tab"})


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
        "csp_nonce": getattr(request.state, "csp_nonce", ""),
        "csrf_token": request.session.get(SESSION_CSRF_KEY, ""),
        "current_user": getattr(request.state, "current_user", None),
        "url_for": template_url_for(request),
        "almabi_data_context": almabi_data_context(request, settings),
        "app_brand": APP_BRAND,
        "almabi_nav_tabs": ALMABI_NAV_TABS,
        "current_nav_tab": "dashboard",
        **context,
    }
    return templates.TemplateResponse(request, template_name, ctx, status_code=status_code)


def _auth_template(
    request: Request,
    template_name: str,
    context: dict[str, Any],
    status_code: int = 200,
) -> HTMLResponse:
    ctx = {
        "request": request,
        "app_brand": APP_BRAND,
        "csp_nonce": getattr(request.state, "csp_nonce", ""),
        "csrf_token": request.session.get(SESSION_CSRF_KEY, ""),
        "current_user": getattr(request.state, "current_user", None),
        **context,
    }
    return templates.TemplateResponse(request, template_name, ctx, status_code=status_code)


def _safe_next(value: str | None) -> str:
    if not value or not value.startswith("/") or value.startswith("//"):
        return "/dashboard/almabi"
    return value


def _valid_csrf(request: Request, supplied: str) -> bool:
    expected = request.session.get(SESSION_CSRF_KEY, "")
    return bool(expected and supplied and secrets.compare_digest(str(expected), supplied))


@app.get("/login", response_class=HTMLResponse, name="login")
def login_page(request: Request, next: str | None = Query(default=None)):
    if not settings.auth_enabled:
        return RedirectResponse(url="/dashboard/almabi", status_code=303)
    token = request.session.get(SESSION_TOKEN_KEY)
    if isinstance(token, str) and auth_store.resolve_session(token) is not None:
        return RedirectResponse(url=_safe_next(next), status_code=303)
    request.session.setdefault(SESSION_CSRF_KEY, secrets.token_urlsafe(32))
    return _auth_template(request, "login.html", {"next_url": _safe_next(next), "error": None})


@app.post("/login", response_class=HTMLResponse)
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    csrf_token: str = Form(...),
    next_url: str = Form(default="/dashboard/almabi"),
):
    if not settings.auth_enabled:
        return RedirectResponse(url="/dashboard/almabi", status_code=303)
    if not _valid_csrf(request, csrf_token):
        return _auth_template(
            request,
            "login.html",
            {"next_url": _safe_next(next_url), "error": "Сессия формы устарела. Повторите вход."},
            status_code=403,
        )
    client_ip = request.client.host if request.client else "unknown"
    throttle_key = f"{client_ip}:{username.strip().casefold()}"
    retry_after = login_throttle.retry_after(throttle_key)
    if retry_after:
        return _auth_template(
            request,
            "login.html",
            {
                "next_url": _safe_next(next_url),
                "error": f"Слишком много попыток. Повторите через {retry_after} сек.",
            },
            status_code=429,
        )
    user = auth_store.authenticate(username, password)
    if user is None:
        login_throttle.failure(throttle_key)
        return _auth_template(
            request,
            "login.html",
            {"next_url": _safe_next(next_url), "error": "Неверное имя пользователя или пароль."},
            status_code=401,
        )
    login_throttle.success(throttle_key)
    request.session.clear()
    request.session[SESSION_TOKEN_KEY] = auth_store.create_session(
        user.id,
        settings.session_max_age_seconds,
    )
    request.session[SESSION_USER_ID_KEY] = user.id
    request.session[SESSION_CSRF_KEY] = secrets.token_urlsafe(32)
    adopt_latest_user_uploads(request, settings)
    return RedirectResponse(url=_safe_next(next_url), status_code=303)


@app.post("/logout")
def logout(request: Request, csrf_token: str = Form(...)):
    if not _valid_csrf(request, csrf_token):
        return JSONResponse({"detail": "Invalid CSRF token"}, status_code=403)
    token = request.session.get(SESSION_TOKEN_KEY)
    if isinstance(token, str):
        auth_store.revoke_session(token)
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


@app.get("/admin/users", response_class=HTMLResponse, name="admin_users")
def admin_users(request: Request):
    return _auth_template(
        request,
        "admin_users.html",
        {"users": auth_store.list_users(), "error": None, "message": None},
    )


@app.post("/admin/users", response_class=HTMLResponse)
def admin_create_user(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    role: str = Form(...),
    csrf_token: str = Form(...),
):
    if not _valid_csrf(request, csrf_token):
        return JSONResponse({"detail": "Invalid CSRF token"}, status_code=403)
    error = None
    try:
        if len(password) < 12:
            raise ValueError("Пароль должен содержать не менее 12 символов")
        auth_store.create_user(username, password, role)
    except (AuthStoreError, ValueError) as exc:
        error = str(exc)
    return _auth_template(
        request,
        "admin_users.html",
        {
            "users": auth_store.list_users(),
            "error": error,
            "message": None if error else "Пользователь создан.",
        },
        status_code=400 if error else 201,
    )


@app.post("/admin/users/{username}/disable")
def admin_disable_user(request: Request, username: str, csrf_token: str = Form(...)):
    if not _valid_csrf(request, csrf_token):
        return JSONResponse({"detail": "Invalid CSRF token"}, status_code=403)
    try:
        normalized_username = normalize_username(username)
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    current_user = getattr(request.state, "current_user", None)
    if current_user is not None and current_user.username == normalized_username:
        return JSONResponse({"detail": "Нельзя отключить текущего администратора"}, status_code=400)
    target = next(
        (user for user in auth_store.list_users() if user.username == normalized_username),
        None,
    )
    if target and target.role == "admin":
        active_admins = [
            user
            for user in auth_store.list_users(include_disabled=False)
            if user.role == "admin"
        ]
        if len(active_admins) <= 1:
            return JSONResponse({"detail": "Нельзя отключить последнего администратора"}, status_code=400)
    try:
        auth_store.disable_user(username)
    except AuthStoreError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=404)
    return RedirectResponse(url="/admin/users", status_code=303)


@app.post("/account/password")
def account_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    csrf_token: str = Form(...),
):
    if not _valid_csrf(request, csrf_token):
        return JSONResponse({"detail": "Invalid CSRF token"}, status_code=403)
    user = getattr(request.state, "current_user", None)
    if user is None or auth_store.authenticate(user.username, current_password) is None:
        return JSONResponse({"detail": "Current password is invalid"}, status_code=403)
    if len(new_password) < 12:
        return JSONResponse({"detail": "Password must contain at least 12 characters"}, status_code=400)
    auth_store.update_password(user.username, new_password)
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/ready")
def ready() -> JSONResponse:
    checks: dict[str, bool | str | None] = {
        "uploads_dir": False,
        "logs_dir": False,
        "runtime_dir": False,
        "auth_store": not settings.auth_enabled,
    }

    uploads_dir = settings.resolved_uploads_dir
    checks["uploads_dir"] = uploads_dir.exists() and uploads_dir.is_dir()
    logs_dir = settings.resolved_logs_dir
    checks["logs_dir"] = logs_dir.exists() and logs_dir.is_dir()
    runtime_dir = settings.resolved_runtime_dir
    checks["runtime_dir"] = runtime_dir.exists() and runtime_dir.is_dir()
    if settings.auth_enabled:
        try:
            auth_store.init_schema()
            checks["auth_store"] = settings.resolved_auth_db.is_file()
        except Exception:
            checks["auth_store"] = False

    is_ready = all(value is True for value in checks.values())
    return JSONResponse(
        {"status": "ready" if is_ready else "not_ready", "checks": checks},
        status_code=200 if is_ready else 503,
    )


@app.get("/", response_class=HTMLResponse, name="index")
def index(request: Request):
    return RedirectResponse(url=template_url_for(request)("almabi_dashboard"), status_code=307)


@app.get("/api/almabi/data-source")
def api_almabi_data_source(request: Request) -> dict:
    return almabi_data_context(request, settings)


@app.get("/api/almabi/dashboard")
def api_almabi_dashboard(
    request: Request,
    direction: list[str] | None = Query(None),
    project_group: list[str] | None = Query(None),
    project: list[str] | None = Query(None),
    contract: list[str] | None = Query(None),
    period_from: str | None = None,
    period_to: str | None = None,
) -> JSONResponse:
    try:
        payload = resolve_almabi_dashboard_api_data(
            request,
            settings,
            direction=direction,
            project_group=project_group,
            project=project,
            contract=contract,
            period_from=period_from,
            period_to=period_to,
        )
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    return JSONResponse(payload)


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


@app.post("/api/almabi/files/upload-set")
def api_almabi_upload_bundle(
    request: Request,
    buh_file: UploadFile | None = File(None),
    realization_file: UploadFile | None = File(None),
    cost_file: UploadFile | None = File(None),
    cost_nu_file: UploadFile | None = File(None),
    plan_forecast_file: UploadFile | None = File(None),
) -> JSONResponse:
    files = {
        "buh": buh_file,
        "realization": realization_file,
        "cost": cost_file,
        "cost_nu": cost_nu_file,
    }
    try:
        payload = store_almabi_upload_bundle(
            request,
            settings,
            files,
            plan_forecast_file=plan_forecast_file,
        )
        return JSONResponse(
            {
                **payload,
                "context": almabi_data_context(request, settings),
            },
            status_code=201,
        )
    finally:
        for file in files.values():
            if file is not None:
                file.file.close()
        if plan_forecast_file is not None:
            plan_forecast_file.file.close()


@app.get("/dashboard/almabi", response_class=HTMLResponse, name="almabi_dashboard")
def almabi_dashboard(request: Request):
    url_fn = template_url_for(request)
    return templated(
        request,
        "almabi_dashboard.html",
        {
            "dashboard": resolve_almabi_dashboard_data(request, settings),
            "current_nav_tab": "almabi_dashboard",
            "dashboard_page_title": "BI",
            "current_level": 1,
            "current_class_name": None,
            "current_service_name": None,
            "current_cost_title": None,
            "current_cost_key": None,
            "navigation_mode": "almabi_dashboard",
            "breadcrumbs": [{"name": APP_BRAND, "href": url_fn("almabi_dashboard")}],
        },
    )


@app.get("/dashboard/almabi-test", name="almabi_test_dashboard")
def almabi_test_dashboard_redirect(request: Request):
    return RedirectResponse(url=template_url_for(request)("almabi_dashboard"), status_code=307)


@app.get("/dashboard/almabi-charts", response_class=HTMLResponse, name="almabi_charts_page")
def almabi_charts_page(request: Request):
    url_fn = template_url_for(request)
    return templated(
        request,
        "almabi_charts.html",
        {
            "dashboard": resolve_almabi_dashboard_data(request, settings),
            "current_nav_tab": "almabi_charts",
            "current_level": 1,
            "current_class_name": None,
            "current_service_name": None,
            "current_cost_title": None,
            "current_cost_key": None,
            "navigation_mode": "almabi_charts",
            "breadcrumbs": [
                {"name": APP_BRAND, "href": url_fn("almabi_dashboard")},
                {"name": "Графики БДР", "href": url_fn("almabi_charts_page")},
            ],
        },
    )


@app.get("/dashboard/almabi-revenue-report", response_class=HTMLResponse, name="almabi_revenue_report_page")
def almabi_revenue_report_page(request: Request):
    url_fn = template_url_for(request)
    payload = load_revenue_report_payload(request, settings)
    return templated(
        request,
        "almabi_revenue_report.html",
        {
            "payload": payload,
            "current_nav_tab": "almabi_revenue_report",
            "current_level": 1,
            "current_class_name": None,
            "current_service_name": None,
            "current_cost_title": None,
            "current_cost_key": None,
            "navigation_mode": "almabi_revenue_report",
            "breadcrumbs": [
                {"name": APP_BRAND, "href": url_fn("almabi_dashboard")},
                {"name": "Выручка", "href": url_fn("almabi_revenue_report_page")},
            ],
        },
    )


@app.post("/api/almabi-revenue-report/upload")
async def api_almabi_revenue_report_upload(
    request: Request,
    buh_file: UploadFile = File(...),
    cost_file: UploadFile | None = File(default=None),
    revenue_file: UploadFile | None = File(default=None),
) -> JSONResponse:
    payload = await store_revenue_report_upload(
        request,
        settings,
        buh_file=buh_file,
        cost_file=cost_file,
        revenue_file=revenue_file,
    )
    return JSONResponse(payload, status_code=201)


@app.get("/api/almabi-revenue-report/data")
def api_almabi_revenue_report_data(request: Request) -> JSONResponse:
    return JSONResponse(load_revenue_report_payload(request, settings))


@app.get("/dashboard/almabi-cost-report", response_class=HTMLResponse, name="almabi_cost_report_page")
def almabi_cost_report_page(request: Request):
    url_fn = template_url_for(request)
    payload = load_cost_report_payload(request, settings)
    return templated(
        request,
        "almabi_cost_report.html",
        {
            "payload": payload,
            "current_nav_tab": "almabi_cost_report",
            "current_level": 1,
            "current_class_name": None,
            "current_service_name": None,
            "current_cost_title": None,
            "current_cost_key": None,
            "navigation_mode": "almabi_cost_report",
            "breadcrumbs": [
                {"name": APP_BRAND, "href": url_fn("almabi_dashboard")},
                {"name": "Себестоимость", "href": url_fn("almabi_cost_report_page")},
            ],
        },
    )


@app.post("/api/almabi-cost-report/upload")
async def api_almabi_cost_report_upload(
    request: Request,
    buh_file: UploadFile = File(...),
    cost_file: UploadFile | None = File(default=None),
    revenue_file: UploadFile | None = File(default=None),
) -> JSONResponse:
    payload = await store_cost_report_upload(
        request,
        settings,
        buh_file=buh_file,
        cost_file=cost_file,
        revenue_file=revenue_file,
    )
    return JSONResponse(payload, status_code=201)


@app.get("/api/almabi-cost-report/data")
def api_almabi_cost_report_data(request: Request) -> JSONResponse:
    return JSONResponse(load_cost_report_payload(request, settings))


@app.get("/dashboard/almabi-other-income-report", response_class=HTMLResponse, name="almabi_other_income_report_page")
def almabi_other_income_report_page(request: Request):
    url_fn = template_url_for(request)
    payload = load_other_income_report_payload(request, settings)
    return templated(
        request,
        "almabi_other_income_report.html",
        {
            "payload": payload,
            "current_nav_tab": "almabi_other_income_report",
            "current_level": 1,
            "current_class_name": None,
            "current_service_name": None,
            "current_cost_title": None,
            "current_cost_key": None,
            "navigation_mode": "almabi_other_income_report",
            "breadcrumbs": [
                {"name": APP_BRAND, "href": url_fn("almabi_dashboard")},
                {"name": "Прочие доходы", "href": url_fn("almabi_other_income_report_page")},
            ],
        },
    )


@app.post("/api/almabi-other-income-report/upload")
async def api_almabi_other_income_report_upload(
    request: Request,
    buh_file: UploadFile = File(...),
    cost_file: UploadFile | None = File(default=None),
    revenue_file: UploadFile | None = File(default=None),
) -> JSONResponse:
    payload = await store_other_income_report_upload(
        request,
        settings,
        buh_file=buh_file,
        cost_file=cost_file,
        revenue_file=revenue_file,
    )
    return JSONResponse(payload, status_code=201)


@app.get("/api/almabi-other-income-report/data")
def api_almabi_other_income_report_data(request: Request) -> JSONResponse:
    return JSONResponse(load_other_income_report_payload(request, settings))


@app.get("/dashboard/almabi-other-expense-report", response_class=HTMLResponse, name="almabi_other_expense_report_page")
def almabi_other_expense_report_page(request: Request):
    url_fn = template_url_for(request)
    payload = load_other_expense_report_payload(request, settings)
    return templated(
        request,
        "almabi_other_expense_report.html",
        {
            "payload": payload,
            "current_nav_tab": "almabi_other_expense_report",
            "current_level": 1,
            "current_class_name": None,
            "current_service_name": None,
            "current_cost_title": None,
            "current_cost_key": None,
            "navigation_mode": "almabi_other_expense_report",
            "breadcrumbs": [
                {"name": APP_BRAND, "href": url_fn("almabi_dashboard")},
                {"name": "Прочие расходы", "href": url_fn("almabi_other_expense_report_page")},
            ],
        },
    )


@app.post("/api/almabi-other-expense-report/upload")
async def api_almabi_other_expense_report_upload(
    request: Request,
    buh_file: UploadFile = File(...),
    cost_file: UploadFile | None = File(default=None),
    revenue_file: UploadFile | None = File(default=None),
) -> JSONResponse:
    payload = await store_other_expense_report_upload(
        request,
        settings,
        buh_file=buh_file,
        cost_file=cost_file,
        revenue_file=revenue_file,
    )
    return JSONResponse(payload, status_code=201)


@app.get("/api/almabi-other-expense-report/data")
def api_almabi_other_expense_report_data(request: Request) -> JSONResponse:
    return JSONResponse(load_other_expense_report_payload(request, settings))


@app.get("/dashboard/almabi-commercial-expense-report", response_class=HTMLResponse, name="almabi_commercial_expense_report_page")
def almabi_commercial_expense_report_page(request: Request):
    url_fn = template_url_for(request)
    payload = load_commercial_expense_report_payload(request, settings)
    return templated(
        request,
        "almabi_commercial_expense_report.html",
        {
            "payload": payload,
            "current_nav_tab": "almabi_commercial_expense_report",
            "current_level": 1,
            "current_class_name": None,
            "current_service_name": None,
            "current_cost_title": None,
            "current_cost_key": None,
            "navigation_mode": "almabi_commercial_expense_report",
            "breadcrumbs": [
                {"name": APP_BRAND, "href": url_fn("almabi_dashboard")},
                {"name": "Коммерческие расходы", "href": url_fn("almabi_commercial_expense_report_page")},
            ],
        },
    )


@app.post("/api/almabi-commercial-expense-report/upload")
async def api_almabi_commercial_expense_report_upload(
    request: Request,
    buh_file: UploadFile = File(...),
    cost_file: UploadFile | None = File(default=None),
    revenue_file: UploadFile | None = File(default=None),
) -> JSONResponse:
    payload = await store_commercial_expense_report_upload(
        request,
        settings,
        buh_file=buh_file,
        cost_file=cost_file,
        revenue_file=revenue_file,
    )
    return JSONResponse(payload, status_code=201)


@app.get("/api/almabi-commercial-expense-report/data")
def api_almabi_commercial_expense_report_data(request: Request) -> JSONResponse:
    return JSONResponse(load_commercial_expense_report_payload(request, settings))


@app.get("/dashboard/almabi-management-expense-report", response_class=HTMLResponse, name="almabi_management_expense_report_page")
def almabi_management_expense_report_page(request: Request):
    url_fn = template_url_for(request)
    payload = load_management_expense_report_payload(request, settings)
    return templated(
        request,
        "almabi_management_expense_report.html",
        {
            "payload": payload,
            "current_nav_tab": "almabi_management_expense_report",
            "current_level": 1,
            "current_class_name": None,
            "current_service_name": None,
            "current_cost_title": None,
            "current_cost_key": None,
            "navigation_mode": "almabi_management_expense_report",
            "breadcrumbs": [
                {"name": APP_BRAND, "href": url_fn("almabi_dashboard")},
                {"name": "Управленческие расходы", "href": url_fn("almabi_management_expense_report_page")},
            ],
        },
    )


@app.post("/api/almabi-management-expense-report/upload")
async def api_almabi_management_expense_report_upload(
    request: Request,
    buh_file: UploadFile = File(...),
    cost_file: UploadFile | None = File(default=None),
    revenue_file: UploadFile | None = File(default=None),
) -> JSONResponse:
    payload = await store_management_expense_report_upload(
        request,
        settings,
        buh_file=buh_file,
        cost_file=cost_file,
        revenue_file=revenue_file,
    )
    return JSONResponse(payload, status_code=201)


@app.get("/api/almabi-management-expense-report/data")
def api_almabi_management_expense_report_data(request: Request) -> JSONResponse:
    return JSONResponse(load_management_expense_report_payload(request, settings))


@app.get("/dashboard/almabi-operating-profit-report", response_class=HTMLResponse, name="almabi_operating_profit_report_page")
def almabi_operating_profit_report_page(request: Request):
    url_fn = template_url_for(request)
    payload = load_operating_profit_report_payload(request, settings)
    return templated(
        request,
        "almabi_operating_profit_report.html",
        {
            "payload": payload,
            "current_nav_tab": "almabi_operating_profit_report",
            "current_level": 1,
            "current_class_name": None,
            "current_service_name": None,
            "current_cost_title": None,
            "current_cost_key": None,
            "navigation_mode": "almabi_operating_profit_report",
            "breadcrumbs": [
                {"name": APP_BRAND, "href": url_fn("almabi_dashboard")},
                {"name": "Операционная прибыль", "href": url_fn("almabi_operating_profit_report_page")},
            ],
        },
    )


@app.post("/api/almabi-operating-profit-report/upload")
async def api_almabi_operating_profit_report_upload(
    request: Request,
    buh_file: UploadFile = File(...),
    cost_file: UploadFile | None = File(default=None),
    revenue_file: UploadFile | None = File(default=None),
) -> JSONResponse:
    payload = await store_operating_profit_report_upload(
        request,
        settings,
        buh_file=buh_file,
        cost_file=cost_file,
        revenue_file=revenue_file,
    )
    return JSONResponse(payload, status_code=201)


@app.get("/api/almabi-operating-profit-report/data")
def api_almabi_operating_profit_report_data(request: Request) -> JSONResponse:
    return JSONResponse(load_operating_profit_report_payload(request, settings))


@app.get("/dashboard/almabi-profit-before-tax-report", response_class=HTMLResponse, name="almabi_profit_before_tax_report_page")
def almabi_profit_before_tax_report_page(request: Request):
    url_fn = template_url_for(request)
    payload = load_profit_before_tax_report_payload(request, settings)
    return templated(
        request,
        "almabi_profit_before_tax_report.html",
        {
            "payload": payload,
            "current_nav_tab": "almabi_profit_before_tax_report",
            "current_level": 1,
            "current_class_name": None,
            "current_service_name": None,
            "current_cost_title": None,
            "current_cost_key": None,
            "navigation_mode": "almabi_profit_before_tax_report",
            "breadcrumbs": [
                {"name": APP_BRAND, "href": url_fn("almabi_dashboard")},
                {"name": "Прибыль/убыток до налогообложения", "href": url_fn("almabi_profit_before_tax_report_page")},
            ],
        },
    )


@app.post("/api/almabi-profit-before-tax-report/upload")
async def api_almabi_profit_before_tax_report_upload(
    request: Request,
    buh_file: UploadFile = File(...),
    cost_file: UploadFile | None = File(default=None),
    revenue_file: UploadFile | None = File(default=None),
) -> JSONResponse:
    payload = await store_profit_before_tax_report_upload(
        request,
        settings,
        buh_file=buh_file,
        cost_file=cost_file,
        revenue_file=revenue_file,
    )
    return JSONResponse(payload, status_code=201)


@app.get("/api/almabi-profit-before-tax-report/data")
def api_almabi_profit_before_tax_report_data(request: Request) -> JSONResponse:
    return JSONResponse(load_profit_before_tax_report_payload(request, settings))


@app.get("/dashboard/almabi-taxes-report", response_class=HTMLResponse, name="almabi_taxes_report_page")
def almabi_taxes_report_page(request: Request):
    url_fn = template_url_for(request)
    payload = load_taxes_report_payload(request, settings)
    return templated(
        request,
        "almabi_taxes_report.html",
        {
            "payload": payload,
            "current_nav_tab": "almabi_taxes_report",
            "current_level": 1,
            "current_class_name": None,
            "current_service_name": None,
            "current_cost_title": None,
            "current_cost_key": None,
            "navigation_mode": "almabi_taxes_report",
            "breadcrumbs": [
                {"name": APP_BRAND, "href": url_fn("almabi_dashboard")},
                {"name": "Налоги", "href": url_fn("almabi_taxes_report_page")},
            ],
        },
    )


@app.post("/api/almabi-taxes-report/upload")
async def api_almabi_taxes_report_upload(
    request: Request,
    buh_file: UploadFile = File(...),
    cost_file: UploadFile | None = File(default=None),
    revenue_file: UploadFile | None = File(default=None),
) -> JSONResponse:
    payload = await store_taxes_report_upload(
        request,
        settings,
        buh_file=buh_file,
        cost_file=cost_file,
        revenue_file=revenue_file,
    )
    return JSONResponse(payload, status_code=201)


@app.get("/api/almabi-taxes-report/data")
def api_almabi_taxes_report_data(request: Request) -> JSONResponse:
    return JSONResponse(load_taxes_report_payload(request, settings))


@app.get("/dashboard/almabi-net-profit-report", response_class=HTMLResponse, name="almabi_net_profit_report_page")
def almabi_net_profit_report_page(request: Request):
    url_fn = template_url_for(request)
    payload = load_net_profit_report_payload(request, settings)
    return templated(
        request,
        "almabi_net_profit_report.html",
        {
            "payload": payload,
            "current_nav_tab": "almabi_net_profit_report",
            "current_level": 1,
            "current_class_name": None,
            "current_service_name": None,
            "current_cost_title": None,
            "current_cost_key": None,
            "navigation_mode": "almabi_net_profit_report",
            "breadcrumbs": [
                {"name": APP_BRAND, "href": url_fn("almabi_dashboard")},
                {"name": "Чистая прибыль", "href": url_fn("almabi_net_profit_report_page")},
            ],
        },
    )


@app.post("/api/almabi-net-profit-report/upload")
async def api_almabi_net_profit_report_upload(
    request: Request,
    buh_file: UploadFile = File(...),
    cost_file: UploadFile | None = File(default=None),
    revenue_file: UploadFile | None = File(default=None),
) -> JSONResponse:
    payload = await store_net_profit_report_upload(
        request,
        settings,
        buh_file=buh_file,
        cost_file=cost_file,
        revenue_file=revenue_file,
    )
    return JSONResponse(payload, status_code=201)


@app.get("/api/almabi-net-profit-report/data")
def api_almabi_net_profit_report_data(request: Request) -> JSONResponse:
    return JSONResponse(load_net_profit_report_payload(request, settings))


@app.get("/dashboard/almabi-test-excel", response_class=HTMLResponse, name="almabi_test_excel_page")
def almabi_test_excel_page(request: Request):
    url_fn = template_url_for(request)
    page = load_test_excel_page_payload(request, settings)
    return templated(
        request,
        "almabi_test_excel.html",
        {
            "page": page,
            "revenue": page["revenue"],
            "cost": page["cost"],
            "projects": page["projects"],
            "buh": page["buh"],
            "active_tab": page["active_tab"],
            "current_nav_tab": "almabi_test_excel",
            "current_level": 1,
            "current_class_name": None,
            "current_service_name": None,
            "current_cost_title": None,
            "current_cost_key": None,
            "navigation_mode": "almabi_test_excel",
            "breadcrumbs": [
                {"name": APP_BRAND, "href": url_fn("almabi_dashboard")},
                {"name": "Тест Excel", "href": url_fn("almabi_test_excel_page")},
            ],
        },
    )


@app.post("/api/almabi-test-excel/revenue/upload")
async def api_almabi_test_excel_revenue_upload(request: Request, file: UploadFile = File(...)) -> JSONResponse:
    payload = await store_test_excel_revenue_upload(request, settings, file)
    return JSONResponse(payload, status_code=201)


@app.post("/api/almabi-test-excel/cost/upload")
async def api_almabi_test_excel_cost_upload(
    request: Request,
    cost_file: UploadFile = File(...),
    projects_file: UploadFile | None = File(default=None),
) -> JSONResponse:
    payload = await store_test_excel_cost_upload(
        request,
        settings,
        cost_file=cost_file,
        projects_file=projects_file,
    )
    return JSONResponse(payload, status_code=201)


@app.post("/api/almabi-test-excel/buh/upload")
async def api_almabi_test_excel_buh_upload(
    request: Request,
    buh_file: UploadFile = File(...),
    cost_file: UploadFile | None = File(default=None),
    revenue_file: UploadFile | None = File(default=None),
) -> JSONResponse:
    payload = await store_test_excel_buh_upload(
        request,
        settings,
        buh_file=buh_file,
        cost_file=cost_file,
        revenue_file=revenue_file,
    )
    return JSONResponse(payload, status_code=201)


@app.post("/api/almabi-test-excel/projects/upload")
async def api_almabi_test_excel_projects_upload(request: Request, file: UploadFile = File(...)) -> JSONResponse:
    payload = await store_test_excel_projects_upload(request, settings, file)
    return JSONResponse(payload, status_code=201)


@app.get("/api/almabi-test-excel/revenue/data")
def api_almabi_test_excel_revenue_data(request: Request) -> JSONResponse:
    return JSONResponse(load_test_excel_revenue_payload(request, settings))


@app.get("/api/almabi-test-excel/cost/data")
def api_almabi_test_excel_cost_data(request: Request) -> JSONResponse:
    return JSONResponse(load_test_excel_cost_payload(request, settings))


@app.get("/api/almabi-test-excel/projects/data")
def api_almabi_test_excel_projects_data(request: Request) -> JSONResponse:
    return JSONResponse(load_test_excel_projects_payload(request, settings))


@app.get("/api/almabi-test-excel/buh/data")
def api_almabi_test_excel_buh_data(request: Request) -> JSONResponse:
    return JSONResponse(load_test_excel_buh_payload(request, settings))


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
