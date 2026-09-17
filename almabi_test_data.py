from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from copy import deepcopy
from pathlib import Path
from typing import Any

from almabi_data_source import (
    adopt_latest_user_uploads,
    get_almabi_plan_forecast_path,
    get_almabi_upload_paths,
    get_almabi_upload_set,
)
from almabi_file_validation import REQUIRED_EXPORT_TYPES
from almabi_pipeline import PipelineResult
from almabi_plan_forecast_parser import PlanForecastParseResult, parse_plan_forecast_workbook
from almabi_test_builder import (
    build_empty_test_dashboard,
    build_test_dashboard_from_pipeline,
    filter_facts_by_dimensions_and_period,
    has_active_dimension_filters,
    join_filter_values,
    strip_non_project_kpi_facts,
)
from almabi_test_pipeline import TestPipelineResult, run_test_pipeline
from settings import Settings
from starlette.requests import Request

logger = logging.getLogger("almabi.dashboard")

# Меняйте при правках pipeline/dashboard — сбрасывает in-memory кэш.
PIPELINE_BUILD_ID = "dashboard_perf_pq_dedupe_v1"

FileCacheKey = tuple[tuple[str, str, int, int], ...]
FilterCacheKey = tuple[tuple[str, str], ...]
DashboardCacheKey = tuple[FileCacheKey, tuple[str, int, int] | None, FilterCacheKey]

_pipeline_cache: dict[FileCacheKey, TestPipelineResult] = {}
_plan_cache: dict[tuple[str, int, int], PlanForecastParseResult] = {}
_dashboard_build_lock = threading.Lock()
_dashboard_build_states_lock = threading.Lock()
_dashboard_build_states: OrderedDict[FileCacheKey, dict[str, Any]] = OrderedDict()
_DASHBOARD_BUILD_STATES_MAX_ENTRIES = 32


class _DashboardLruCache:
    def __init__(self, max_entries: int) -> None:
        self.max_entries = max(1, max_entries)
        self._entries: OrderedDict[DashboardCacheKey, dict[str, Any]] = OrderedDict()
        self._lock = threading.RLock()

    def get(self, key: DashboardCacheKey) -> dict[str, Any] | None:
        with self._lock:
            value = self._entries.get(key)
            if value is None:
                return None
            self._entries.move_to_end(key)
            return value

    def set(self, key: DashboardCacheKey, value: dict[str, Any]) -> None:
        with self._lock:
            if key in self._entries:
                self._entries.move_to_end(key)
            self._entries[key] = value
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)

    def contains(self, key: DashboardCacheKey) -> bool:
        with self._lock:
            return key in self._entries


_dashboard_cache = _DashboardLruCache(max_entries=8)


def _configure_dashboard_cache(settings: Settings) -> None:
    global _dashboard_cache
    max_entries = settings.dashboard_cache_max_entries
    if _dashboard_cache.max_entries != max_entries:
        _dashboard_cache = _DashboardLruCache(max_entries=max_entries)


def _file_signature(path: Path) -> tuple[str, int, int]:
    stat = path.stat()
    return (str(path), int(stat.st_mtime_ns), int(stat.st_size))


def _pipeline_cache_key(upload_paths: dict[str, Path]) -> FileCacheKey:
    parts: list[tuple[str, str, int, int]] = [("pipeline", PIPELINE_BUILD_ID, 0, 0)]
    parts.extend(
        (export_type, *_file_signature(path))
        for export_type, path in sorted(upload_paths.items())
    )
    return tuple(parts)


def _base_dashboard_cache_key(
    request: Request,
    settings: Settings,
    upload_paths: dict[str, Path],
) -> DashboardCacheKey:
    plan_path = get_almabi_plan_forecast_path(request, settings)
    plan_key = _file_signature(plan_path) if plan_path is not None else None
    return (_pipeline_cache_key(upload_paths), plan_key, _normalized_filters({}))


def _public_dashboard_build_state(state: dict[str, Any]) -> dict[str, Any]:
    started_at = state.get("started_at")
    queued_at = float(state.get("queued_at") or time.time())
    elapsed_from = float(started_at or queued_at)
    elapsed_until = float(state.get("finished_at") or time.time())
    return {
        "state": state["state"],
        "elapsed_seconds": max(0, round(elapsed_until - elapsed_from)),
        "message": state["message"],
    }


