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
    enable_multiple_quasi_identifier_groups: bool = False


@dataclass(frozen=True)
class AnonymizationSettings:
    tokenize_direct_identifiers: bool = True
    remove_direct_identifiers: bool = False
    enable_k_anonymity: bool = False


@dataclass(frozen=True)
class KAnonymizationSettings:
    default_k: int = 5
    max_row_suppression_percent: float = 5.0
    numeric_representative: str = "mean"
    enable_l_diversity: bool = False
    default_l: int = 2
    l_diversity_variant: str = "both"


@dataclass(frozen=True)
class AppSettings:
    data_type_analysis: DataTypeAnalysisSettings = DataTypeAnalysisSettings()
    anonymization: AnonymizationSettings = AnonymizationSettings()
    k_anonymization: KAnonymizationSettings = KAnonymizationSettings()


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
    enable_multiple_qi_groups = analysis.get("enable_multiple_quasi_identifier_groups", False)
    if not isinstance(enable_multiple_qi_groups, bool):
        raise ValueError("Параметр enable_multiple_quasi_identifier_groups должен быть логическим.")
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
    enable_k_anonymity = anonymization.get("enable_k_anonymity", False)
    if not isinstance(enable_k_anonymity, bool):
        raise ValueError("Параметр enable_k_anonymity должен быть логическим.")
    if tokenize_direct_identifiers and remove_direct_identifiers:
        raise ValueError(
            "Токенизация и удаление прямых идентификаторов являются "
            "альтернативными операциями. Включите только одну из них "
            "для суммарной анонимизации."
        )

    k_anonymization = raw.get("k_anonymization", {})
    if not isinstance(k_anonymization, dict):
        raise ValueError("Раздел k_anonymization должен быть JSON-объектом.")
    raw_default_k = k_anonymization.get("default_k", 5)
    if isinstance(raw_default_k, bool) or not isinstance(raw_default_k, int) or raw_default_k < 2:
        raise ValueError("Значение k по умолчанию должно быть целым числом не меньше 2.")
    raw_suppression = k_anonymization.get("max_row_suppression_percent", 5.0)
    if isinstance(raw_suppression, bool):
        raise ValueError("Ограничение подавления строк должно находиться от 0 до 5%.")
    try:
        max_row_suppression = float(raw_suppression)
    except (TypeError, ValueError) as error:
        raise ValueError("Ограничение подавления строк должно находиться от 0 до 5%.") from error
    if not math.isfinite(max_row_suppression) or not 0 <= max_row_suppression <= 5:
        raise ValueError("Ограничение подавления строк должно находиться от 0 до 5%.")
    representative = k_anonymization.get("numeric_representative", "mean")
    if representative not in {"mean", "median", "medoid"}:
        raise ValueError("Способ замены числовых значений должен быть mean, median или medoid.")
    enable_l_diversity = k_anonymization.get("enable_l_diversity", False)
    if not isinstance(enable_l_diversity, bool):
        raise ValueError("Параметр enable_l_diversity должен быть логическим.")
    raw_default_l = k_anonymization.get("default_l", 2)
    if isinstance(raw_default_l, bool) or not isinstance(raw_default_l, int) or raw_default_l < 2:
        raise ValueError("Значение l по умолчанию должно быть целым числом не меньше 2.")
    l_variant = k_anonymization.get("l_diversity_variant", "both")
    if not isinstance(l_variant, str) or l_variant not in {"distinct", "entropy", "both"}:
        raise ValueError("Вариант l-разнообразия должен быть distinct, entropy или both.")

    return AppSettings(
        data_type_analysis=DataTypeAnalysisSettings(
            detect_nominal_attributes=enabled,
            nominal_unique_threshold_percent=threshold,
            enable_multiple_quasi_identifier_groups=enable_multiple_qi_groups,
        ),
        anonymization=AnonymizationSettings(
            tokenize_direct_identifiers=tokenize_direct_identifiers,
            remove_direct_identifiers=remove_direct_identifiers,
            enable_k_anonymity=enable_k_anonymity,
        ),
        k_anonymization=KAnonymizationSettings(
            default_k=raw_default_k,
            max_row_suppression_percent=max_row_suppression,
            numeric_representative=representative,
            enable_l_diversity=enable_l_diversity,
            default_l=raw_default_l,
            l_diversity_variant=l_variant,
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
    if not isinstance(settings.data_type_analysis.enable_multiple_quasi_identifier_groups, bool):
        raise ValueError("Параметр enable_multiple_quasi_identifier_groups должен быть логическим.")
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
    if not isinstance(settings.anonymization.enable_k_anonymity, bool):
        raise ValueError("Параметр enable_k_anonymity должен быть логическим.")
    if (
        settings.anonymization.tokenize_direct_identifiers
        and settings.anonymization.remove_direct_identifiers
    ):
        raise ValueError(
            "Токенизация и удаление прямых идентификаторов являются "
            "альтернативными операциями. Включите только одну из них "
            "для суммарной анонимизации."
        )

    k_settings = settings.k_anonymization
    if isinstance(k_settings.default_k, bool) or not isinstance(k_settings.default_k, int) or k_settings.default_k < 2:
        raise ValueError("Значение k по умолчанию должно быть целым числом не меньше 2.")
    if isinstance(k_settings.max_row_suppression_percent, bool):
        raise ValueError("Ограничение подавления строк должно находиться от 0 до 5%.")
    try:
        max_row_suppression = float(k_settings.max_row_suppression_percent)
    except (TypeError, ValueError) as error:
        raise ValueError("Ограничение подавления строк должно находиться от 0 до 5%.") from error
    if not math.isfinite(max_row_suppression) or not 0 <= max_row_suppression <= 5:
        raise ValueError("Ограничение подавления строк должно находиться от 0 до 5%.")
    if k_settings.numeric_representative not in {"mean", "median", "medoid"}:
        raise ValueError("Способ замены числовых значений должен быть mean, median или medoid.")
    if not isinstance(k_settings.enable_l_diversity, bool):
        raise ValueError("Параметр enable_l_diversity должен быть логическим.")
    if isinstance(k_settings.default_l, bool) or not isinstance(k_settings.default_l, int) or k_settings.default_l < 2:
        raise ValueError("Значение l по умолчанию должно быть целым числом не меньше 2.")
    if not isinstance(k_settings.l_diversity_variant, str) or k_settings.l_diversity_variant not in {"distinct", "entropy", "both"}:
        raise ValueError("Вариант l-разнообразия должен быть distinct, entropy или both.")

    payload = {
        "data_type_analysis": {
            "detect_nominal_attributes": settings.data_type_analysis.detect_nominal_attributes,
            "nominal_unique_threshold_percent": threshold,
            "enable_multiple_quasi_identifier_groups": settings.data_type_analysis.enable_multiple_quasi_identifier_groups,
        },
        "anonymization": {
            "tokenize_direct_identifiers": settings.anonymization.tokenize_direct_identifiers,
            "remove_direct_identifiers": settings.anonymization.remove_direct_identifiers,
            "enable_k_anonymity": settings.anonymization.enable_k_anonymity,
        },
        "k_anonymization": {
            "default_k": k_settings.default_k,
            "max_row_suppression_percent": max_row_suppression,
            "numeric_representative": k_settings.numeric_representative,
            "enable_l_diversity": k_settings.enable_l_diversity,
            "default_l": k_settings.default_l,
            "l_diversity_variant": k_settings.l_diversity_variant,
        },
    }
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = settings_path.with_suffix(settings_path.suffix + ".tmp")
    temporary_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(settings_path)
