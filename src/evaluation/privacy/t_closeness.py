from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime
from typing import Any, Iterable

import numpy as np
import pandas as pd
from pandas.api.types import is_bool_dtype, is_datetime64_any_dtype, is_numeric_dtype


def _is_missing(value: Any) -> bool:
    try:
        result = pd.isna(value)
        return bool(result) if np.isscalar(result) else False
    except (TypeError, ValueError):
        return False


def _stable_value(value: Any) -> str:
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, (pd.Timestamp, datetime, date)):
        value = value.isoformat()
    return f"{type(value).__module__}.{type(value).__qualname__}:{value!r}"


def _partition(dataframe: pd.DataFrame, columns: list[str]) -> list[list[int]]:
    grouped: dict[tuple[str, ...], list[int]] = defaultdict(list)
    for index, row in enumerate(dataframe[columns].itertuples(index=False, name=None)):
        grouped[tuple("<MISSING>" if _is_missing(value) else _stable_value(value) for value in row)].append(index)
    return list(grouped.values())


def _normalized_emd(global_values: np.ndarray, group_values: np.ndarray) -> float:
    """Рассчитывает нормализованную EMD эмпирических одномерных распределений."""
    if global_values.size == 0 or group_values.size == 0:
        return 1.0 if global_values.size != group_values.size else 0.0
    support = np.unique(np.concatenate([global_values, group_values]))
    if support.size <= 1:
        return 0.0
    global_cdf = np.searchsorted(np.sort(global_values), support[:-1], side="right") / global_values.size
    group_cdf = np.searchsorted(np.sort(group_values), support[:-1], side="right") / group_values.size
    span = float(support[-1] - support[0])
    if span <= 0:
        return 0.0
    distance = float(np.sum(np.abs(global_cdf - group_cdf) * np.diff(support)) / span)
    return float(min(1.0, max(0.0, distance)))


def _total_variation(global_values: list[Any], group_values: list[Any]) -> float:
    """Total variation distance for nominal attributes, including missing as a category."""
    global_counts = Counter("<MISSING>" if _is_missing(value) else _stable_value(value) for value in global_values)
    group_counts = Counter("<MISSING>" if _is_missing(value) else _stable_value(value) for value in group_values)
    global_n = sum(global_counts.values())
    group_n = sum(group_counts.values())
    if not global_n or not group_n:
        return 1.0 if global_n != group_n else 0.0
    support = set(global_counts) | set(group_counts)
    return float(0.5 * sum(abs(global_counts[key] / global_n - group_counts[key] / group_n) for key in support))


def _distance(global_series: pd.Series, group_series: pd.Series, kind: str) -> tuple[float, str, dict[str, float]]:
    if kind == "numeric":
        global_numeric = pd.to_numeric(global_series, errors="coerce")
        group_numeric = pd.to_numeric(group_series, errors="coerce")
        global_missing = float(global_numeric.isna().mean())
        group_missing = float(group_numeric.isna().mean())
        global_observed = global_numeric.dropna().to_numpy(dtype=float)
        group_observed = group_numeric.dropna().to_numpy(dtype=float)
        observed_distance = _normalized_emd(global_observed, group_observed)
        # Missingness is part of the distribution and must not silently disappear.
        missing_distance = abs(global_missing - group_missing)
        observed_weight = 1.0 - max(global_missing, group_missing)
        distance = min(1.0, missing_distance + observed_weight * observed_distance)
        return distance, "normalized_emd_with_missingness", {
            "global_missing_rate": global_missing,
            "group_missing_rate": group_missing,
            "observed_emd": observed_distance,
        }

    distance = _total_variation(global_series.tolist(), group_series.tolist())
    return distance, "total_variation", {}


