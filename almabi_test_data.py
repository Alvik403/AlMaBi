from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from almabi_data_source import get_almabi_plan_forecast_path, get_almabi_upload_paths, get_almabi_upload_set
from almabi_file_validation import REQUIRED_EXPORT_TYPES
from almabi_pipeline import PipelineResult
from almabi_plan_forecast_parser import PlanForecastParseResult, parse_plan_forecast_workbook
from almabi_test_builder import (
    build_empty_test_dashboard,
    build_test_dashboard_from_pipeline,
    filter_facts_by_dimensions_and_period,
    join_filter_values,
)
from almabi_test_pipeline import TestPipelineResult, run_test_pipeline
from settings import Settings
from starlette.requests import Request

# Меняйте при правках pipeline/dashboard — сбрасывает in-memory кэш.
PIPELINE_BUILD_ID = "revenue_direction_by_amount_v4"

FileCacheKey = tuple[tuple[str, str, int, int], ...]
FilterCacheKey = tuple[tuple[str, str], ...]

_pipeline_cache: dict[FileCacheKey, TestPipelineResult] = {}
_plan_cache: dict[tuple[str, int, int], PlanForecastParseResult] = {}
_dashboard_cache: dict[
    tuple[FileCacheKey, tuple[str, int, int] | None, FilterCacheKey],
    dict[str, Any],
] = {}


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


def _decorate_dashboard_meta(
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
        }
    )
    if not cost_nu_loaded:
        meta.setdefault("warnings", [])
        warning = "Файл «Себестоимость НУ» не загружен — колонка «Факт НУ» по себестоимости будет нулевой."
        if warning not in meta["warnings"]:
            meta["warnings"].insert(0, warning)
    data["meta"] = meta
    return data


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
        return _decorate_dashboard_meta(
            data,
            upload_paths=upload_paths,
            applied_filters=normalized,
        )

    pipeline_key, pipeline = _load_pipeline(upload_paths, settings)
    plan_key, parsed_plan = _load_plan(get_almabi_plan_forecast_path(request, settings))
    cache_key = (pipeline_key, plan_key, normalized)
    cached = _dashboard_cache.get(cache_key)
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
            # PQ rows are not independently scoped by all BI dimensions.
            # For a filtered rebuild use the already scoped Fact set so that
            # cost structure, charts and drill-down cannot retain full totals.
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
        )
        if any(value for _, value in normalized):
            full_key = (pipeline_key, plan_key, _normalized_filters({}))
            full_dashboard = _dashboard_cache.get(full_key)
            if full_dashboard is None:
                full_dashboard = build_test_dashboard_from_pipeline(
                    pipeline,
                    upload_names=upload_names,
                    plan_facts=plan_facts,
                    forecast_facts=forecast_facts,
                    plan_warnings=list(plan_warnings),
                )
                _dashboard_cache[full_key] = full_dashboard
            cached["filters"] = deepcopy(full_dashboard.get("filters") or {})
            cached["filter_tree"] = deepcopy(full_dashboard.get("filter_tree") or [])
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
        _dashboard_cache[cache_key] = cached
    dashboard = _decorate_dashboard_meta(
        deepcopy(cached),
        upload_paths=upload_paths,
        applied_filters=normalized,
    )
    user = getattr(request.state, "current_user", None)
    if not settings.audit_detail_enabled or getattr(user, "role", None) != "admin":
        audit = dashboard.get("meta", {}).get("audit")
        if isinstance(audit, dict):
            audit.pop("summary", None)
    return dashboard


def resolve_almabi_dashboard_data(request: Request, settings: Settings) -> dict[str, Any]:
    """Безфильтровый resolver для HTML."""
    return resolve_almabi_dashboard_api_data(request, settings)


def resolve_almabi_test_dashboard_data(request: Request, settings: Settings) -> dict[str, Any]:
    return resolve_almabi_dashboard_data(request, settings)
