from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import HTTPException, Request, UploadFile

from almabi_file_validation import (
    EXPORT_TYPES,
    REQUIRED_EXPORT_TYPES,
    EXPORT_LABELS,
    guess_export_type_from_filename,
    validate_almabi_export,
)
from settings import Settings


SESSION_ALMABI_UPLOAD_SET = "almabi_upload_set"
SESSION_ALMABI_PLAN_FORECAST = "almabi_plan_forecast"

_EXPORT_FIELD_NAMES = {
    "buh": "buh_file",
    "realization": "realization_file",
    "cost": "cost_file",
    "cost_nu": "cost_nu_file",
}


def get_almabi_upload_set(request: Request) -> dict[str, dict[str, str]]:
    stored = request.session.get(SESSION_ALMABI_UPLOAD_SET, {})
    if not isinstance(stored, dict):
        return {}
    return {
        key: value
        for key, value in stored.items()
        if key in EXPORT_TYPES and isinstance(value, dict)
    }


def get_almabi_upload_paths(request: Request, settings: Settings) -> dict[str, Path]:
    upload_set = get_almabi_upload_set(request)
    upload_dir = settings.resolved_uploads_dir / "almabi"
    paths: dict[str, Path] = {}
    for export_type, meta in upload_set.items():
        stored_name = meta.get("stored")
        if not stored_name:
            continue
        path = upload_dir / stored_name
        if path.exists():
            paths[export_type] = path
    return paths


def get_almabi_plan_forecast_path(request: Request, settings: Settings) -> Path | None:
    stored = request.session.get(SESSION_ALMABI_PLAN_FORECAST)
    if not isinstance(stored, dict):
        return None
    stored_name = stored.get("stored")
    if not stored_name:
        return None
    path = settings.resolved_uploads_dir / "almabi" / stored_name
    return path if path.exists() else None


def _upload_status(upload_set: dict[str, dict[str, str]], *, plan_forecast: dict[str, str] | None = None) -> dict[str, Any]:
    loaded = {export_type: upload_set[export_type].get("original") for export_type in EXPORT_TYPES if export_type in upload_set}
    missing_required = [export_type for export_type in REQUIRED_EXPORT_TYPES if export_type not in loaded]
    return {
        "loaded_exports": loaded,
        "missing_required": missing_required,
        "is_complete": not missing_required,
        "plan_forecast_file": (plan_forecast or {}).get("original"),
    }


def almabi_data_context(request: Request, settings: Settings) -> dict[str, Any]:
    upload_set = get_almabi_upload_set(request)
    plan_forecast = request.session.get(SESSION_ALMABI_PLAN_FORECAST)
    if not isinstance(plan_forecast, dict):
        plan_forecast = None
    upload_status = _upload_status(upload_set, plan_forecast=plan_forecast)
    return {
        "source": "upload",
        "title": "Выгрузки AlMaBi",
        "description": "Выгрузки 1С: бухрегистр, реализация, себестоимость (БУ/НУ) и план/прогноз.",
        "sources": [],
        "upload_file_name": None,
        "upload_files": upload_status["loaded_exports"],
        "plan_forecast_file": upload_status["plan_forecast_file"],
        "missing_exports": upload_status["missing_required"],
        "has_upload_file": upload_status["is_complete"],
        "fixtures": {},
    }


def _save_upload_file(settings: Settings, file: UploadFile) -> dict[str, Any]:
    original_name = Path(file.filename or "").name
    if not original_name:
        raise ValueError("Имя файла не передано")
    if Path(original_name).suffix.casefold() != ".xlsx":
        raise ValueError("Поддерживаются только файлы .xlsx")

    upload_dir = settings.resolved_uploads_dir / "almabi"
    upload_dir.mkdir(parents=True, exist_ok=True)
    incoming_dir = upload_dir / ".incoming"
    incoming_dir.mkdir(parents=True, exist_ok=True)

    temp_path = incoming_dir / f"upload-{uuid4().hex}.xlsx"

    try:
        with temp_path.open("wb") as output:
            while chunk := file.file.read(1024 * 1024):
                output.write(chunk)
        if temp_path.stat().st_size == 0:
            raise ValueError(f"Файл «{original_name}» пустой")
        validation = validate_almabi_export(temp_path)
        export_type = validation.export_type
        filename_hint = guess_export_type_from_filename(original_name)
        reassigned = False
        if filename_hint and filename_hint != export_type:
            reassigned = True
        stored_name = f"{export_type}-{uuid4().hex}.xlsx"
        final_path = upload_dir / stored_name
        temp_path.replace(final_path)
        return {
            "original": original_name,
            "stored": stored_name,
            "export_type": export_type,
            "validation": validation.to_dict(),
            "reassigned": reassigned,
            "selected_slot": None,
        }
    except ValueError:
        temp_path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        temp_path.unlink(missing_ok=True)
        raise ValueError(str(exc)) from exc