def _set_dashboard_build_state(
    cache_key: FileCacheKey,
    *,
    state: str,
    message: str,
    started_at: float | None = None,
) -> dict[str, Any]:
    with _dashboard_build_states_lock:
        current = _dashboard_build_states.get(cache_key, {})
        updated = {
            "state": state,
            "message": message,
            "queued_at": current.get("queued_at", time.time()),
            "started_at": started_at if started_at is not None else current.get("started_at"),
            "finished_at": (
                current.get("finished_at") or time.time()
                if state in {"ready", "failed"}
                else None
            ),
        }
        _dashboard_build_states[cache_key] = updated
        _dashboard_build_states.move_to_end(cache_key)
        while len(_dashboard_build_states) > _DASHBOARD_BUILD_STATES_MAX_ENTRIES:
            _dashboard_build_states.popitem(last=False)
        return _public_dashboard_build_state(updated)


def prepare_almabi_dashboard_warmup(
    request: Request,
    settings: Settings,
) -> tuple[dict[str, Any], bool]:
    """Пометить текущий комплект файлов для фоновой single-flight сборки."""
    adopt_latest_user_uploads(request, settings)
    upload_paths = get_almabi_upload_paths(request, settings)
    missing = [
        export_type for export_type in REQUIRED_EXPORT_TYPES if export_type not in upload_paths
    ]
    if missing:
        return {
            "state": "waiting_for_files",
            "elapsed_seconds": 0,
            "message": "Для сборки нужны бухрегистр, реализация и себестоимость.",
        }, False

    cache_key = _pipeline_cache_key(upload_paths)
    if _dashboard_cache.contains(_base_dashboard_cache_key(request, settings, upload_paths)):
        return _set_dashboard_build_state(
            cache_key,
            state="ready",
            message="Дашборд готов.",
        ), False
    with _dashboard_build_states_lock:
        current = _dashboard_build_states.get(cache_key)
        if current and current["state"] in {"queued", "running", "ready"}:
            return _public_dashboard_build_state(current), False
        queued = {
            "state": "queued",
            "message": "Сборка дашборда поставлена в очередь.",
            "queued_at": time.time(),
            "started_at": None,
            "finished_at": None,
        }
        _dashboard_build_states[cache_key] = queued
        _dashboard_build_states.move_to_end(cache_key)
        while len(_dashboard_build_states) > _DASHBOARD_BUILD_STATES_MAX_ENTRIES:
            _dashboard_build_states.popitem(last=False)
        return _public_dashboard_build_state(queued), True


def get_almabi_dashboard_warmup_status(
    request: Request,
    settings: Settings,
) -> dict[str, Any]:
    """Вернуть короткий статус фоновой сборки для polling из браузера."""
    adopt_latest_user_uploads(request, settings)
    upload_paths = get_almabi_upload_paths(request, settings)
    missing = [
        export_type for export_type in REQUIRED_EXPORT_TYPES if export_type not in upload_paths
    ]
    if missing:
        return {
            "state": "waiting_for_files",
            "elapsed_seconds": 0,
            "message": "Для сборки нужны бухрегистр, реализация и себестоимость.",
        }
    cache_key = _pipeline_cache_key(upload_paths)
    if _dashboard_cache.contains(_base_dashboard_cache_key(request, settings, upload_paths)):
        return _set_dashboard_build_state(
            cache_key,
            state="ready",
            message="Дашборд готов.",
        )
    with _dashboard_build_states_lock:
        current = _dashboard_build_states.get(cache_key)
        if current is None:
            return {
                "state": "idle",
                "elapsed_seconds": 0,
                "message": "Фоновая сборка не запускалась.",
            }
        return _public_dashboard_build_state(current)


def build_almabi_dashboard_warmup_placeholder(status: dict[str, Any]) -> dict[str, Any]:
    """Лёгкая HTML-модель, пока тяжёлая сборка выполняется вне запроса страницы."""
    dashboard = build_empty_test_dashboard()
    dashboard["meta"] = {
        **(dashboard.get("meta") or {}),
        "mode": "bi",
        "title": "BI",
        "message": status.get("message") or "Дашборд собирается в фоне.",
        "dashboard_build": status,
    }
    return dashboard


