from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import date, datetime
from typing import Any, Iterable

import numpy as np
import pandas as pd


SUPPORTED_VARIANTS = {"distinct", "entropy", "both"}


def _is_missing(value: Any) -> bool:
    try:
        result = pd.isna(value)
        return bool(result) if np.isscalar(result) else False
    except (TypeError, ValueError):
        return False


def _scalar_key(value: Any) -> str:
    """Создаёт стабильный ключ значения, не смешивая, например, 1 и '1'."""
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, (pd.Timestamp, datetime, date)):
        normalized = value.isoformat()
    else:
        normalized = repr(value)
    return f"{type(value).__module__}.{type(value).__qualname__}:{normalized}"


def _group_key(values: Iterable[Any]) -> tuple[str, ...]:
    return tuple("<MISSING>" if _is_missing(value) else _scalar_key(value) for value in values)


def _partition_rows(
    dataframe: pd.DataFrame,
    columns: list[str],
) -> list[list[int]]:
    groups: dict[tuple[str, ...], list[int]] = defaultdict(list)
    for row_index, values in enumerate(dataframe[columns].itertuples(index=False, name=None)):
        groups[_group_key(values)].append(row_index)
    return list(groups.values())


def _has_missing_component(value: Any) -> bool:
    if isinstance(value, tuple):
        return any(_is_missing(item) for item in value)
    return _is_missing(value)


def _distribution_metrics(values: list[Any], l_value: int, variant: str) -> dict[str, Any]:
    missing_count = sum(_has_missing_component(value) for value in values)
    observed = [value for value in values if not _has_missing_component(value)]
    frequencies = Counter(_scalar_key(value) for value in observed)
    distinct_count = len(frequencies)
    entropy = None
    if frequencies:
        total = sum(frequencies.values())
        entropy = -sum(
            (count / total) * math.log(count / total)
            for count in frequencies.values()
        )

    distinct_satisfied = missing_count == 0 and distinct_count >= l_value
    required_entropy = math.log(l_value)
    entropy_satisfied = (
        missing_count == 0
        and entropy is not None
        and entropy + 1e-12 >= required_entropy
    )

    if variant == "distinct":
        satisfied = distinct_satisfied
    elif variant == "entropy":
        satisfied = entropy_satisfied
    else:
        satisfied = distinct_satisfied and entropy_satisfied

    return {
        "row_count": len(values),
        "observed_value_count": len(observed),
        "missing_value_count": missing_count,
        "distinct_value_count": distinct_count,
        "entropy_nats": None if entropy is None else float(entropy),
        "required_entropy_nats": float(required_entropy),
        "distinct_satisfied": bool(distinct_satisfied),
        "entropy_satisfied": bool(entropy_satisfied),
        "satisfied": bool(satisfied),
    }


