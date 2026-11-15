from __future__ import annotations

from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd
from pandas.api.types import is_bool_dtype, is_datetime64_any_dtype, is_numeric_dtype


DATE_FORMATS: dict[str, str] = {
    "ГГГГ-ММ-ДД": "%Y-%m-%d",
    "ГГГГ-ММ-ДД ЧЧ:ММ": "%Y-%m-%d %H:%M",
    "ГГГГ-ММ-ДД ЧЧ:ММ:СС": "%Y-%m-%d %H:%M:%S",
    "ГГГГ-ММ-ДДTЧЧ:ММ:СС": "%Y-%m-%dT%H:%M:%S",
    "ДД.ММ.ГГГГ": "%d.%m.%Y",
    "ДД.ММ.ГГГГ ЧЧ:ММ:СС": "%d.%m.%Y %H:%M:%S",
    "ДД/ММ/ГГГГ": "%d/%m/%Y",
    "ММ/ДД/ГГГГ": "%m/%d/%Y",
    "ДД-ММ-ГГГГ": "%d-%m-%Y",
    "ММ-ДД-ГГГГ": "%m-%d-%Y",
}

_AUTO_DATE_FORMATS = tuple(dict.fromkeys(DATE_FORMATS.values()))

STATISTIC_ROWS = [
    "Количество непустых значений (n)",
    "Среднее (оценка мат. ожидания)",
    "Выборочная дисперсия",
    "Стандартное отклонение",
    "Медиана",
    "Минимум",
    "Максимум",
    "Q1 (25%)",
    "Q3 (75%)",
    "Межквартильный размах (IQR = Q3 − Q1)",
    "Нижние выбросы",
    "Верхние выбросы",
    "Асимметрия",
    "Эксцесс (Фишера)",
    "Мода",
    "Уникальные значения",
    "Пропуски",
    "Пропуски, %",
    "Энтропия (бит)",
    "Первая дата",
    "Последняя дата",
    "Медианная дата",
    "Ошибки распознавания дат",
]


def _date_match_count(values: pd.Series, date_format: str) -> int:
    matched = 0
    for value in values:
        try:
            datetime.strptime(str(value).strip(), date_format)
            matched += 1
        except (TypeError, ValueError, OverflowError):
            continue
    return matched


def detect_date_format(series: pd.Series) -> tuple[str | None, bool]:
    """Ищет единый формат минимум для 90% непустых значений; неоднозначность не угадывает."""
    values = series.dropna().astype(str).str.strip()
    if len(values) < 2:
        return None, False

    candidates = []
    required_matches = max(2, int(np.ceil(len(values) * 0.9)))
    for date_format in _AUTO_DATE_FORMATS:
        match_count = _date_match_count(values, date_format)
        if match_count >= required_matches:
            candidates.append((date_format, match_count))

    if not candidates:
        return None, False

    best_count = max(count for _, count in candidates)
    best_formats = [date_format for date_format, count in candidates if count == best_count]
    if len(best_formats) == 1:
        return best_formats[0], False
    return None, True


def inspect_date_columns(dataframe: pd.DataFrame) -> dict[str, dict[str, Any]]:
    """Диагностика строковых столбцов для диалога ручного назначения дат."""
    result: dict[str, dict[str, Any]] = {}
    for column in dataframe.columns:
        series = dataframe[column]
        if is_datetime64_any_dtype(series.dtype):
            result[str(column)] = {
                "format": None,
                "ambiguous": False,
                "detected": True,
                "sample": _sample_values(series),
            }
            continue
        if not (series.dtype == object or pd.api.types.is_string_dtype(series.dtype)):
            continue
        detected_format, ambiguous = detect_date_format(series)
        result[str(column)] = {
            "format": detected_format,
            "ambiguous": ambiguous,
            "detected": detected_format is not None,
            "sample": _sample_values(series),
        }
    return result


def _sample_values(series: pd.Series, limit: int = 3) -> str:
    values = series.dropna().astype(str).head(limit).tolist()
    return "; ".join(values) if values else "нет значений"