def run_almabi_dashboard_warmup(request: Request, settings: Settings) -> None:
    """Собрать базовый dashboard после upload, не удерживая запрос браузера."""
    adopt_latest_user_uploads(request, settings)
    upload_paths = get_almabi_upload_paths(request, settings)
    if any(export_type not in upload_paths for export_type in REQUIRED_EXPORT_TYPES):
        return
    cache_key = _pipeline_cache_key(upload_paths)

    with _dashboard_build_lock:
        _set_dashboard_build_state(
            cache_key,
            state="running",
            message="Файлы обрабатываются, дашборд собирается.",
            started_at=time.time(),
        )
        try:
            resolve_almabi_dashboard_data(request, settings)
        except Exception:
            logger.exception("dashboard.warmup failed")
            _set_dashboard_build_state(
                cache_key,
                state="failed",
                message="Не удалось собрать дашборд. Проверьте журнал сервера.",
            )
            return
        _set_dashboard_build_state(
            cache_key,
            state="ready",
            message="Дашборд готов.",
        )


def _normalized_filters(filters: dict[str, str | list[str] | None]) -> FilterCacheKey:
    return tuple(
        (name, join_filter_values(filters.get(name)))
        for name in (
            "direction",
            "project_group",
            "project",
            "contract",
            "period_from",
            "period_to",
        )
    )


def _april_cost_nu_from_dashboard(data: dict[str, Any]) -> float | None:
    for row in data.get("summary_rows") or []:
        if row.get("name") != "Себестоимость":
            continue
        values = (row.get("values") or {}).get("Факт НУ") or {}
        return sum(
            float(value or 0)
            for period, value in values.items()
            if period == "Апрель" or period.endswith("-04")
        )
    return None


def _should_skip_duplicate_analysis(settings: Settings) -> bool:
    return settings.pipeline_skip_audit_when_disabled and not settings.audit_detail_enabled


def _load_pipeline(
    upload_paths: dict[str, Path],
    settings: Settings,
) -> tuple[FileCacheKey, TestPipelineResult]:
    cache_key = _pipeline_cache_key(upload_paths)
    pipeline = _pipeline_cache.get(cache_key)
    if pipeline is None:
        pipeline = run_test_pipeline(
            upload_paths,
            logs_dir=settings.resolved_logs_dir if settings.audit_detail_enabled else None,
            write_audit=settings.audit_detail_enabled,
            skip_duplicate_analysis=_should_skip_duplicate_analysis(settings),
        )
        _pipeline_cache.clear()
        _pipeline_cache[cache_key] = pipeline
    return cache_key, pipeline


def _load_plan(
    path: Path | None,
) -> tuple[tuple[str, int, int] | None, PlanForecastParseResult | None]:
    if path is None:
        return None, None
    signature = _file_signature(path)
    parsed = _plan_cache.get(signature)
    if parsed is None:
        parsed = parse_plan_forecast_workbook(path)
        _plan_cache.clear()
        _plan_cache[signature] = parsed
    return signature, parsed


def _build_dashboard_meta(
    data: dict[str, Any],
    *,
    upload_paths: dict[str, Path],
    applied_filters: FilterCacheKey,
) -> dict[str, Any]:
    cost_nu_loaded = "cost_nu" in upload_paths
    meta = dict(data.get("meta") or {})
    meta.update(
        {
            "mode": "bi",
            "title": "BI",
            "description": "Структура «Уровни для дашборда» + join направления как в Power Query.",
            "levels_spec": "fixtures/almabi_dashboard_levels.json",
            "pipeline_build_id": PIPELINE_BUILD_ID,
            "cost_nu_loaded": cost_nu_loaded,
            "april_cost_nu": _april_cost_nu_from_dashboard(data),
            "applied_filters": {name: value for name, value in applied_filters if value},
            "project_scoped_view": has_active_dimension_filters(applied_filters),
        }
    )
    if not cost_nu_loaded:
        meta.setdefault("warnings", [])
        warning = "Файл «Себестоимость НУ» не загружен — колонка «Факт НУ» по себестоимости будет нулевой."
        if warning not in meta["warnings"]:
            meta["warnings"] = [warning, *meta["warnings"]]
    return meta


