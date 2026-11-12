import json
from pathlib import Path
from typing import Any

import pandas as pd

from anonymization.algorithms.k_anonymity import (
    anonymize_k_anonymity,
    evaluate_qi_profiles,
)
from evaluation.privacy.l_diversity import evaluate_l_diversity
from infrastructure.attribute_profile_store import (
    DEFAULT_PROFILE_PATH,
    load_manual_role_overrides,
    load_quasi_identifier_correlation_blocks,
    load_quasi_identifier_groups,
    load_quasi_identifier_hierarchies,
)


class LDiversityViolationError(RuntimeError):
    def __init__(self, report: dict[str, Any]):
        self.report = report
        failures = [check for check in report.get("checks", []) if not check.get("satisfied")]
        preview = []
        for item in failures[:8]:
            preview.append(
                f"{item['profile_name']} / {', '.join(item['target_attributes'])} "
                f"/ {item['scope']} / класс {item['class_number']}: "
                f"различных значений {item['distinct_value_count']}, "
                f"H={item['entropy_nats'] if item['entropy_nats'] is not None else 'нет данных'} "
                f"(требуется l={item['l']})"
            )
        details = "\n".join(preview)
        if len(failures) > len(preview):
            details += f"\n... и ещё {len(failures) - len(preview)} нарушений."
        super().__init__(
            "l-разнообразие не выполнено. CSV-результат не сохранён.\n" + details
        )


def execute_k_anonymization(
    dataframe: pd.DataFrame,
    source_csv_path: str | Path,
    default_k: int = 5,
    representative: str = "mean",
    profile_path: str | Path = DEFAULT_PROFILE_PATH,
    enable_l_diversity: bool = False,
    default_l: int = 2,
    l_variant: str = "both",
) -> tuple[pd.DataFrame, dict[str, Any]]:
    profiles = load_quasi_identifier_groups(source_csv_path, profile_path)
    hierarchies = load_quasi_identifier_hierarchies(source_csv_path, profile_path)
    correlation_blocks = load_quasi_identifier_correlation_blocks(source_csv_path, profile_path)
    result, report = anonymize_k_anonymity(
        dataframe,
        profiles,
        default_k=default_k,
        representative=representative,
        hierarchies=hierarchies,
        correlation_blocks=correlation_blocks,
    )
    if enable_l_diversity:
        overrides = load_manual_role_overrides(source_csv_path, profile_path)
        sensitive_attributes = [
            column for column, roles in overrides.items()
            if "sensitive_attribute" in roles and column in result.columns
        ]
        l_report = evaluate_l_diversity(
            result,
            profiles,
            sensitive_attributes,
            l_value=default_l,
            variant=l_variant,
        )
        report["l_diversity"] = l_report
        if l_report["status"] != "satisfied":
            raise LDiversityViolationError({**report, "status": "l_diversity_failed"})
        report["notes"].append(
            "Дополнительно пройдена проверка l-разнообразия по вручную назначенным чувствительным атрибутам."
        )
    else:
        report["l_diversity"] = {
            "status": "not_checked",
            "reason": "Проверка l-разнообразия выключена в настройках.",
        }
    return result, report


def evaluate_current_k(
    dataframe: pd.DataFrame,
    source_csv_path: str | Path,
    default_k: int = 5,
    profile_path: str | Path = DEFAULT_PROFILE_PATH,
) -> list[dict]:
    groups = load_quasi_identifier_groups(source_csv_path, profile_path)
    active = [group for group in groups if group.get("active", group.get("source") != "automatic")]
    if not active:
        raise ValueError("Нет активных QI-профилей для проверки. Сначала подтвердите группы.")
    return evaluate_qi_profiles(dataframe, active, default_k)


def evaluate_current_l(
    dataframe: pd.DataFrame,
    source_csv_path: str | Path,
    l_value: int = 2,
    variant: str = "both",
    profile_path: str | Path = DEFAULT_PROFILE_PATH,
) -> dict[str, Any]:
    profiles = load_quasi_identifier_groups(source_csv_path, profile_path)
    overrides = load_manual_role_overrides(source_csv_path, profile_path)
    sensitive_attributes = [
        column for column, roles in overrides.items()
        if "sensitive_attribute" in roles and column in dataframe.columns
    ]
    return evaluate_l_diversity(
        dataframe, profiles, sensitive_attributes, l_value=l_value, variant=variant
    )


def save_k_anonymity_report(report: dict, output_path: str | Path) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(path)