def classify_analysis_columns(
    dataframe: pd.DataFrame,
    date_formats: dict[str, str] | None = None,
) -> tuple[dict[str, str], dict[str, pd.Series], dict[str, int]]:
    """Определяет типы столбцов и возвращает преобразованные даты без изменения источника."""
    date_formats = date_formats or {}
    unknown_columns = set(date_formats) - {str(column) for column in dataframe.columns}
    if unknown_columns:
        raise ValueError(
            "В параметрах дат указаны отсутствующие столбцы: "
            + ", ".join(sorted(unknown_columns))
        )

    kinds: dict[str, str] = {}
    parsed_dates: dict[str, pd.Series] = {}
    date_errors: dict[str, int] = {}

    for original_column in dataframe.columns:
        column = str(original_column)
        series = dataframe[original_column]

        if column in date_formats:
            date_format = date_formats[column]
            if not isinstance(date_format, str) or not date_format:
                raise ValueError(f"Для столбца «{column}» задан пустой формат даты.")
            parsed = pd.to_datetime(
                series.astype("string").str.strip(),
                format=date_format,
                errors="coerce",
                exact=True,
            )
            invalid_count = int((series.notna() & parsed.isna()).sum())
            kinds[column] = "date"
            parsed_dates[column] = parsed
            date_errors[column] = invalid_count
            continue

        if is_datetime64_any_dtype(series.dtype):
            parsed = pd.to_datetime(series, errors="coerce")
            kinds[column] = "date"
            parsed_dates[column] = parsed
            date_errors[column] = int((series.notna() & parsed.isna()).sum())
            continue

        if is_bool_dtype(series.dtype):
            kinds[column] = "categorical"
            continue

        if is_numeric_dtype(series.dtype):
            kinds[column] = "numeric"
            continue

        detected_format, _ = detect_date_format(series)
        if detected_format is not None:
            parsed = pd.to_datetime(
                series.astype("string").str.strip(),
                format=detected_format,
                errors="coerce",
                exact=True,
            )
            kinds[column] = "date"
            parsed_dates[column] = parsed
            date_errors[column] = int((series.notna() & parsed.isna()).sum())
        else:
            kinds[column] = "categorical"

    return kinds, parsed_dates, date_errors


def _display_value(value: Any) -> str:
    if pd.isna(value):
        return "—"
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat(sep=" ")
    if isinstance(value, (np.integer,)):
        return str(int(value))
    if isinstance(value, (np.floating, float)):
        return f"{float(value):.12g}"
    return str(value)


def _count_label(count: int) -> str:
    remainder = count % 10
    last_two = count % 100
    if remainder == 1 and last_two != 11:
        return "раз"
    if remainder in {2, 3, 4} and last_two not in {12, 13, 14}:
        return "раза"
    return "раз"


def _format_modes(series: pd.Series) -> str:
    counts = series.dropna().value_counts(dropna=True, sort=False)
    if counts.empty:
        return "—"
    max_count = int(counts.max())
    if max_count == 1:
        return "нет повторяющейся моды (частота 1)"
    modes = sorted(counts[counts == max_count].index.tolist(), key=lambda value: str(value))
    return "; ".join(
        f"{_display_value(value)} ({max_count} {_count_label(max_count)})" for value in modes
    )


def _format_extreme_outliers(values: pd.Series, lower: bool) -> str:
    if values.empty:
        return "нет"
    counts = values.value_counts(dropna=True, sort=False)
    unique_values = sorted(counts.index.tolist(), reverse=not lower)[:2]
    return "; ".join(
        f"{_display_value(value)} ({int(counts.loc[value])} {_count_label(int(counts.loc[value]))})"
        for value in unique_values
    )


def _entropy_bits(series: pd.Series) -> float | None:
    counts = series.dropna().value_counts(dropna=True)
    if counts.empty:
        return None
    probabilities = counts.to_numpy(dtype=float) / float(counts.sum())
    return float(-(probabilities * np.log2(probabilities)).sum())


