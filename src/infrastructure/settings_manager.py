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
class AppSettings:
    data_type_analysis: DataTypeAnalysisSettings = DataTypeAnalysisSettings()


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
        raise ValueError(
            "Корень файла настроек должен быть JSON-объектом."
        )
    analysis = raw.get("data_type_analysis", {})
    if not isinstance(analysis, dict):
        raise ValueError(
            "Раздел data_type_analysis должен быть JSON-объектом."
        )

    enabled = analysis.get("detect_nominal_attributes", False)
    raw_threshold = analysis.get("nominal_unique_threshold_percent", 10.0)
    if not isinstance(enabled, bool):
        raise ValueError(
            "Параметр detect_nominal_attributes должен быть логическим."
        )
    if isinstance(raw_threshold, bool):
        raise ValueError(
            "Порог уникальных значений должен быть "
            "числом от 0 до 100."
        )

    try:
        threshold = float(raw_threshold)
    except (TypeError, ValueError) as error:
        raise ValueError(
            "Порог уникальных значений должен быть "
            "числом от 0 до 100."
        ) from error

    if not math.isfinite(threshold) or not 0 <= threshold <= 100:
        raise ValueError(
            "Порог уникальных значений должен находиться "
            "в диапазоне от 0 до 100."
        )

    return AppSettings(
        data_type_analysis=DataTypeAnalysisSettings(
            detect_nominal_attributes=enabled,
            nominal_unique_threshold_percent=threshold,
        )
    )

def save_settings(settings: AppSettings, path: str | Path = DEFAULT_SETTINGS_PATH) -> None:
    settings_path = Path(path)
    threshold = settings.data_type_analysis.nominal_unique_threshold_percent
    if not isinstance(settings.data_type_analysis.detect_nominal_attributes, bool):
        raise ValueError(
            "Параметр detect_nominal_attributes должен быть логическим."
        )
    if not math.isfinite(threshold) or not 0 <= threshold <= 100:
        raise ValueError(
            "Порог уникальных значений должен находиться "
            "в диапазоне от 0 до 100."
        )

    payload = {
        "data_type_analysis": {
            "detect_nominal_attributes": settings.data_type_analysis.detect_nominal_attributes,
            "nominal_unique_threshold_percent": threshold,
        }
    }
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = settings_path.with_suffix(settings_path.suffix + ".tmp")
    temporary_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(settings_path)
