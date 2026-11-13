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
        l_report = report.get("l_diversity", report)
        failures = [
            check for check in l_report.get("checks", [])
            if not check.get("satisfied")
        ]
        failed_by_scope = l_report.get("failed_by_scope", {})
        lines = [
            "l-разнообразие не выполнено. CSV-результат не сохранён (CSV не создан).",
            f"Нарушений: {len(failures)} из {l_report.get('check_count', len(failures))} проверок.",
        ]

        conditional = next(
            (
                item for item in failures
                if item.get("scope") == "conditional_on_other_sensitive_attributes"
            ),
            None,
        )
        if conditional is not None:
            target = ", ".join(conditional.get("target_attributes", []))
            context = ", ".join(conditional.get("context_attributes", [])) or "другие чувствительные поля"
            lines.append(
                f"Причина: поле «{target}» проверяется с учётом «{context}». "
                f"В профиле «{conditional.get('profile_name', 'без названия')}» "
                f"получилась группа из {conditional.get('row_count')} строки(строк)."
            )
            lines.append(
                f"В группе найдено разных значений: {conditional.get('distinct_value_count')}; "
                f"энтропия: {conditional.get('entropy_nats')}; "
                f"порог при l={conditional.get('l')}: "
                f"{conditional.get('required_entropy_nats')}."
            )
            lines.append(
                "Такое часто происходит, когда дополнительное числовое поле почти уникально "
                "(например, сумма покупки или доход). Сейчас такие поля сравниваются по точным значениям."
            )
        elif failures:
            item = failures[0]
            lines.append(
                f"Первое нарушение: профиль «{item.get('profile_name', 'без названия')}», "
                f"поле «{', '.join(item.get('target_attributes', []))}», "
                f"класс {item.get('class_number')}, строк в классе: {item.get('row_count')}, "
                f"разных значений: {item.get('distinct_value_count')}, "
                f"H={item.get('entropy_nats')} при пороге {item.get('required_entropy_nats')}."
            )

        if failed_by_scope:
            scope_labels = {
                "individual": "отдельные поля",
                "joint_tuple": "совместные комбинации",
                "conditional_on_other_sensitive_attributes": "учёт остальных чувствительных полей",
            }
            breakdown = ", ".join(
                f"{scope_labels.get(scope, scope)}: {count}"
                for scope, count in failed_by_scope.items()
            )
            lines.append(f"Где возникли нарушения: {breakdown}.")

        lines.append("Подробности сохранены в диагностическом JSON-отчёте.")
        super().__init__("\n".join(lines))


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