def _save_plan_forecast_file(settings: Settings, file: UploadFile) -> dict[str, str]:
    from almabi_plan_forecast_parser import validate_plan_forecast_workbook

    original_name = Path(file.filename or "").name
    if not original_name:
        raise ValueError("Имя файла не передано")
    if Path(original_name).suffix.casefold() != ".xlsx":
        raise ValueError("Поддерживаются только файлы .xlsx")

    upload_dir = settings.resolved_uploads_dir / "almabi"
    upload_dir.mkdir(parents=True, exist_ok=True)
    incoming_dir = upload_dir / ".incoming"
    incoming_dir.mkdir(parents=True, exist_ok=True)
    temp_path = incoming_dir / f"plan-forecast-{uuid4().hex}.xlsx"

    try:
        with temp_path.open("wb") as output:
            while chunk := file.file.read(1024 * 1024):
                output.write(chunk)
        if temp_path.stat().st_size == 0:
            raise ValueError(f"Файл «{original_name}» пустой")
        validate_plan_forecast_workbook(temp_path)
        stored_name = f"plan-forecast-{uuid4().hex}.xlsx"
        final_path = upload_dir / stored_name
        temp_path.replace(final_path)
        return {"original": original_name, "stored": stored_name}
    except ValueError:
        temp_path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        temp_path.unlink(missing_ok=True)
        raise ValueError(str(exc)) from exc


def store_almabi_upload_bundle(
    request: Request,
    settings: Settings,
    files: dict[str, UploadFile | None],
    *,
    plan_forecast_file: UploadFile | None = None,
) -> dict[str, Any]:
    incoming = [(slot, file) for slot, file in files.items() if file is not None]
    if not incoming and plan_forecast_file is None:
        raise HTTPException(status_code=400, detail="Передайте хотя бы один файл выгрузки или форму план/прогноз")

    upload_set = dict(get_almabi_upload_set(request))
    saved: dict[str, Any] = {}
    warnings: list[str] = []

    try:
        for slot, file in incoming:
            payload = _save_upload_file(settings, file)
            payload["selected_slot"] = slot
            export_type = payload["export_type"]
            if export_type in saved:
                previous = saved[export_type]["original"]
                raise ValueError(
                    f"Загружено два файла типа «{EXPORT_LABELS[export_type]}»: "
                    f"«{previous}» и «{payload['original']}»."
                )
            if slot != export_type:
                warnings.append(
                    f"«{payload['original']}» определён как «{EXPORT_LABELS[export_type]}» "
                    f"(выбран слот «{EXPORT_LABELS.get(slot, slot)}»)."
                )
            saved[export_type] = payload
            upload_set[export_type] = {
                "original": payload["original"],
                "stored": payload["stored"],
            }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    plan_forecast_meta: dict[str, str] | None = None
    if plan_forecast_file is not None:
        try:
            plan_forecast_meta = _save_plan_forecast_file(settings, plan_forecast_file)
            request.session[SESSION_ALMABI_PLAN_FORECAST] = plan_forecast_meta
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    request.session[SESSION_ALMABI_UPLOAD_SET] = upload_set

    status = _upload_status(upload_set, plan_forecast=plan_forecast_meta or request.session.get(SESSION_ALMABI_PLAN_FORECAST))
    result = {
        "source": "upload",
        "saved_exports": saved,
        "upload_files": status["loaded_exports"],
        "missing_exports": status["missing_required"],
        "is_complete": status["is_complete"],
        "warnings": warnings,
    }
    if plan_forecast_meta:
        result["plan_forecast_file"] = plan_forecast_meta["original"]
    return result


def store_almabi_upload(request: Request, settings: Settings, file: UploadFile) -> dict[str, Any]:
    original_name = Path(file.filename or "").name
    if not original_name:
        raise HTTPException(status_code=400, detail="Имя файла не передано")
    if Path(original_name).suffix.casefold() != ".xlsx":
        raise HTTPException(status_code=400, detail="Поддерживаются только файлы .xlsx")

    upload_dir = settings.resolved_uploads_dir / "almabi"
    upload_dir.mkdir(parents=True, exist_ok=True)
    incoming_dir = upload_dir / ".incoming"
    incoming_dir.mkdir(parents=True, exist_ok=True)
    temp_path = incoming_dir / f"detect-{uuid4().hex}.xlsx"
    try:
        with temp_path.open("wb") as output:
            while chunk := file.file.read(1024 * 1024):
                output.write(chunk)
        if temp_path.stat().st_size == 0:
            raise ValueError("Файл пустой")
        validation = validate_almabi_export(temp_path)
        export_type = validation.export_type
        stored_name = f"{export_type}-{uuid4().hex}.xlsx"
        final_path = upload_dir / stored_name
        temp_path.replace(final_path)
    except ValueError as exc:
        temp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    upload_set = dict(get_almabi_upload_set(request))
    upload_set[export_type] = {"original": original_name, "stored": stored_name}
    request.session[SESSION_ALMABI_UPLOAD_SET] = upload_set
    status = _upload_status(upload_set)
    return {
        "source": "upload",
        "saved_exports": {
            export_type: {
                "original": original_name,
                "stored": stored_name,
                "validation": validation.to_dict(),
            }
        },
        "upload_files": status["loaded_exports"],
        "missing_exports": status["missing_required"],
        "is_complete": status["is_complete"],
    }