def evaluate_t_closeness(
    dataframe: pd.DataFrame,
    profiles: list[dict[str, Any]],
    sensitive_attributes: list[str],
    t_value: float = 0.2,
    semantic_types: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Проверяет t-близость для каждого активного QI-класса и чувствительного поля.

    Для числовых/временных полей используется нормализованная EMD, для
    номинальных категорий — расстояние полной вариации.
    """
    if isinstance(t_value, bool) or not isinstance(t_value, (int, float)) or not np.isfinite(t_value) or not 0 <= float(t_value) <= 1:
        raise ValueError("Порог t должен быть числом от 0 до 1.")
    if dataframe.empty:
        raise ValueError("Нельзя проверить t-близость пустой таблицы.")
    if not sensitive_attributes:
        return {
            "status": "not_evaluable",
            "reason": "Не назначены конфиденциальные атрибуты для проверки t-близости.",
            "t": float(t_value),
            "metric_policy": "numeric/date: normalized EMD; nominal categorical: total variation",
            "profiles": [],
            "checks": [],
            "check_count": 0,
            "failed_check_count": 0,
        }

    semantic_types = semantic_types or {}
    active_profiles = [item for item in profiles if item.get("active", item.get("source") != "automatic")]
    if not active_profiles:
        raise ValueError("Нет активных QI-профилей для проверки t-близости.")

    checks: list[dict[str, Any]] = []
    profile_summaries: list[dict[str, Any]] = []
    for profile in active_profiles:
        qi_columns = list(profile.get("attributes", []))
        if not qi_columns:
            raise ValueError(f"QI-профиль «{profile.get('name', profile.get('id'))}» пуст.")
        missing_qi = [column for column in qi_columns if column not in dataframe.columns]
        if missing_qi:
            raise ValueError("В QI-профиле отсутствуют столбцы: " + ", ".join(missing_qi))
        partitions = _partition(dataframe, qi_columns)
        start = len(checks)
        profile_failed = 0
        for sensitive in sensitive_attributes:
            if sensitive not in dataframe.columns:
                raise ValueError(f"Конфиденциальный атрибут «{sensitive}» отсутствует в таблице.")
            series = dataframe[sensitive]
            declared_type = semantic_types.get(sensitive, "auto")
            numeric_kind = declared_type in {"numeric", "datetime"} or (
                declared_type == "auto" and (is_numeric_dtype(series.dtype) or is_datetime64_any_dtype(series.dtype))
            )
            if declared_type == "categorical" or is_bool_dtype(series.dtype):
                numeric_kind = False
            kind = "numeric" if numeric_kind else "nominal"
            if numeric_kind and declared_type == "datetime":
                parsed_dates = pd.to_datetime(series, errors="coerce")
                series = parsed_dates.astype("int64", copy=False).where(parsed_dates.notna(), np.nan)
            global_values = series
            global_observed_count = int(global_values.notna().sum())
            for class_number, row_indices in enumerate(partitions, start=1):
                group_values = series.iloc[row_indices]
                if global_observed_count == 0:
                    checks.append({
                        "check_id": len(checks) + 1,
                        "profile_id": profile.get("id"),
                        "profile_name": str(profile.get("name", profile.get("id", "QI-профиль"))),
                        "profile_attributes": qi_columns,
                        "sensitive_attribute": str(sensitive),
                        "class_number": class_number,
                        "class_size": len(row_indices),
                        "metric": "not_evaluable",
                        "distance": None,
                        "t": float(t_value),
                        "satisfied": None,
                        "evaluated": False,
                        "reason": "Конфиденциальный атрибут полностью состоит из пропусков.",
                    })
                    continue
                if numeric_kind:
                    distance, metric, extra = _distance(global_values, group_values, "numeric")
                else:
                    distance, metric, extra = _distance(global_values, group_values, "nominal")
                satisfied = distance <= float(t_value) + 1e-12
                if not satisfied:
                    profile_failed += 1
                checks.append({
                    "check_id": len(checks) + 1,
                    "profile_id": profile.get("id"),
                    "profile_name": str(profile.get("name", profile.get("id", "QI-профиль"))),
                    "profile_attributes": qi_columns,
                    "sensitive_attribute": str(sensitive),
                    "class_number": class_number,
                    "class_size": len(row_indices),
                    "metric": metric,
                    "distance": float(distance),
                    "t": float(t_value),
                    "satisfied": bool(satisfied),
                    "evaluated": True,
                    **extra,
                })
        profile_checks = checks[start:]
        not_evaluable_count = sum(not item.get("evaluated", True) for item in profile_checks)
        profile_summaries.append({
            "profile_id": profile.get("id"),
            "profile_name": str(profile.get("name", profile.get("id", "QI-профиль"))),
            "qi_attributes": qi_columns,
            "equivalence_class_count": len(partitions),
            "check_count": len(profile_checks),
            "failed_check_count": profile_failed,
            "not_evaluable_check_count": not_evaluable_count,
            "maximum_distance": max((item["distance"] for item in profile_checks if item.get("distance") is not None), default=None),
            "satisfied": profile_failed == 0 and not_evaluable_count == 0,
        })

    failures = [item for item in checks if item.get("satisfied") is False]
    not_evaluable = [item for item in checks if not item.get("evaluated", True)]
    overall_status = "failed" if failures else ("not_evaluable" if not checks or not_evaluable else "satisfied")
    return {
        "status": overall_status,
        "t": float(t_value),
        "metric_policy": "numeric/date: normalized EMD; nominal categorical: total variation",
        "profile_count": len(profile_summaries),
        "check_count": len(checks),
        "failed_check_count": len(failures),
        "not_evaluable_check_count": len(not_evaluable),
        "maximum_distance": max((item["distance"] for item in checks if item.get("distance") is not None), default=None),
        "profiles": profile_summaries,
        "checks": checks,
        "notes": [
            "Для числовых и временных атрибутов применена нормализованная одномерная EMD.",
            "Для номинальных категориальных атрибутов без естественного порядка применено расстояние полной вариации (TVD).",
            "Порог t является настраиваемым экспериментальным параметром; успешная проверка не гарантирует абсолютную анонимность.",
        ],
    }
