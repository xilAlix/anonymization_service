from __future__ import annotations

import re

import pandas as pd
from pandas.api.types import is_bool_dtype, is_datetime64_any_dtype, is_numeric_dtype


SEMANTIC_TYPE_LABELS = {
    "auto": "Автоматически",
    "numeric": "Числовой",
    "categorical": "Категориальный",
    "datetime": "Дата и время",
    "identifier": "Идентификатороподобный",
}
SEMANTIC_TYPE_VALUES = frozenset(SEMANTIC_TYPE_LABELS)

_IDENTIFIER_TOKENS = {
    "id", "identifier", "code", "account", "passport",
    "postal", "postcode", "zip", "pin", "pincode", "номер", "код",
    "идентификатор", "счёт", "счет", "паспорт", "индекс", "name",
    "email", "mail", "phone", "telephone", "mobile", "телефон",
    "почта", "фио", "имя", "фамилия", "отчество",
}
_DATE_TOKENS = {"date", "datetime", "time", "дата", "время"}


def suggest_semantic_type(column: str, series: pd.Series) -> str:
    """Возвращает предварительную семантическую подсказку без автоматического назначения."""
    if is_datetime64_any_dtype(series.dtype):
        return "datetime"
    tokens = {
        token for token in re.split(r"[^a-zа-яё0-9]+", str(column).casefold()) if token
    }
    if tokens & _IDENTIFIER_TOKENS:
        return "identifier"
    if "number" in tokens and tokens & {
        "customer", "employee", "transaction", "account", "invoice", "order", "passport"
    }:
        return "identifier"
    if tokens & _DATE_TOKENS:
        return "datetime"
    if is_bool_dtype(series.dtype):
        return "categorical"
    if is_numeric_dtype(series.dtype):
        return "numeric"
    return "categorical"


def resolve_semantic_type(
    column: str,
    series: pd.Series,
    semantic_types: dict[str, str] | None = None,
) -> str:
    selected = (semantic_types or {}).get(str(column), "auto")
    if not isinstance(selected, str) or selected not in SEMANTIC_TYPE_VALUES:
        raise ValueError(f"Для столбца «{column}» задан неизвестный семантический тип: {selected}.")
    return suggest_semantic_type(str(column), series) if selected == "auto" else selected


def numeric_values(series: pd.Series, column: str) -> pd.Series:
    converted = pd.to_numeric(series, errors="coerce").replace([float("inf"), float("-inf")], pd.NA)
    invalid = series.notna() & converted.isna()
    if bool(invalid.any()):
        examples = series.loc[invalid].astype(str).head(3).tolist()
        raise ValueError(
            f"Столбец «{column}» назначен числовым, но содержит значения, "
            f"которые нельзя преобразовать в число: {', '.join(examples)}."
        )
    return converted


def validate_semantic_types(semantic_types: dict[str, str]) -> dict[str, str]:
    if not isinstance(semantic_types, dict):
        raise ValueError("Семантические типы должны иметь формат «столбец: тип».")
    validated: dict[str, str] = {}
    for column, semantic_type in semantic_types.items():
        if not isinstance(column, str) or not column.strip():
            raise ValueError("Название столбца для семантического типа не должно быть пустым.")
        if not isinstance(semantic_type, str) or semantic_type not in SEMANTIC_TYPE_VALUES:
            raise ValueError(f"Неизвестный семантический тип для столбца «{column}».")
        if semantic_type != "auto":
            validated[column] = semantic_type
    return validated
