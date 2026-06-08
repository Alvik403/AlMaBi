from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import HTTPException, Request, UploadFile

from almabi_dashboard_builder import load_almabi_dashboard_from_exports
from almabi_file_validation import (
    EXPORT_TYPES,
    REQUIRED_EXPORT_TYPES,
    EXPORT_LABELS,
    guess_export_type_from_filename,
    validate_almabi_export,
)
from almabi_mock_data import get_almabi_dashboard_data
from almabi_template_data import get_almabi_template_dashboard_data
from settings import BASE_DIR, Settings


SESSION_ALMABI_DATA_SOURCE = "almabi_data_source"
SESSION_ALMABI_UPLOAD_SET = "almabi_upload_set"

ALMABI_SOURCES = {
    "mock": {
        "key": "mock",
        "title": "Демо-данные",
        "description": "Текущий набор тестовых показателей AlMaBi.",
    },
    "template": {
        "key": "template",
        "title": "Шаблон БДР",
        "description": "Заполненный тестовый шаблон «Универсальный отчёт для БДР».",
    },
    "upload": {
        "key": "upload",
        "title": "Мои выгрузки",
        "description": "Четыре .xlsx выгрузки 1С: бухрегистр, реализация, себестоимость, амортизация.",
    },
}

_EXPORT_FIELD_NAMES = {
    "buh": "buh_file",
    "realization": "realization_file",
    "cost": "cost_file",
    "amortization": "amortization_file",
}


def get_almabi_data_source(request: Request) -> str:
    source = request.session.get(SESSION_ALMABI_DATA_SOURCE, "mock")
    if source not in ALMABI_SOURCES:
        return "mock"
    return source


def set_almabi_data_source(request: Request, source: str) -> None:
    if source not in ALMABI_SOURCES:
        raise HTTPException(status_code=400, detail=f"Неизвестный источник данных: {source}")
    request.session[SESSION_ALMABI_DATA_SOURCE] = source


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


def _upload_status(upload_set: dict[str, dict[str, str]]) -> dict[str, Any]:
    loaded = {export_type: upload_set[export_type].get("original") for export_type in EXPORT_TYPES if export_type in upload_set}
    missing_required = [export_type for export_type in REQUIRED_EXPORT_TYPES if export_type not in loaded]
    return {
        "loaded_exports": loaded,
        "missing_required": missing_required,
        "is_complete": not missing_required,
    }


def almabi_data_context(request: Request, settings: Settings) -> dict[str, Any]:
    source = get_almabi_data_source(request)
    meta = ALMABI_SOURCES[source]
    upload_set = get_almabi_upload_set(request)
    upload_status = _upload_status(upload_set)
    return {
        "source": source,
        "title": meta["title"],
        "description": meta["description"],
        "sources": list(ALMABI_SOURCES.values()),
        "upload_file_name": None,
        "upload_files": upload_status["loaded_exports"],
        "missing_exports": upload_status["missing_required"],
        "has_upload_file": upload_status["is_complete"],
        "fixtures": {
            "bdr_template": str(BASE_DIR / "fixtures" / "bdr_template_empty.xlsx"),
            "field_mapping": str(BASE_DIR / "fixtures" / "bi_field_names.xlsx"),
        },
    }


def resolve_almabi_dashboard_data(request: Request, settings: Settings) -> dict[str, Any]:
    source = get_almabi_data_source(request)
    if source == "mock":
        data = get_almabi_dashboard_data()
        data["meta"] = {
            "source": "mock",
            "title": ALMABI_SOURCES["mock"]["title"],
            "description": ALMABI_SOURCES["mock"]["description"],
        }
        return data

    if source == "template":
        return get_almabi_template_dashboard_data()

    upload_paths = get_almabi_upload_paths(request, settings)
    upload_set = get_almabi_upload_set(request)
    upload_names = {
        export_type: meta.get("original", f"{export_type}.xlsx")
        for export_type, meta in upload_set.items()
    }
    missing_required = [export_type for export_type in REQUIRED_EXPORT_TYPES if export_type not in upload_paths]
    if missing_required:
        data = get_almabi_template_dashboard_data()
        data["meta"] = {
            **data.get("meta", {}),
            "source": "upload",
            "title": ALMABI_SOURCES["upload"]["title"],
            "upload_files": upload_names,
            "parsed": False,
            "missing_exports": missing_required,
            "message": "Загрузите обязательные выгрузки: бухрегистр, реализация и себестоимость.",
        }
        return data

    return load_almabi_dashboard_from_exports(upload_paths, upload_names=upload_names)


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


def store_almabi_upload_bundle(request: Request, settings: Settings, files: dict[str, UploadFile | None]) -> dict[str, Any]:
    incoming = [(slot, file) for slot, file in files.items() if file is not None]
    if not incoming:
        raise HTTPException(status_code=400, detail="Передайте хотя бы один файл выгрузки")

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

    request.session[SESSION_ALMABI_DATA_SOURCE] = "upload"
    request.session[SESSION_ALMABI_UPLOAD_SET] = upload_set

    status = _upload_status(upload_set)
    return {
        "source": "upload",
        "saved_exports": saved,
        "upload_files": status["loaded_exports"],
        "missing_exports": status["missing_required"],
        "is_complete": status["is_complete"],
        "warnings": warnings,
    }


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
    request.session[SESSION_ALMABI_DATA_SOURCE] = "upload"
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
