import json
import math
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SETTINGS_PATH = PROJECT_ROOT / "config" / "settings.json"


@dataclass(frozen=True)
class DataTypeAnalysisSettings:
    detect_nominal_attributes: bool = False
    nominal_unique_threshold_percent: float = 10.0


@dataclass(frozen=True)
class AnonymizationSettings:
    tokenize_direct_identifiers: bool = True
    remove_direct_identifiers: bool = False


@dataclass(frozen=True)
class AppSettings:
    data_type_analysis: DataTypeAnalysisSettings = DataTypeAnalysisSettings()
    anonymization: AnonymizationSettings = AnonymizationSettings()


def load_settings(path: str | Path = DEFAULT_SETTINGS_PATH) -> AppSettings:
    settings_path = Path(path)
    if not settings_path.exists():
        return AppSettings()

    try:
        raw = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(
            f"Не удалось прочитать настройки {settings_path}: {error}"
        ) from error

    if not isinstance(raw, dict):
        raise ValueError("Корень файла настроек должен быть JSON-объектом.")

    analysis = raw.get("data_type_analysis", {})
    if not isinstance(analysis, dict):
        raise ValueError("Раздел data_type_analysis должен быть JSON-объектом.")

    enabled = analysis.get("detect_nominal_attributes", False)
    raw_threshold = analysis.get("nominal_unique_threshold_percent", 10.0)
    if not isinstance(enabled, bool):
        raise ValueError(
            "Параметр detect_nominal_attributes должен быть логическим."
        )
    if isinstance(raw_threshold, bool):
        raise ValueError("Порог уникальных значений должен быть числом от 0 до 100.")

    try:
        threshold = float(raw_threshold)
    except (TypeError, ValueError) as error:
        raise ValueError(
            "Порог уникальных значений должен быть числом от 0 до 100."
        ) from error

    if not math.isfinite(threshold) or not 0 <= threshold <= 100:
        raise ValueError(
            "Порог уникальных значений должен находиться в диапазоне от 0 до 100."
        )

    anonymization = raw.get("anonymization", {})
    if not isinstance(anonymization, dict):
        raise ValueError("Раздел anonymization должен быть JSON-объектом.")

    tokenize_direct_identifiers = anonymization.get(
        "tokenize_direct_identifiers",
        True,
    )
    if not isinstance(tokenize_direct_identifiers, bool):
        raise ValueError(
            "Параметр tokenize_direct_identifiers должен быть логическим."
        )
    remove_direct_identifiers = anonymization.get(
        "remove_direct_identifiers",
        False,
    )
    if not isinstance(remove_direct_identifiers, bool):
        raise ValueError(
            "Параметр remove_direct_identifiers должен быть логическим."
        )
    if tokenize_direct_identifiers and remove_direct_identifiers:
        raise ValueError(
            "Токенизация и удаление прямых идентификаторов являются "
            "альтернативными операциями. Включите только одну из них "
            "для суммарной анонимизации."
        )

    return AppSettings(
        data_type_analysis=DataTypeAnalysisSettings(
            detect_nominal_attributes=enabled,
            nominal_unique_threshold_percent=threshold,
        ),
        anonymization=AnonymizationSettings(
            tokenize_direct_identifiers=tokenize_direct_identifiers,
            remove_direct_identifiers=remove_direct_identifiers,
        ),
    )


def save_settings(
    settings: AppSettings,
    path: str | Path = DEFAULT_SETTINGS_PATH,
) -> None:
    settings_path = Path(path)
    threshold = settings.data_type_analysis.nominal_unique_threshold_percent
    if not isinstance(settings.data_type_analysis.detect_nominal_attributes, bool):
        raise ValueError(
            "Параметр detect_nominal_attributes должен быть логическим."
        )
    if isinstance(threshold, bool):
        raise ValueError("Порог уникальных значений должен быть числом от 0 до 100.")
    try:
        threshold = float(threshold)
    except (TypeError, ValueError) as error:
        raise ValueError(
            "Порог уникальных значений должен быть числом от 0 до 100."
        ) from error
    if not math.isfinite(threshold) or not 0 <= threshold <= 100:
        raise ValueError(
            "Порог уникальных значений должен находиться в диапазоне от 0 до 100."
        )
    if not isinstance(settings.anonymization.tokenize_direct_identifiers, bool):
        raise ValueError(
            "Параметр tokenize_direct_identifiers должен быть логическим."
        )
    if not isinstance(settings.anonymization.remove_direct_identifiers, bool):
        raise ValueError(
            "Параметр remove_direct_identifiers должен быть логическим."
        )
    if (
        settings.anonymization.tokenize_direct_identifiers
        and settings.anonymization.remove_direct_identifiers
    ):
        raise ValueError(
            "Токенизация и удаление прямых идентификаторов являются "
            "альтернативными операциями. Включите только одну из них "
            "для суммарной анонимизации."
        )

    payload = {
        "data_type_analysis": {
            "detect_nominal_attributes": settings.data_type_analysis.detect_nominal_attributes,
            "nominal_unique_threshold_percent": threshold,
        },
        "anonymization": {
            "tokenize_direct_identifiers": settings.anonymization.tokenize_direct_identifiers,
            "remove_direct_identifiers": settings.anonymization.remove_direct_identifiers,
        },
    }
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = settings_path.with_suffix(settings_path.suffix + ".tmp")
    temporary_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(settings_path)
