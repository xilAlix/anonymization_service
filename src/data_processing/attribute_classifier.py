from dataclasses import dataclass
from typing import Iterable

import pandas as pd

from data_processing.algorithms.attribute_detection import suggest_attribute_roles


ROLE_LABELS = {
    "direct_identifier": "Прямой идентификатор",
    "quasi_identifier": "Квази-идентификатор",
    "sensitive_attribute": "Конфиденциальный атрибут",
    "analytical_attribute": "Аналитический атрибут",
}


@dataclass(frozen=True)
class RoleSuggestion:
    role: str
    confidence: str
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class AttributeClassificationResult:
    attribute: str
    pandas_type: str
    suggestions: tuple[RoleSuggestion, ...]
    assigned_roles: tuple[str, ...]
    assignment_source: str


def _plain_values(series: pd.Series) -> Iterable[object]:
    for value in series.tolist():
        yield None if pd.isna(value) else value


def classify_attributes(
    dataframe: pd.DataFrame,
    manual_overrides: dict[str, list[str]] | None = None,
) -> list[AttributeClassificationResult]:
    """Адаптирует результаты алгоритма к моделям, используемым интерфейсом."""
    overrides = manual_overrides or {}
    results: list[AttributeClassificationResult] = []

    for column, series in dataframe.items():
        attribute = str(column)
        raw_suggestions = suggest_attribute_roles(attribute, _plain_values(series))
        suggestions = tuple(
            RoleSuggestion(
                role=item["role"],
                confidence=item["confidence"],
                reasons=tuple(item["reasons"]),
            )
            for item in raw_suggestions
        )
        if attribute in overrides:
            assigned_roles = tuple(overrides[attribute])
            source = "Вручную"
        else:
            assigned_roles = tuple(item.role for item in suggestions)
            source = "Автоматически"

        results.append(
            AttributeClassificationResult(
                attribute=attribute,
                pandas_type=str(series.dtype),
                suggestions=suggestions,
                assigned_roles=assigned_roles,
                assignment_source=source,
            )
        )

    return results


def role_labels(roles: Iterable[str]) -> str:
    labels = [ROLE_LABELS[role] for role in roles if role in ROLE_LABELS]
    return ", ".join(labels) if labels else "Не назначены"