def _decorate_dashboard_meta(
    data: dict[str, Any],
    *,
    upload_paths: dict[str, Path],
    applied_filters: FilterCacheKey,
) -> dict[str, Any]:
    data["meta"] = _build_dashboard_meta(
        data,
        upload_paths=upload_paths,
        applied_filters=applied_filters,
    )
    return data


def _materialize_dashboard_response(
    cached: dict[str, Any],
    *,
    settings: Settings,
    upload_paths: dict[str, Path],
    applied_filters: FilterCacheKey,
) -> dict[str, Any]:
    if settings.dashboard_skip_deep_copy:
        return {
            **cached,
            "meta": _build_dashboard_meta(
                cached,
                upload_paths=upload_paths,
                applied_filters=applied_filters,
            ),
        }
    return _decorate_dashboard_meta(
        deepcopy(cached),
        upload_paths=upload_paths,
        applied_filters=applied_filters,
    )


def _strip_admin_audit_summary(dashboard: dict[str, Any], settings: Settings, request: Request) -> None:
    user = getattr(request.state, "current_user", None)
    if not settings.audit_detail_enabled or getattr(user, "role", None) != "admin":
        audit = dashboard.get("meta", {}).get("audit")
        if isinstance(audit, dict):
            audit.pop("summary", None)