def _check_partition(
    dataframe: pd.DataFrame,
    partitions: list[list[int]],
    target_columns: list[str],
    l_value: int,
    variant: str,
    scope: str,
    profile: dict[str, Any],
    check_offset: int,
    invalid_context_columns: list[str] | None = None,
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for local_index, row_indices in enumerate(partitions, start=1):
        if len(target_columns) == 1:
            values = dataframe.iloc[row_indices][target_columns[0]].tolist()
        else:
            rows = dataframe.iloc[row_indices][target_columns]
            values = [tuple(row) for row in rows.itertuples(index=False, name=None)]
        metrics = _distribution_metrics(values, l_value, variant)
        missing_context_count = 0
        if invalid_context_columns:
            missing_context_count = sum(
                any(_is_missing(value) for value in row)
                for row in dataframe.iloc[row_indices][invalid_context_columns].itertuples(index=False, name=None)
            )
            if missing_context_count:
                metrics["satisfied"] = False
        checks.append({
            "check_id": check_offset + local_index,
            "profile_id": profile["id"],
            "profile_name": profile["name"],
            "scope": scope,
            "target_attributes": target_columns,
            "class_number": local_index,
            "l": l_value,
            "variant": variant,
            "missing_context_count": missing_context_count,
            **metrics,
        })
    return checks


def evaluate_l_diversity(
    dataframe: pd.DataFrame,
    profiles: list[dict[str, Any]],
    sensitive_attributes: list[str],
    l_value: int = 2,
    variant: str = "both",
) -> dict[str, Any]:
    """Проверяет l-разнообразие в каждом активном QI-профиле.

    Для нескольких чувствительных атрибутов выполняются индивидуальные проверки,
    проверка составного значения и условные проверки: остальные чувствительные
    атрибуты добавляются к QI-ключу при проверке целевого атрибута.
    """
    if isinstance(l_value, bool) or not isinstance(l_value, int) or l_value < 2:
        raise ValueError("Значение l должно быть целым числом не меньше 2.")
    if not isinstance(variant, str) or variant not in SUPPORTED_VARIANTS:
        raise ValueError("Вариант l-разнообразия должен быть distinct, entropy или both.")
    if dataframe.empty:
        raise ValueError("Нельзя проверить l-разнообразие пустой таблицы.")
    if not sensitive_attributes:
        raise ValueError(
            "Для l-разнообразия не назначены чувствительные атрибуты. "
            "Откройте классификацию атрибутов и вручную назначьте роль "
            "«Конфиденциальный атрибут» хотя бы одному столбцу."
        )
    if len(sensitive_attributes) != len(set(sensitive_attributes)):
        raise ValueError("Список чувствительных атрибутов содержит повторы.")
    missing_sensitive = [column for column in sensitive_attributes if column not in dataframe.columns]
    if missing_sensitive:
        raise ValueError(
            "В таблице отсутствуют чувствительные атрибуты: " + ", ".join(missing_sensitive)
        )

    active_profiles = [profile for profile in profiles if profile.get("active", False)]
    if not active_profiles:
        raise ValueError("Нет активных QI-профилей для проверки l-разнообразия.")

    all_checks: list[dict[str, Any]] = []
    profile_summaries: list[dict[str, Any]] = []
    for profile in active_profiles:
        qi_columns = list(profile.get("attributes", []))
        if not qi_columns:
            raise ValueError(f"QI-профиль «{profile.get('name', profile.get('id'))}» пуст.")
        missing_qi = [column for column in qi_columns if column not in dataframe.columns]
        if missing_qi:
            raise ValueError(
                f"В QI-профиле «{profile.get('name', profile.get('id'))}» "
                f"отсутствуют столбцы: {', '.join(missing_qi)}"
            )
        overlap = sorted(set(qi_columns) & set(sensitive_attributes))
        if overlap:
            raise ValueError(
                f"Чувствительные атрибуты не должны входить в QI-профиль "
                f"«{profile.get('name', profile.get('id'))}»: {', '.join(overlap)}. "
                "Пересмотрите вручную назначенные роли или состав QI-профиля."
            )

        profile_checks: list[dict[str, Any]] = []
        base_partitions = _partition_rows(dataframe, qi_columns)
        for sensitive_column in sensitive_attributes:
            profile_checks.extend(_check_partition(
                dataframe,
                base_partitions,
                [sensitive_column],
                l_value,
                variant,
                "individual",
                profile,
                len(all_checks) + len(profile_checks),
            ))

        if len(sensitive_attributes) > 1:
            profile_checks.extend(_check_partition(
                dataframe,
                base_partitions,
                list(sensitive_attributes),
                l_value,
                variant,
                "joint_tuple",
                profile,
                len(all_checks) + len(profile_checks),
            ))

            # Для каждого S_i остальные чувствительные признаки становятся
            # дополнительной фоновой информацией, как в multi-attribute ℓ-diversity.
            for target in sensitive_attributes:
                other_sensitive = [column for column in sensitive_attributes if column != target]
                conditional_columns = list(dict.fromkeys(qi_columns + other_sensitive))
                conditional_partitions = _partition_rows(dataframe, conditional_columns)
                profile_checks.extend(_check_partition(
                    dataframe,
                    conditional_partitions,
                    [target],
                    l_value,
                    variant,
                    "conditional_on_other_sensitive_attributes",
                    profile,
                    len(all_checks) + len(profile_checks),
                    invalid_context_columns=other_sensitive,
                ))

        all_checks.extend(profile_checks)
        failed = [check for check in profile_checks if not check["satisfied"]]
        profile_summaries.append({
            "profile_id": profile["id"],
            "profile_name": profile["name"],
            "qi_attributes": qi_columns,
            "equivalence_class_count": len(base_partitions),
            "check_count": len(profile_checks),
            "failed_check_count": len(failed),
            "satisfied": not failed,
        })

    failures = [check for check in all_checks if not check["satisfied"]]
    numeric_sensitive = [
        column for column in sensitive_attributes
        if pd.api.types.is_numeric_dtype(dataframe[column].dtype)
        and not pd.api.types.is_bool_dtype(dataframe[column].dtype)
    ]
    notes = [
        "Проверка выполнена по итоговым значениям QI-атрибутов после k-анонимизации.",
        "Пропущенные чувствительные значения не считаются отдельным разнообразным значением; наличие пропусков в проверяемом значении приводит к провалу соответствующей проверки.",
        "joint_tuple показывает разнообразие совместных комбинаций, а conditional_on_other_sensitive_attributes проверяет каждый чувствительный атрибут с учётом комбинаций остальных чувствительных атрибутов.",
        "Entropy использует натуральный логарифм: H(S) = -Σ p_i ln(p_i), порог ln(l).",
    ]
    if numeric_sensitive:
        notes.append(
            "Числовые чувствительные атрибуты проверяются по точным значениям. "
            "При высокой кардинальности это может завышать формальное разнообразие; "
            "семантические интервалы/категории для них пока не реализованы: "
            + ", ".join(numeric_sensitive)
        )

    return {
        "status": "satisfied" if not failures else "failed",
        "l": l_value,
        "variant": variant,
        "sensitive_attributes": list(sensitive_attributes),
        "profile_count": len(profile_summaries),
        "check_count": len(all_checks),
        "failed_check_count": len(failures),
        "profiles": profile_summaries,
        "checks": all_checks,
        "notes": notes,
    }
