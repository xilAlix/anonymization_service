from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from data_processing.semantic_types import numeric_values
from data_analysis.descriptive_statistics import detect_date_format


def parse_date_value(value: Any, date_format: str | None = None) -> pd.Timestamp:
    if date_format:
        return pd.to_datetime(value, format=date_format, errors="coerce", exact=True)
    text = str(value).strip()
    if len(text) >= 10 and text[0:4].isdigit() and text[4] in "-/" and text[7] in "-/":
        return pd.to_datetime(value, errors="coerce", dayfirst=False)
    return pd.to_datetime(value, errors="coerce", dayfirst=True)


@dataclass(frozen=True)
class ColumnMetric:
    name: str
    kind: str
    center: Any = None
    scale: float = 1.0
    minimum: float | None = None
    maximum: float | None = None
    date_format: str | None = None


class MixedRecordDistance:
    def __init__(
        self,
        dataframe: pd.DataFrame,
        columns: list[str],
        semantic_types: dict[str, str] | None = None,
    ):
        if not columns:
            raise ValueError("Для микроагрегации не выбраны атрибуты.")
        self.dataframe = dataframe
        self.columns = list(columns)
        self.semantic_types = semantic_types or {}
        self.metrics = [self._build_metric(column) for column in self.columns]
        self.numeric_only = all(metric.kind == "numeric" for metric in self.metrics)
        self.values = {
            column: dataframe[column].tolist() for column in self.columns
        }

    @staticmethod
    def _is_date_series(series: pd.Series) -> bool:
        if pd.api.types.is_datetime64_any_dtype(series.dtype):
            return True
        sample = series.dropna().astype(str).head(100)
        if sample.empty:
            return False
        patterns = (
            r"^\d{4}-\d{1,2}-\d{1,2}(?:[T ].*)?$",
            r"^\d{1,2}[./-]\d{1,2}[./-]\d{2,4}$",
            r"^\d{4}/\d{1,2}/\d{1,2}$",
        )
        matched = sample.str.match("|".join(f"(?:{pattern})" for pattern in patterns))
        return bool(len(matched) and matched.mean() >= 0.85)

    def _build_metric(self, column: str) -> ColumnMetric:
        series = self.dataframe[column]
        semantic_type = self.semantic_types.get(column, "auto")
        if semantic_type in {"categorical", "identifier"}:
            return ColumnMetric(column, "categorical")
        if semantic_type == "datetime":
            date_format = None
            if pd.api.types.is_datetime64_any_dtype(series.dtype):
                parsed = pd.to_datetime(series, errors="coerce")
            else:
                date_format, ambiguous = detect_date_format(series)
                if date_format is None:
                    reason = "неоднозначен" if ambiguous else "не распознан"
                    raise ValueError(
                        f"Столбец «{column}» назначен типом «Дата/время», но формат {reason}. "
                        "Для k-анонимизации используйте однозначный формат даты."
                    )
                parsed = pd.to_datetime(
                    series.astype("string").str.strip(),
                    format=date_format,
                    errors="coerce",
                    exact=True,
                )
            invalid_count = int((series.notna() & parsed.isna()).sum())
            if invalid_count:
                raise ValueError(
                    f"Столбец «{column}» назначен типом «Дата/время», "
                    f"но {invalid_count} непустых значений не удалось распознать."
                )
            numbers = parsed.dropna().astype("int64").to_numpy(dtype=float)
            spread = float(np.quantile(numbers, 0.75) - np.quantile(numbers, 0.25)) if len(numbers) else 1.0
            if not np.isfinite(spread) or spread <= 0:
                spread = float(np.max(numbers) - np.min(numbers)) if len(numbers) else 1.0
            return ColumnMetric(
                column, "date", None, spread if spread > 0 else 1.0, date_format=date_format
            )

        normalized_name = column.casefold().replace("-", "_").replace(" ", "_")
        name_tokens = set(normalized_name.replace(".", "_").split("_"))
        identifier_like_numeric = bool(name_tokens & {
            "postal", "postcode", "postcode", "zip", "pin", "pincode",
            "id", "identifier", "account", "passport", "phone", "telephone",
        })
        if semantic_type == "numeric":
            numeric_candidate = numeric_values(series, column).replace(
                [np.inf, -np.inf], np.nan
            )
        else:
            numeric_candidate = pd.to_numeric(series, errors="coerce").replace(
                [np.inf, -np.inf], np.nan
            )
        non_missing_count = int(series.notna().sum())
        numeric_ratio = (
            float(numeric_candidate.notna().sum()) / non_missing_count
            if non_missing_count else 0.0
        )
        if semantic_type == "numeric" and non_missing_count and numeric_ratio < 1.0:
            raise ValueError(
                f"Столбец «{column}» назначен числовым, но содержит значения, "
                "которые нельзя преобразовать в число."
            )
        is_numeric = (
            semantic_type == "numeric"
            or (
                semantic_type == "auto"
                and not identifier_like_numeric
                and not pd.api.types.is_bool_dtype(series.dtype)
                and (
                    pd.api.types.is_numeric_dtype(series.dtype)
                    or numeric_ratio >= 0.9
                )
            )
        )
        if is_numeric:
            numeric = numeric_candidate.dropna().astype(float)
            median = float(numeric.median()) if len(numeric) else 0.0
            q1 = float(numeric.quantile(0.25)) if len(numeric) else 0.0
            q3 = float(numeric.quantile(0.75)) if len(numeric) else 0.0
            scale = q3 - q1
            if not np.isfinite(scale) or scale <= 0:
                mad = float((numeric - median).abs().median()) if len(numeric) else 0.0
                scale = 1.4826 * mad
            if not np.isfinite(scale) or scale <= 0:
                scale = float(numeric.max() - numeric.min()) if len(numeric) else 1.0
            if not np.isfinite(scale) or scale <= 0:
                scale = 1.0
            return ColumnMetric(column, "numeric", median, scale)

        if self._is_date_series(series):
            date_format, ambiguous = detect_date_format(series)
            if date_format is not None:
                parsed = pd.to_datetime(
                    series.astype("string").str.strip(),
                    format=date_format,
                    errors="coerce",
                    exact=True,
                )
                invalid_count = int((series.notna() & parsed.isna()).sum())
                if invalid_count == 0:
                    numbers = parsed.dropna().astype("int64").to_numpy(dtype=float)
                    spread = float(np.quantile(numbers, 0.75) - np.quantile(numbers, 0.25)) if len(numbers) else 1.0
                    if not np.isfinite(spread) or spread <= 0:
                        spread = float(np.max(numbers) - np.min(numbers)) if len(numbers) else 1.0
                    return ColumnMetric(
                        column, "date", None, spread if spread > 0 else 1.0, date_format=date_format
                    )
            elif ambiguous:
                return ColumnMetric(column, "categorical")

        return ColumnMetric(column, "categorical")

    @staticmethod
    def _missing(value: Any) -> bool:
        try:
            return bool(pd.isna(value))
        except (TypeError, ValueError):
            return False

    def _numeric_value(self, column: str, index: int) -> float | None:
        value = self.values[column][index]
        if self._missing(value):
            return None
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return None
        return numeric if np.isfinite(numeric) else None

    def _date_value(self, column: str, index: int) -> int | None:
        value = self.values[column][index]
        if self._missing(value):
            return None
        metric = next(item for item in self.metrics if item.name == column)
        parsed = parse_date_value(value, metric.date_format)
        if pd.isna(parsed):
            return None
        return int(parsed.value)

    def centroid(self, indices: list[int]) -> dict[str, Any]:
        center: dict[str, Any] = {}
        for metric in self.metrics:
            column = metric.name
            if metric.kind == "numeric":
                values = [self._numeric_value(column, index) for index in indices]
                valid = [value for value in values if value is not None]
                center[column] = float(np.mean(valid)) if valid else None
            elif metric.kind == "date":
                values = [self._date_value(column, index) for index in indices]
                valid = [value for value in values if value is not None]
                center[column] = int(np.median(valid)) if valid else None
            else:
                values = [self.values[column][index] for index in indices]
                valid = [value for value in values if not self._missing(value)]
                if not valid:
                    center[column] = None
                else:
                    counts: dict[str, tuple[int, Any]] = {}
                    for value in valid:
                        key = f"{type(value).__qualname__}:{value}"
                        old = counts.get(key, (0, value))
                        counts[key] = (old[0] + 1, value)
                    center[column] = min(
                        counts.values(), key=lambda item: (-item[0], str(item[1]))
                    )[1]
        return center

    def distance_to_centroid(self, index: int, center: dict[str, Any]) -> float:
        if self.numeric_only:
            squared = []
            for metric in self.metrics:
                value = self._numeric_value(metric.name, index)
                target = center[metric.name]
                if value is None or target is None:
                    squared.append(1.0)
                else:
                    squared.append(((value - target) / metric.scale) ** 2)
            return float(np.sqrt(np.sum(squared)))

        distances: list[float] = []
        for metric in self.metrics:
            value = self.values[metric.name][index]
            target = center[metric.name]
            if self._missing(value) and self._missing(target):
                distances.append(0.0)
            elif self._missing(value) or self._missing(target):
                distances.append(1.0)
            elif metric.kind == "numeric":
                numeric = float(value)
                distances.append(min(abs(numeric - float(target)) / metric.scale, 1.0))
            elif metric.kind == "date":
                parsed = parse_date_value(value, metric.date_format)
                if pd.isna(parsed):
                    distances.append(1.0)
                else:
                    numeric = int(parsed.value)
                    distances.append(min(abs(numeric - int(target)) / metric.scale, 1.0))
            else:
                distances.append(0.0 if value == target else 1.0)
        return float(np.mean(distances)) if distances else 0.0

    def distance_between(self, first: int, second: int) -> float:
        if self.numeric_only:
            squared = []
            for metric in self.metrics:
                left = self._numeric_value(metric.name, first)
                right = self._numeric_value(metric.name, second)
                if left is None and right is None:
                    difference = 0.0
                elif left is None or right is None:
                    difference = 1.0
                else:
                    difference = (left - right) / metric.scale
                squared.append(difference * difference)
            return float(np.sqrt(np.sum(squared)))

        distances: list[float] = []
        for metric in self.metrics:
            column = metric.name
            left = self.values[column][first]
            right = self.values[column][second]
            if self._missing(left) and self._missing(right):
                distances.append(0.0)
            elif self._missing(left) or self._missing(right):
                distances.append(1.0)
            elif metric.kind == "numeric":
                distances.append(min(abs(float(left) - float(right)) / metric.scale, 1.0))
            elif metric.kind == "date":
                left_date = parse_date_value(left, metric.date_format)
                right_date = parse_date_value(right, metric.date_format)
                if pd.isna(left_date) or pd.isna(right_date):
                    distances.append(1.0)
                else:
                    distances.append(min(abs(left_date.value - right_date.value) / metric.scale, 1.0))
            else:
                distances.append(0.0 if left == right else 1.0)
        return float(np.mean(distances)) if distances else 0.0
