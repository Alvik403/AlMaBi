from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import HTTPException, Request, UploadFile

from almabi_excel_loader import load_almabi_dashboard_from_excel
from almabi_file_validation import validate_almabi_excel
from almabi_mock_data import get_almabi_dashboard_data
from almabi_template_data import get_almabi_template_dashboard_data
from settings import BASE_DIR, Settings


SESSION_ALMABI_DATA_SOURCE = "almabi_data_source"
SESSION_ALMABI_UPLOAD_ORIGINAL = "almabi_upload_original_name"
SESSION_ALMABI_UPLOAD_STORED = "almabi_upload_stored_name"

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
        "title": "Мой файл",
        "description": "Загруженный .xlsx по структуре БДР или реализаций.",
    },
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


def get_almabi_upload_path(request: Request, settings: Settings) -> Path | None:
    stored_name = request.session.get(SESSION_ALMABI_UPLOAD_STORED)
    if not stored_name:
        return None
    path = settings.resolved_uploads_dir / "almabi" / stored_name
    return path if path.exists() else None


def almabi_data_context(request: Request, settings: Settings) -> dict[str, Any]:
    source = get_almabi_data_source(request)
    meta = ALMABI_SOURCES[source]
    upload_name = request.session.get(SESSION_ALMABI_UPLOAD_ORIGINAL)
    upload_path = get_almabi_upload_path(request, settings)
    return {
        "source": source,
        "title": meta["title"],
        "description": meta["description"],
        "sources": list(ALMABI_SOURCES.values()),
        "upload_file_name": upload_name,
        "has_upload_file": bool(upload_path),
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

    upload_path = get_almabi_upload_path(request, settings)
    upload_name = request.session.get(SESSION_ALMABI_UPLOAD_ORIGINAL, "upload.xlsx")
    if not upload_path:
        data = get_almabi_template_dashboard_data()
        data["meta"] = {
            **data.get("meta", {}),
            "source": "upload",
            "title": ALMABI_SOURCES["upload"]["title"],
            "upload_file_name": None,
            "parsed": False,
            "message": "Загрузите .xlsx файл, чтобы использовать свой источник данных.",
        }
        return data

    return load_almabi_dashboard_from_excel(upload_path, original_name=upload_name)


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

    stored_name = f"{uuid4().hex}.xlsx"
    temp_path = incoming_dir / stored_name
    final_path = upload_dir / stored_name

    try:
        with temp_path.open("wb") as output:
            while chunk := file.file.read(1024 * 1024):
                output.write(chunk)
        validation = validate_almabi_excel(temp_path)
        temp_path.replace(final_path)
        request.session[SESSION_ALMABI_DATA_SOURCE] = "upload"
        request.session[SESSION_ALMABI_UPLOAD_ORIGINAL] = original_name
        request.session[SESSION_ALMABI_UPLOAD_STORED] = stored_name
        return {
            "source": "upload",
            "upload_file_name": original_name,
            "validation": validation.to_dict(),
        }
    except ValueError as exc:
        temp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
