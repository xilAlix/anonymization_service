import json
from pathlib import Path
from typing import Any

import pandas as pd

from anonymization.algorithms.k_anonymity import (
    anonymize_k_anonymity,
    evaluate_qi_profiles,
)
from evaluation.privacy.l_diversity import evaluate_l_diversity
from evaluation.privacy.t_closeness import evaluate_t_closeness
from infrastructure.file_safety import atomic_write_text
from infrastructure.attribute_profile_store import (
    DEFAULT_PROFILE_PATH,
    load_manual_role_overrides,
    load_quasi_identifier_correlation_blocks,
    load_quasi_identifier_groups,
    load_quasi_identifier_hierarchies,
    load_semantic_types,
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
        if l_report.get("status") == "not_evaluable":
            reason = l_report.get("reason", "Нет подходящих конфиденциальных атрибутов.")
            lines = [
                "Проверку l-разнообразия невозможно выполнить. CSV-результат не сохранён.",
                reason,
            ]
            excluded = l_report.get("excluded_sensitive_direct_identifiers", [])
            if excluded:
                lines.append(
                    "Исключены как прямые идентификаторы: " + ", ".join(excluded) + "."
                )
            super().__init__("\n".join(lines))
            return

        lines = [
            "l-разнообразие не выполнено. CSV-результат не сохранён (CSV не создан).",
            f"Нарушений: {len(failures)} из {l_report.get('check_count', len(failures))} проверок.",
        ]
        excluded = l_report.get("excluded_sensitive_direct_identifiers", [])
        if excluded:
            lines.append(
                "Не включены в l-проверку как прямые идентификаторы: " + ", ".join(excluded) + "."
            )

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



def _select_l_sensitive_attributes(
    manual_overrides: dict[str, list[str]],
    available_columns: list[str] | pd.Index,
) -> tuple[list[str], list[str]]:
    """Исключает прямые идентификаторы из набора чувствительных атрибутов l-проверки."""
    available = set(map(str, available_columns))
    sensitive: list[str] = []
    excluded_direct: list[str] = []
    for column, roles in manual_overrides.items():
        if column not in available or "sensitive_attribute" not in roles:
            continue
        if "direct_identifier" in roles:
            excluded_direct.append(column)
        else:
            sensitive.append(column)
    return sensitive, excluded_direct


def _not_evaluable_l_report(
    l_value: int,
    variant: str,
    excluded_direct: list[str],
) -> dict[str, Any]:
    if excluded_direct:
        reason = (
            "Нет конфиденциальных атрибутов, доступных для l-проверки: все назначенные "
            "конфиденциальные поля одновременно имеют роль прямого идентификатора и "
            "поэтому исключены. Назначьте роль конфиденциального атрибута другому "
            "столбцу или снимите с него роль прямого идентификатора, если она ошибочна."
        )
    else:
        reason = (
            "Для l-проверки не назначено ни одного конфиденциального атрибута. "
            "Откройте классификацию атрибутов и вручную назначьте эту роль хотя бы одному столбцу."
        )
    return {
        "status": "not_evaluable",
        "reason": reason,
        "l": l_value,
        "variant": variant,
        "sensitive_attributes": [],
        "excluded_sensitive_direct_identifiers": list(excluded_direct),
        "warnings": [reason] if excluded_direct else [],
        "profile_count": 0,
        "check_count": 0,
        "failed_check_count": 0,
        "failed_by_scope": {},
        "failure_examples": [],
        "profiles": [],
        "checks": [],
        "notes": [reason],
    }


class TClosenessViolationError(RuntimeError):
    def __init__(self, report: dict[str, Any]):
        self.report = report
        t_report = report.get("t_closeness", report)
        failures = [item for item in t_report.get("checks", []) if not item.get("satisfied")]
        lines = [
            "t-близость не выполнена. CSV-результат не сохранён.",
            f"Нарушений: {len(failures)} из {t_report.get('check_count', len(failures))} проверок.",
            f"Порог t: {t_report.get('t', 'не задан')}.",
        ]
        if failures:
            first = failures[0]
            lines.append(
                f"Первое нарушение: профиль «{first.get('profile_name')}», "
                f"атрибут «{first.get('sensitive_attribute')}», "
                f"класс {first.get('class_number')}, расстояние={first.get('distance')}, "
                f"метрика={first.get('metric')}."
            )
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
    enable_t_closeness: bool = False,
    default_t: float = 0.4,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    semantic_types = load_semantic_types(source_csv_path, profile_path)
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
        semantic_types=semantic_types,
    )
    if enable_l_diversity:
        overrides = load_manual_role_overrides(source_csv_path, profile_path)
        sensitive_attributes, excluded_direct = _select_l_sensitive_attributes(
            overrides, result.columns
        )
        if not sensitive_attributes:
            l_report = _not_evaluable_l_report(default_l, l_variant, excluded_direct)
            report["l_diversity"] = l_report
            raise LDiversityViolationError({**report, "status": "l_diversity_not_evaluable"})
        l_report = evaluate_l_diversity(
            result,
            profiles,
            sensitive_attributes,
            l_value=default_l,
            variant=l_variant,
        )
        l_report["excluded_sensitive_direct_identifiers"] = excluded_direct
        l_report["warnings"] = (
            [
                "Поля, одновременно назначенные direct_identifier и sensitive_attribute, "
                "исключены из l-проверки: " + ", ".join(excluded_direct) + "."
            ] if excluded_direct else []
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

    if enable_t_closeness:
        overrides = load_manual_role_overrides(source_csv_path, profile_path)
        sensitive_attributes, excluded_direct = _select_l_sensitive_attributes(
            overrides, result.columns
        )
        t_report = evaluate_t_closeness(
            result,
            profiles,
            sensitive_attributes,
            t_value=default_t,
            semantic_types=semantic_types,
        )
        t_report["excluded_sensitive_direct_identifiers"] = excluded_direct
        report["t_closeness"] = t_report
        if t_report["status"] == "failed":
            raise TClosenessViolationError({**report, "status": "t_closeness_failed"})
        if t_report["status"] == "not_evaluable":
            report["notes"].append("t-близость включена, но не может быть рассчитана: " + str(t_report.get("reason")))
        else:
            report["notes"].append(
                f"Проверка t-близости пройдена при t={default_t:g}."
            )
    else:
        report["t_closeness"] = {
            "status": "not_checked",
            "reason": "Проверка t-близости выключена в настройках.",
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
    sensitive_attributes, excluded_direct = _select_l_sensitive_attributes(
        overrides, dataframe.columns
    )
    if not sensitive_attributes:
        return _not_evaluable_l_report(l_value, variant, excluded_direct)
    report = evaluate_l_diversity(
        dataframe, profiles, sensitive_attributes, l_value=l_value, variant=variant
    )
    report["excluded_sensitive_direct_identifiers"] = excluded_direct
    report["warnings"] = (
        [
            "Поля, одновременно назначенные direct_identifier и sensitive_attribute, "
            "исключены из l-проверки: " + ", ".join(excluded_direct) + "."
        ] if excluded_direct else []
    )
    return report


def save_k_anonymity_report(report: dict, output_path: str | Path) -> None:
    atomic_write_text(
        output_path,
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        create_parents=True,
    )