def _median_timestamp(series: pd.Series) -> pd.Timestamp | pd.NaT:
    ordered = series.dropna().sort_values().reset_index(drop=True)
    count = len(ordered)
    if count == 0:
        return pd.NaT
    middle = count // 2
    if count % 2:
        return pd.Timestamp(ordered.iloc[middle])
    left = pd.Timestamp(ordered.iloc[middle - 1])
    right = pd.Timestamp(ordered.iloc[middle])
    return left + (right - left) / 2


def calculate_descriptive_statistics(
    dataframe: pd.DataFrame,
    column_kinds: dict[str, str],
    parsed_dates: dict[str, pd.Series] | None = None,
    date_errors: dict[str, int] | None = None,
) -> pd.DataFrame:
    parsed_dates = parsed_dates or {}
    date_errors = date_errors or {}
    total_rows = len(dataframe)
    result: dict[str, dict[str, Any]] = {}

    for original_column in dataframe.columns:
        column = str(original_column)
        kind = column_kinds[column]
        source = dataframe[original_column]
        missing_count = int(source.isna().sum())
        missing_percent = (missing_count / total_rows * 100.0) if total_rows else "—"
        metrics: dict[str, Any] = {row: "—" for row in STATISTIC_ROWS}
        metrics["Пропуски"] = missing_count
        metrics["Пропуски, %"] = missing_percent

        if kind == "numeric":
            values = source.dropna()
            n = len(values)
            metrics["Количество непустых значений (n)"] = n
            metrics["Уникальные значения"] = int(values.nunique(dropna=True))
            if n:
                metrics["Среднее (оценка мат. ожидания)"] = float(values.mean())
                metrics["Медиана"] = float(values.median())
                metrics["Минимум"] = _display_value(values.min())
                metrics["Максимум"] = _display_value(values.max())
                metrics["Мода"] = _format_modes(values)
                if n >= 2:
                    metrics["Выборочная дисперсия"] = float(values.var(ddof=1))
                    metrics["Стандартное отклонение"] = float(values.std(ddof=1))
                q1 = float(values.quantile(0.25, interpolation="linear"))
                q3 = float(values.quantile(0.75, interpolation="linear"))
                iqr = q3 - q1
                lower_fence = q1 - 1.5 * iqr
                upper_fence = q3 + 1.5 * iqr
                metrics["Q1 (25%)"] = q1
                metrics["Q3 (75%)"] = q3
                metrics["Межквартильный размах (IQR = Q3 − Q1)"] = iqr
                metrics["Нижние выбросы"] = _format_extreme_outliers(
                    values[values < lower_fence], lower=True
                )
                metrics["Верхние выбросы"] = _format_extreme_outliers(
                    values[values > upper_fence], lower=False
                )
                if n >= 3 and values.nunique() > 1:
                    metrics["Асимметрия"] = float(values.skew())
                if n >= 4 and values.nunique() > 1:
                    metrics["Эксцесс (Фишера)"] = float(values.kurt())

        elif kind == "categorical":
            values = source.dropna()
            n = len(values)
            metrics["Количество непустых значений (n)"] = n
            metrics["Уникальные значения"] = int(values.nunique(dropna=True))
            metrics["Мода"] = _format_modes(values)
            entropy = _entropy_bits(values)
            metrics["Энтропия (бит)"] = entropy if entropy is not None else "—"

        elif kind == "date":
            parsed = parsed_dates.get(column)
            if parsed is None:
                parsed = pd.to_datetime(source, errors="coerce")
            valid = parsed.dropna()
            n = int(source.notna().sum())
            valid_count = len(valid)
            metrics["Количество непустых значений (n)"] = n
            metrics["Первая дата"] = _display_value(valid.min()) if valid_count else "—"
            metrics["Последняя дата"] = _display_value(valid.max()) if valid_count else "—"
            metrics["Медианная дата"] = _display_value(_median_timestamp(valid)) if valid_count else "—"
            metrics["Мода"] = _format_modes(valid)
            metrics["Уникальные значения"] = int(valid.nunique())
            metrics["Ошибки распознавания дат"] = int(date_errors.get(column, 0))

        result[column] = metrics

    statistics = pd.DataFrame(result, index=STATISTIC_ROWS)
    statistics.index.name = "Показатель"
    return statistics
