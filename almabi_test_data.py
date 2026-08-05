from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from almabi_data_source import get_almabi_plan_forecast_path, get_almabi_upload_paths, get_almabi_upload_set
from almabi_file_validation import REQUIRED_EXPORT_TYPES
from almabi_test_builder import build_empty_test_dashboard, load_test_dashboard_from_exports
from settings import Settings
from starlette.requests import Request

# Меняйте при правках пайплайна НУ — сбрасывает in-memory кэш дашборда.
PIPELINE_BUILD_ID = "cost_nu_etalon_reconcile_v3"

_dashboard_cache: dict[tuple[tuple[str, str, int, int], ...], dict[str, Any]] = {}


def _file_signature(path: Path) -> tuple[str, int, int]:
    stat = path.stat()
    return (str(path), int(stat.st_mtime_ns), int(stat.st_size))


def _dashboard_cache_key(upload_paths: dict[str, Path], plan_forecast_path: Path | None) -> tuple[tuple[str, str, int, int], ...]:
    parts: list[tuple[str, str, int, int]] = [("pipeline", PIPELINE_BUILD_ID, 0, 0)]
    parts.extend(
        (export_type, *_file_signature(path))
        for export_type, path in sorted(upload_paths.items())
    )
    if plan_forecast_path:
        parts.append(("plan_forecast", *_file_signature(plan_forecast_path)))
    return tuple(parts)


def _april_cost_nu_from_dashboard(data: dict[str, Any]) -> float | None:
    for row in data.get("summary_rows") or []:
        if row.get("name") != "Себестоимость":
            continue
        values = (row.get("values") or {}).get("Факт НУ") or {}
        return float(values.get("Апрель") or 0)
    return None


def resolve_almabi_dashboard_data(request: Request, settings: Settings) -> dict[str, Any]:
    """BI-дашборд: структура из spec, данные через PQ-join при загрузке выгрузок."""
    upload_paths = get_almabi_upload_paths(request, settings)
    upload_set = get_almabi_upload_set(request)
    upload_names = {
        export_type: meta.get("original", f"{export_type}.xlsx")
        for export_type, meta in upload_set.items()
    }
    missing_required = [export_type for export_type in REQUIRED_EXPORT_TYPES if export_type not in upload_paths]

    if missing_required:
        data = build_empty_test_dashboard()
        data["meta"] = {
            **data.get("meta", {}),
            "upload_files": upload_names,
            "missing_exports": missing_required,
            "message": "Загрузите обязательные выгрузки: бухрегистр, реализация и себестоимость.",
        }
        return data

    plan_forecast_path = get_almabi_plan_forecast_path(request, settings)
    cache_key = _dashboard_cache_key(upload_paths, plan_forecast_path)
    cached = _dashboard_cache.get(cache_key)
    if cached is None:
        cached = load_test_dashboard_from_exports(
            upload_paths,
            upload_names=upload_names,
            logs_dir=settings.resolved_logs_dir,
            plan_forecast_path=plan_forecast_path,
        )
        _dashboard_cache.clear()
        _dashboard_cache[cache_key] = cached
    data = deepcopy(cached)
    april_cost_nu = _april_cost_nu_from_dashboard(data)
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
            "april_cost_nu": april_cost_nu,
        }
    )
    if not cost_nu_loaded:
        meta.setdefault("warnings", [])
        warning = "Файл «Себестоимость НУ» не загружен — колонка «Факт НУ» по себестоимости будет нулевой."
        if warning not in meta["warnings"]:
            meta["warnings"].insert(0, warning)
    data["meta"] = meta
    return data


def resolve_almabi_test_dashboard_data(request: Request, settings: Settings) -> dict[str, Any]:
    return resolve_almabi_dashboard_data(request, settings)