def resolve_almabi_dashboard_api_data(
    request: Request,
    settings: Settings,
    *,
    direction: str | list[str] | None = None,
    project_group: str | list[str] | None = None,
    project: str | list[str] | None = None,
    contract: str | list[str] | None = None,
    period_from: str | None = None,
    period_to: str | None = None,
) -> dict[str, Any]:
    """Собрать dashboard из отфильтрованных сырых Fact."""
    started = time.perf_counter()
    _configure_dashboard_cache(settings)
    normalized = _normalized_filters(
        {
            "direction": direction,
            "project_group": project_group,
            "project": project,
            "contract": contract,
            "period_from": period_from,
            "period_to": period_to,
        }
    )
    filters = dict(normalized)
    adopt_latest_user_uploads(request, settings)
    upload_paths = get_almabi_upload_paths(request, settings)
    upload_set = get_almabi_upload_set(request)
    upload_names = {
        export_type: meta.get("original", f"{export_type}.xlsx")
        for export_type, meta in upload_set.items()
    }
    missing_required = [
        export_type for export_type in REQUIRED_EXPORT_TYPES if export_type not in upload_paths
    ]
    if missing_required:
        filter_facts_by_dimensions_and_period([], **filters)
        data = build_empty_test_dashboard()
        data["meta"] = {
            **data.get("meta", {}),
            "upload_files": upload_names,
            "missing_exports": missing_required,
            "message": "Загрузите обязательные выгрузки: бухрегистр, реализация и себестоимость.",
        }
        dashboard = _decorate_dashboard_meta(
            data,
            upload_paths=upload_paths,
            applied_filters=normalized,
        )
        _strip_admin_audit_summary(dashboard, settings, request)
        if settings.perf_log_enabled:
            logger.info("dashboard.resolve empty exports %.3fs", time.perf_counter() - started)
        return dashboard

    pipeline_key, pipeline = _load_pipeline(upload_paths, settings)
    plan_key, parsed_plan = _load_plan(get_almabi_plan_forecast_path(request, settings))
    cache_key: DashboardCacheKey = (pipeline_key, plan_key, normalized)
    cached = _dashboard_cache.get(cache_key)
    cache_hit = cached is not None
    if cached is None:
        plan_facts = list(parsed_plan.plan_facts) if parsed_plan else []
        forecast_facts = list(parsed_plan.forecast_facts) if parsed_plan else []
        plan_warnings = list(parsed_plan.warnings) if parsed_plan else []

        filter_facts_by_dimensions_and_period(
            [*pipeline.result.facts, *plan_facts, *forecast_facts],
            **filters,
            apply_period=False,
        )
        filtered_facts = filter_facts_by_dimensions_and_period(
            pipeline.result.facts,
            **filters,
            validate_values=False,
        )
        scenario_filters: dict[str, Any] = {
            **filters,
            "period_from": None,
            "period_to": None,
            "apply_period": False,
            "validate_values": False,
        }
        filtered_plan = filter_facts_by_dimensions_and_period(
            plan_facts,
            **scenario_filters,
        )
        filtered_forecast = filter_facts_by_dimensions_and_period(
            forecast_facts,
            **scenario_filters,
        )
        project_scoped_view = has_active_dimension_filters(normalized)
        if project_scoped_view:
            filtered_facts = strip_non_project_kpi_facts(filtered_facts)
            filtered_plan = strip_non_project_kpi_facts(filtered_plan)
            filtered_forecast = strip_non_project_kpi_facts(filtered_forecast)
        actual_years = {
            fact.period[:4]
            for fact in pipeline.result.facts
            if fact.period and len(fact.period) == 7 and fact.period[4] == "-"
        }
        if len(actual_years) > 1 and (plan_facts or forecast_facts):
            warning = (
                "План/прогноз содержит month-only периоды: period_from/period_to "
                "применяются только к факту, аналитические фильтры применяются ко всем сценариям."
            )
            if warning not in plan_warnings:
                plan_warnings.append(warning)

        filtered_pipeline = TestPipelineResult(
            result=PipelineResult(
                facts=filtered_facts,
                months=list(pipeline.result.months),
                warnings=list(pipeline.result.warnings),
                realization_rows=list(pipeline.result.realization_rows),
            ),
            audit=pipeline.audit,
            audit_path=pipeline.audit_path,
            pq_cost_rows=(
                None
                if any(value for _, value in normalized)
                else pipeline.pq_cost_rows
            ),
        )
        cached = build_test_dashboard_from_pipeline(
            filtered_pipeline,
            upload_names=upload_names,
            plan_facts=filtered_plan,
            forecast_facts=filtered_forecast,
            plan_warnings=plan_warnings,
            project_scoped_view=project_scoped_view,
        )
        if any(value for _, value in normalized):
            full_key: DashboardCacheKey = (pipeline_key, plan_key, _normalized_filters({}))
            full_dashboard = _dashboard_cache.get(full_key)
            if full_dashboard is None:
                full_dashboard = build_test_dashboard_from_pipeline(
                    pipeline,
                    upload_names=upload_names,
                    plan_facts=plan_facts,
                    forecast_facts=forecast_facts,
                    plan_warnings=list(plan_warnings),
                )
                _dashboard_cache.set(full_key, full_dashboard)
            cached["filters"] = dict(full_dashboard.get("filters") or {})
            cached["filter_tree"] = list(full_dashboard.get("filter_tree") or [])
            cached["available_periods"] = list(
                full_dashboard.get("available_periods")
                or full_dashboard.get("periods")
                or []
            )
            cached["data_periods"] = list(
                full_dashboard.get("data_periods")
                or full_dashboard.get("months")
                or []
            )
            cached["period_labels"] = {
                **(full_dashboard.get("period_labels") or {}),
                **(cached.get("period_labels") or {}),
            }
        _dashboard_cache.set(cache_key, cached)
    dashboard = _materialize_dashboard_response(
        cached,
        settings=settings,
        upload_paths=upload_paths,
        applied_filters=normalized,
    )
    _strip_admin_audit_summary(dashboard, settings, request)
    if settings.perf_log_enabled:
        logger.info(
            "dashboard.resolve cache_hit=%s filters=%s %.3fs",
            cache_hit,
            normalized,
            time.perf_counter() - started,
        )
    return dashboard


def resolve_almabi_dashboard_data(request: Request, settings: Settings) -> dict[str, Any]:
    """Безфильтровый resolver для HTML."""
    return resolve_almabi_dashboard_api_data(request, settings)


def resolve_almabi_test_dashboard_data(request: Request, settings: Settings) -> dict[str, Any]:
    return resolve_almabi_dashboard_data(request, settings)
