from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from data_loader import load_calculation_services_dataset


@dataclass(frozen=True)
class ValidationResult:
    service_count: int
    class_count: int

    def to_dict(self) -> dict:
        return {
            "service_count": self.service_count,
            "class_count": self.class_count,
        }


def validate_excel_file(path: Path) -> ValidationResult:
    if path.suffix.casefold() != ".xlsx":
        raise ValueError("Поддерживаются только файлы .xlsx")

    try:
        dataset = load_calculation_services_dataset(path)
    except Exception as exc:
        raise ValueError(f"Файл не прошёл проверку структуры: {exc}") from exc

    services = dataset.get("services", [])
    classes = {service.get("class_name") for service in services if service.get("class_name")}
    if not services:
        raise ValueError("В файле не найдены услуги на листе 'Калькуляция'")
    if not classes:
        raise ValueError("В файле не найдены классы услуг")

    required_detail_groups = (
        "direct_detail_labels",
        "indirect_detail_labels",
        "inefficiency_detail_labels",
    )
    missing_groups = [name for name in required_detail_groups if not dataset.get(name)]
    if missing_groups:
        raise ValueError(f"Не найдены ожидаемые группы стоимостных колонок: {', '.join(missing_groups)}")

    return ValidationResult(service_count=len(services), class_count=len(classes))
