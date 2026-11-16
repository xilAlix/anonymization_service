from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from pandas.api.types import is_bool_dtype, is_numeric_dtype


@dataclass
class UtilityEvaluation:
    attributes: pd.DataFrame
    correlations: pd.DataFrame
    summary: dict[str, Any]
    excluded_columns: list[str]
    removed_columns: list[str]
    added_columns: list[str]


def _numeric_series(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan)


def _is_numeric_pair(before: pd.Series, after: pd.Series) -> bool:
    return (
        is_numeric_dtype(before.dtype)
        and is_numeric_dtype(after.dtype)
        and not is_bool_dtype(before.dtype)
        and not is_bool_dtype(after.dtype)
    )


def _missing_percent(series: pd.Series) -> float:
    return float(series.isna().mean() * 100.0) if len(series) else 0.0


def _distribution_tvd(before: pd.Series, after: pd.Series) -> float:
    before_values = before.astype("string").fillna("<ПРОПУСК>").value_counts(normalize=True)
    after_values = after.astype("string").fillna("<ПРОПУСК>").value_counts(normalize=True)
    categories = set(before_values.index) | set(after_values.index)
    return float(
        0.5 * sum(
            abs(float(before_values.get(item, 0.0)) - float(after_values.get(item, 0.0)))
            for item in categories
        )
    )


def _relative_change(before: float | None, after: float | None) -> float | None:
    if before is None or after is None or abs(before) < 1e-15:
        return None
    return float((after - before) / abs(before) * 100.0)


def _numeric_metrics(series: pd.Series) -> dict[str, float | int | None]:
    values = _numeric_series(series).dropna()
    if values.empty:
        return {
            "mean": None,
            "variance": None,
            "median": None,
            "q1": None,
            "q3": None,
            "iqr": None,
        }
    q1 = float(values.quantile(0.25, interpolation="linear"))
    q3 = float(values.quantile(0.75, interpolation="linear"))
    return {
        "mean": float(values.mean()),
        "variance": float(values.var(ddof=1)) if len(values) >= 2 else None,
        "median": float(values.median()),
        "q1": q1,
        "q3": q3,
        "iqr": q3 - q1,
    }


def _pair_correlation(
    first_before: pd.Series,
    second_before: pd.Series,
    first_after: pd.Series,
    second_after: pd.Series,
    method: str,
) -> tuple[float | None, int, float | None, int]:
    before_frame = pd.DataFrame({"x": _numeric_series(first_before), "y": _numeric_series(second_before)}).dropna()
    after_frame = pd.DataFrame({"x": _numeric_series(first_after), "y": _numeric_series(second_after)}).dropna()

    def calculate(frame: pd.DataFrame) -> float | None:
        if len(frame) < 3 or frame["x"].nunique() < 2 or frame["y"].nunique() < 2:
            return None
        if method == "spearman":
            return float(frame["x"].corr(frame["y"], method="spearman"))
        return float(frame["x"].corr(frame["y"], method="pearson"))

    return (
        calculate(before_frame),
        len(before_frame),
        calculate(after_frame),
        len(after_frame),
    )


def evaluate_utility(
    original: pd.DataFrame,
    transformed: pd.DataFrame,
    excluded_columns: list[str] | tuple[str, ...] = (),
) -> UtilityEvaluation:
    """Сравнивает аналитические свойства исходной и обработанной таблиц в одной сессии."""
    excluded = set(map(str, excluded_columns))
    original_columns = [str(column) for column in original.columns]
    transformed_columns = [str(column) for column in transformed.columns]
    common_columns = [
        column for column in original_columns
        if column in transformed_columns and column not in excluded
    ]
    removed_columns = [column for column in original_columns if column not in transformed_columns]
    added_columns = [column for column in transformed_columns if column not in original_columns]

    rows: list[dict[str, Any]] = []
    numeric_columns: list[str] = []
    numeric_count = 0
    categorical_count = 0
    for column in common_columns:
        before = original[column]
        after = transformed[column]
        numeric_pair = _is_numeric_pair(before, after)
        if numeric_pair:
            numeric_columns.append(column)
            numeric_count += 1
            before_metrics = _numeric_metrics(before)
            after_metrics = _numeric_metrics(after)
            mean_change = _relative_change(before_metrics["mean"], after_metrics["mean"])
            variance_change = _relative_change(before_metrics["variance"], after_metrics["variance"])
            tvd = None
            data_kind = "Числовой"
        else:
            categorical_count += 1
            before_metrics = {key: None for key in ("mean", "variance", "median", "q1", "q3", "iqr")}
            after_metrics = before_metrics.copy()
            mean_change = None
            variance_change = None
            tvd = _distribution_tvd(before, after)
            data_kind = "Категориальный / дата / иной"

        rows.append({
            "Атрибут": column,
            "Тип сравнения": data_kind,
            "n до": int(before.notna().sum()),
            "n после": int(after.notna().sum()),
            "Пропуски до, %": _missing_percent(before),
            "Пропуски после, %": _missing_percent(after),
            "Уникальных до": int(before.nunique(dropna=True)),
            "Уникальных после": int(after.nunique(dropna=True)),
            "Среднее до": before_metrics["mean"],
            "Среднее после": after_metrics["mean"],
            "Изменение среднего, %": mean_change,
            "Выборочная дисперсия до": before_metrics["variance"],
            "Выборочная дисперсия после": after_metrics["variance"],
            "Изменение дисперсии, %": variance_change,
            "Медиана до": before_metrics["median"],
            "Медиана после": after_metrics["median"],
            "IQR до": before_metrics["iqr"],
            "IQR после": after_metrics["iqr"],
            "TVD категорий": tvd,
        })

    correlation_rows: list[dict[str, Any]] = []
    for index, first in enumerate(numeric_columns):
        for second in numeric_columns[index + 1:]:
            for method in ("Pearson", "Spearman"):
                before_value, before_n, after_value, after_n = _pair_correlation(
                    original[first], original[second],
                    transformed[first], transformed[second],
                    method.casefold(),
                )
                correlation_rows.append({
                    "Атрибут 1": first,
                    "Атрибут 2": second,
                    "Метод": method,
                    "Коэффициент до": before_value,
                    "Коэффициент после": after_value,
                    "Абсолютное изменение": (
                        abs(after_value - before_value)
                        if before_value is not None and after_value is not None
                        else None
                    ),
                    "Парных наблюдений до": before_n,
                    "Парных наблюдений после": after_n,
                })

    attributes = pd.DataFrame(rows)
    correlations = pd.DataFrame(correlation_rows)
    summary = {
        "common_columns": len(common_columns),
        "numeric_columns": numeric_count,
        "categorical_columns": categorical_count,
        "removed_columns": len(removed_columns),
        "added_columns": len(added_columns),
        "original_rows": len(original),
        "transformed_rows": len(transformed),
        "note": (
            "Оценка полезности описывает различия между двумя таблицами. "
            "Она не является доказательством приватности и не формирует единый оптимальный балл."
        ),
    }
    return UtilityEvaluation(
        attributes=attributes,
        correlations=correlations,
        summary=summary,
        excluded_columns=sorted(excluded),
        removed_columns=removed_columns,
        added_columns=added_columns,
    )
