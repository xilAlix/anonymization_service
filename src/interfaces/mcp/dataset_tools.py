from __future__ import annotations

from typing import Any


from data_processing.attribute_classifier import classify_attributes
from data_processing.quasi_identifier_analyzer import suggest_quasi_identifier_groups
from data_processing.semantic_types import suggest_semantic_type
from infrastructure.attribute_profile_store import (
    DEFAULT_PROFILE_PATH,
    load_manual_role_overrides,
    load_quasi_identifier_groups,
    load_semantic_types,
)
from interfaces.mcp.registry import DatasetRegistry


def list_datasets(registry: DatasetRegistry) -> dict[str, Any]:
    try:
        datasets = registry.list_datasets()
    except (OSError, ValueError):
        return {
            "ok": False,
            "error_code": "workspace_unavailable",
            "message": "Не удалось просмотреть разрешённую рабочую папку.",
        }
    return {"ok": True, "count": len(datasets), "datasets": datasets}


def open_dataset(registry: DatasetRegistry, dataset_id: str) -> dict[str, Any]:
    try:
        return registry.open_dataset(dataset_id)
    except KeyError:
        return {
            "ok": False,
            "error_code": "unknown_dataset_id",
            "message": "dataset_id не найден. Сначала обновите список CSV.",
        }
    except RuntimeError:
        return {
            "ok": False,
            "error_code": "dataset_changed",
            "message": "CSV изменился после построения списка или во время загрузки. Обновите список.",
        }
    except (OSError, ValueError, LookupError):
        return {
            "ok": False,
            "error_code": "dataset_open_failed",
            "message": "CSV не удалось открыть. Проверьте файл и его структуру.",
        }


def inspect_dataset(
    registry: DatasetRegistry,
    dataset_id: str | None = None,
    profile_path: str = str(DEFAULT_PROFILE_PATH),
) -> dict[str, Any]:
    try:
        session = registry.get_active_session(dataset_id)
    except LookupError:
        return {
            "ok": False,
            "error_code": "dataset_not_open",
            "message": "Сначала откройте CSV через open_dataset.",
        }

    dataframe = session.source_dataframe
    try:
        manual_roles = load_manual_role_overrides(session.source_path, profile_path)
        assigned_types = load_semantic_types(session.source_path, profile_path)
        active_groups = load_quasi_identifier_groups(session.source_path, profile_path)
        role_results = classify_attributes(dataframe, manual_roles)
        potential_groups = suggest_quasi_identifier_groups(dataframe)
    except (OSError, ValueError):
        return {
            "ok": False,
            "error_code": "inspection_failed",
            "message": "Не удалось сформировать локальное описание CSV и его профиля.",
        }

    columns: list[dict[str, Any]] = []
    for attribute, series in dataframe.items():
        name = str(attribute)
        non_null_count = int(series.notna().sum())
        missing_count = int(series.isna().sum())
        unique_count = int(series.nunique(dropna=True))
        assigned_type = assigned_types.get(name, "auto")
        columns.append({
            "name": name,
            "pandas_type": str(series.dtype),
            "semantic_type": assigned_type,
            "semantic_type_suggestion": suggest_semantic_type(name, series),
            "non_null_count": non_null_count,
            "missing_count": missing_count,
            "unique_count": unique_count,
            "unique_percent": round(unique_count / non_null_count * 100, 2)
            if non_null_count else None,
            "manually_assigned_roles": list(manual_roles.get(name, [])),
        })

    role_suggestions: list[dict[str, Any]] = []
    for result in role_results:
        role_suggestions.append({
            "attribute": result.attribute,
            "suggestions": [
                {
                    "role": suggestion.role,
                    "confidence": suggestion.confidence,
                    "reasons": list(suggestion.reasons),
                }
                for suggestion in result.suggestions
            ],
            "assignment_source": result.assignment_source,
        })

    safe_potential_groups = [
        {
            "id": group.get("id"),
            "name": group.get("name"),
            "description": group.get("description"),
            "attributes": list(group.get("attributes", [])),
            "source": group.get("source"),
            "confidence": group.get("confidence"),
            "reasons": list(group.get("reasons", [])),
            "unique_tuple_count": group.get("unique_tuple_count"),
            "unique_tuple_ratio": group.get("unique_tuple_ratio"),
        }
        for group in potential_groups
    ]
    safe_active_groups = [
        {
            "id": group.get("id"),
            "name": group.get("name"),
            "attributes": list(group.get("attributes", [])),
            "active": bool(group.get("active", group.get("source") != "automatic")),
            "k_override": group.get("k_override"),
        }
        for group in active_groups
    ]

    return {
        "ok": True,
        "dataset_id": registry.active_dataset_id,
        "name": session.source_path.name,
        "row_count": int(len(dataframe)),
        "column_count": int(len(dataframe.columns)),
        "columns": columns,
        "role_suggestions": role_suggestions,
        "active_qi_groups": safe_active_groups,
        "potential_qi_groups": safe_potential_groups,
        "source_rows_included": False,
        "sample_values_included": False,
    }
