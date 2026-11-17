from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

import pandas as pd

from data_processing.attribute_classifier import ROLE_LABELS, classify_attributes
from data_processing.quasi_identifier_analyzer import suggest_quasi_identifier_groups
from data_processing.semantic_types import suggest_semantic_type
from infrastructure.attribute_profile_store import (
    DEFAULT_PROFILE_PATH,
    load_manual_role_overrides,
    load_quasi_identifier_correlation_blocks,
    load_quasi_identifier_groups,
    load_quasi_identifier_hierarchies,
    load_semantic_types,
    save_profile_bundle,
)
from interfaces.mcp.action_store import PendingActionStore
from interfaces.mcp.registry import DatasetRegistry


def _profile_snapshot(session, profile_path: str) -> dict[str, Any]:
    return {
        "roles": load_manual_role_overrides(session.source_path, profile_path),
        "semantic_types": load_semantic_types(session.source_path, profile_path),
        "qi_groups": load_quasi_identifier_groups(session.source_path, profile_path),
        "hierarchies": load_quasi_identifier_hierarchies(session.source_path, profile_path),
        "correlation_blocks": load_quasi_identifier_correlation_blocks(session.source_path, profile_path),
    }


def profile_digest(snapshot: dict[str, Any]) -> str:
    payload = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def get_dataset_profile(
    registry: DatasetRegistry,
    dataset_id: str,
    profile_path: str = str(DEFAULT_PROFILE_PATH),
) -> dict[str, Any]:
    try:
        session = registry.get_active_session(dataset_id)
        snapshot = _profile_snapshot(session, profile_path)
    except LookupError:
        return {"ok": False, "error_code": "dataset_not_open", "message": "Сначала откройте CSV."}
    except (OSError, ValueError):
        return {"ok": False, "error_code": "profile_read_failed", "message": "Не удалось прочитать профиль набора."}

    # Иерархии содержат реальные значения категорий; модели передаётся только их структура.
    hierarchy_summary = {
        column: [{"level": index} for index, _ in enumerate(levels, start=1)]
        for column, levels in snapshot["hierarchies"].items()
    }
    safe_groups = [
        {
            "id": group.get("id"),
            "name": group.get("name"),
            "attributes": list(group.get("attributes", [])),
            "source": group.get("source"),
            "active": bool(group.get("active", group.get("source") != "automatic")),
            "k_override": group.get("k_override"),
        }
        for group in snapshot["qi_groups"] if isinstance(group, dict)
    ]

    return {
        "ok": True,
        "dataset_id": dataset_id,
        "roles": snapshot["roles"],
        "semantic_types": snapshot["semantic_types"],
        "qi_groups": safe_groups,
        "hierarchy_summary": hierarchy_summary,
        "correlation_blocks": snapshot["correlation_blocks"],
        "category_mappings_included": False,
        "profile_digest": profile_digest(snapshot),
    }


def suggest_attribute_roles(registry: DatasetRegistry, dataset_id: str) -> dict[str, Any]:
    try:
        session = registry.get_active_session(dataset_id)
        manual = load_manual_role_overrides(session.source_path)
        suggestions = classify_attributes(session.source_dataframe, manual)
    except LookupError:
        return {"ok": False, "error_code": "dataset_not_open", "message": "Сначала откройте CSV."}
    results = []
    for item in suggestions:
        results.append({
            "attribute": item.attribute,
            "assigned_roles": list(item.assigned_roles),
            "assignment_source": item.assignment_source,
            "suggestions": [
                {"role": entry.role, "confidence": entry.confidence}
                for entry in item.suggestions
            ],
        })
    return {"ok": True, "dataset_id": dataset_id, "attributes": results}


def suggest_semantic_types_tool(registry: DatasetRegistry, dataset_id: str) -> dict[str, Any]:
    try:
        session = registry.get_active_session(dataset_id)
        assigned = load_semantic_types(session.source_path)
    except LookupError:
        return {"ok": False, "error_code": "dataset_not_open", "message": "Сначала откройте CSV."}
    return {
        "ok": True,
        "dataset_id": dataset_id,
        "types": [
            {
                "attribute": str(column),
                "pandas_type": str(series.dtype),
                "assigned_type": assigned.get(str(column), "auto"),
                "suggested_type": suggest_semantic_type(str(column), series),
            }
            for column, series in session.source_dataframe.items()
        ],
    }


def suggest_qi_groups_tool(registry: DatasetRegistry, dataset_id: str) -> dict[str, Any]:
    try:
        session = registry.get_active_session(dataset_id)
        groups = suggest_quasi_identifier_groups(session.source_dataframe)
    except LookupError:
        return {"ok": False, "error_code": "dataset_not_open", "message": "Сначала откройте CSV."}
    return {
        "ok": True,
        "dataset_id": dataset_id,
        "groups": [
            {
                "name": group.get("name"),
                "description": group.get("description"),
                "attributes": list(group.get("attributes", [])),
                "confidence": group.get("confidence"),
                "unique_tuple_count": group.get("unique_tuple_count"),
                "unique_tuple_ratio": group.get("unique_tuple_ratio"),
                "reasons": list(group.get("reasons", [])),
            }
            for group in groups
        ],
    }


def get_category_values_tool(
    registry: DatasetRegistry,
    dataset_id: str,
    column: str,
    minimum_frequency: int = 5,
    profile_path: str = str(DEFAULT_PROFILE_PATH),
) -> dict[str, Any]:
    try:
        session = registry.get_active_session(dataset_id)
        if column not in session.source_dataframe.columns:
            return {"ok": False, "error_code": "unknown_column", "message": "Столбец не найден."}
        roles = load_manual_role_overrides(session.source_path, profile_path)
        if "direct_identifier" in roles.get(column, []):
            return {"ok": False, "error_code": "direct_identifier_blocked", "message": "Категории прямого идентификатора не выдаются."}
        # Даже без ручной роли блокируем столбцы, которые локальный классификатор
        # с высокой уверенностью распознал как прямые идентификаторы.
        assigned_semantic_type = load_semantic_types(session.source_path, profile_path).get(column, "auto")
        if assigned_semantic_type == "identifier":
            return {"ok": False, "error_code": "direct_identifier_blocked", "message": "Столбец семантического типа identifier не выдаётся как набор категорий."}
        classification = next(
            (item for item in classify_attributes(session.source_dataframe, roles) if item.attribute == column),
            None,
        )
        if classification and any(item.role == "direct_identifier" for item in classification.suggestions):
            return {"ok": False, "error_code": "direct_identifier_blocked", "message": "Локальный классификатор обнаружил признаки прямого идентификатора; категории не выдаются."}
        if isinstance(minimum_frequency, bool) or not isinstance(minimum_frequency, int) or minimum_frequency < 5:
            return {"ok": False, "error_code": "invalid_threshold", "message": "Минимальная частота должна быть целым числом не меньше 5."}
        effective_threshold = minimum_frequency
        for group in load_quasi_identifier_groups(session.source_path, profile_path):
            if group.get("active", group.get("source") != "automatic"):
                effective_threshold = max(effective_threshold, int(group.get("k_override") or 2))
        counts = session.source_dataframe[column].dropna().astype(str).value_counts()
        selected = [
            {"value": str(value), "count": int(count)}
            for value, count in counts.items()
            if int(count) >= effective_threshold
        ]
        selected = selected[:200]
        return {
            "ok": True,
            "dataset_id": dataset_id,
            "column": column,
            "minimum_frequency": effective_threshold,
            "categories": selected,
            "categories_truncated": len([count for count in counts if int(count) >= effective_threshold]) > len(selected),
            "categories_complete": False,
        }
    except LookupError:
        return {"ok": False, "error_code": "dataset_not_open", "message": "Сначала откройте CSV."}


def _validate_profile_updates(session, updates: dict[str, Any], profile_path: str):
    if not isinstance(updates, dict):
        raise ValueError("updates должен быть JSON-объектом.")
    allowed_keys = {"role_updates", "semantic_type_updates", "qi_groups", "hierarchy_updates"}
    unknown_keys = set(updates) - allowed_keys
    if unknown_keys:
        raise ValueError("Неизвестные разделы обновления профиля: " + ", ".join(sorted(map(str, unknown_keys))))

    available = set(map(str, session.source_dataframe.columns))
    current = _profile_snapshot(session, profile_path)

    merged_roles = dict(current["roles"])
    role_updates = updates.get("role_updates")
    if role_updates is not None:
        if not isinstance(role_updates, dict):
            raise ValueError("role_updates должен быть объектом столбец → список ролей.")
        for column, roles in role_updates.items():
            if not isinstance(column, str) or column not in available:
                raise ValueError(f"Столбец «{column}» отсутствует в CSV.")
            if roles is None or roles == []:
                merged_roles.pop(column, None)
            elif (
                not isinstance(roles, list)
                or any(not isinstance(role, str) or role not in ROLE_LABELS for role in roles)
                or len(roles) != len(set(roles))
            ):
                raise ValueError(f"Некорректный список ролей для столбца «{column}».")
            else:
                if "direct_identifier" in roles and "quasi_identifier" in roles:
                    raise ValueError(f"Столбец «{column}» нельзя одновременно назначить прямым и квази-идентификатором.")
                merged_roles[column] = list(roles)

    merged_types = dict(current["semantic_types"])
    type_updates = updates.get("semantic_type_updates")
    if type_updates is not None:
        if not isinstance(type_updates, dict):
            raise ValueError("semantic_type_updates должен быть объектом столбец → тип.")
        for column, semantic_type in type_updates.items():
            if not isinstance(column, str) or column not in available:
                raise ValueError(f"Столбец «{column}» отсутствует в CSV.")
            if semantic_type == "auto":
                merged_types.pop(column, None)
            elif semantic_type in {"numeric", "categorical", "datetime", "identifier"}:
                merged_types[column] = semantic_type
            else:
                raise ValueError(f"Неизвестный семантический тип для столбца «{column}».")

    groups_update = updates.get("qi_groups")
    if groups_update is not None:
        if not isinstance(groups_update, list):
            raise ValueError("qi_groups должен быть полным списком QI-групп.")
        normalized_groups = []
        seen_group_ids: set[str] = set()
        seen_group_names: set[str] = set()
        for index, item in enumerate(groups_update, start=1):
            if not isinstance(item, dict):
                raise ValueError(f"QI-группа №{index} должна быть объектом.")
            name = item.get("name")
            attributes = item.get("attributes")
            description = item.get("description", "Создано AI-ассистентом после подтверждения пользователя.")
            active = item.get("active", True)
            k_override = item.get("k_override")
            group_id = item.get("id") or uuid.uuid4().hex[:10]
            if not isinstance(name, str) or not name.strip() or len(name.strip()) > 120:
                raise ValueError(f"У QI-группы №{index} должно быть непустое название длиной до 120 символов.")
            if (
                not isinstance(attributes, list)
                or not attributes
                or any(not isinstance(attribute, str) or attribute not in available for attribute in attributes)
                or len(attributes) != len(set(attributes))
            ):
                raise ValueError(f"Список атрибутов QI-группы «{name}» пуст, содержит повторы или неизвестные столбцы.")
            if not isinstance(group_id, str) or not group_id.strip() or len(group_id) > 80:
                raise ValueError(f"Некорректный идентификатор QI-группы «{name}».")
            normalized_name = name.strip().casefold()
            if group_id in seen_group_ids or normalized_name in seen_group_names:
                raise ValueError(f"Идентификатор и название QI-группы «{name}» должны быть уникальными.")
            seen_group_ids.add(group_id)
            seen_group_names.add(normalized_name)
            if not isinstance(description, str) or len(description) > 500:
                raise ValueError(f"Описание QI-группы «{name}» должно быть строкой длиной до 500 символов.")
            if not isinstance(active, bool):
                raise ValueError(f"Флаг active QI-группы «{name}» должен быть логическим.")
            if k_override is not None and (
                isinstance(k_override, bool) or not isinstance(k_override, int) or k_override < 2
            ):
                raise ValueError(f"Для QI-группы «{name}» k_override должен быть целым числом не меньше 2.")
            normalized_groups.append({
                "id": group_id,
                "name": name.strip(),
                "attributes": list(attributes),
                "source": "manual",
                "confidence": "manual",
                "description": description,
                "active": active,
                "k_override": k_override,
            })
        groups = normalized_groups
    else:
        groups = current["qi_groups"]

    direct_columns = {column for column, roles in merged_roles.items() if "direct_identifier" in roles}
    identifier_columns = {column for column, value in merged_types.items() if value == "identifier"}
    for group in groups:
        attributes = set(group["attributes"])
        overlap = sorted(attributes & (direct_columns | identifier_columns))
        if overlap:
            raise ValueError("QI-группа содержит прямые или идентификатороподобные атрибуты: " + ", ".join(overlap))

    hierarchy_updates = updates.get("hierarchy_updates")
    normalized_hierarchies = None
    if hierarchy_updates is not None:
        if not isinstance(hierarchy_updates, dict):
            raise ValueError("hierarchy_updates должен быть объектом столбец → список уровней.")
        normalized_hierarchies = {}
        total_entries = 0
        for column, levels in hierarchy_updates.items():
            if not isinstance(column, str) or column not in available:
                raise ValueError(f"Столбец «{column}» отсутствует в CSV.")
            if levels in (None, []):
                normalized_hierarchies[column] = None
                continue
            if not isinstance(levels, list) or not levels or len(levels) > 10:
                raise ValueError(f"Иерархия «{column}» должна содержать от 1 до 10 уровней.")

            actual_categories = set(session.source_dataframe[column].dropna().astype(str).unique())
            previous_values = actual_categories
            normalized_levels = []
            for index, level in enumerate(levels, start=1):
                if not isinstance(level, dict) or not level:
                    raise ValueError(f"Уровень {index} иерархии «{column}» пуст или повреждён.")
                if any(
                    not isinstance(key, str) or not key or len(key) > 300
                    or not isinstance(value, str) or not value.strip() or len(value) > 300
                    for key, value in level.items()
                ):
                    raise ValueError(f"Уровень {index} иерархии «{column}» содержит некорректные значения.")
                total_entries += len(level)
                if total_entries > 100_000:
                    raise ValueError("Суммарный размер иерархий превышает 100 000 соответствий.")
                keys = set(level)
                if not keys.issubset(previous_values):
                    raise ValueError(f"Уровень {index} иерархии «{column}» содержит неизвестные категории предыдущего уровня.")
                values = set(level.values())
                previous_values = values
                normalized_levels.append(dict(level))
            normalized_hierarchies[column] = normalized_levels

    return {
        "role_overrides": merged_roles,
        "semantic_types": merged_types,
        "quasi_identifier_groups": groups,
        "hierarchy_updates": normalized_hierarchies,
    }, current


def preview_profile_changes(
    registry: DatasetRegistry,
    store: PendingActionStore,
    dataset_id: str,
    updates: dict[str, Any],
    profile_path: str = str(DEFAULT_PROFILE_PATH),
) -> dict[str, Any]:
    try:
        session = registry.get_active_session(dataset_id)
        normalized, current = _validate_profile_updates(session, updates, profile_path)
        diff: dict[str, Any] = {}
        if "role_updates" in updates:
            diff["roles_after"] = normalized["role_overrides"]
        if "semantic_type_updates" in updates:
            diff["semantic_types_after"] = normalized["semantic_types"]
        if "qi_groups" in updates:
            diff["qi_groups_after"] = normalized["quasi_identifier_groups"]
        if "hierarchy_updates" in updates:
            diff["hierarchies_after"] = {
                column: (None if levels is None else [
                    {"level": index, "mapping_count": len(level), "generalized_value_count": len(set(level.values()))}
                    for index, level in enumerate(levels, start=1)
                ]) for column, levels in normalized["hierarchy_updates"].items()
            }
        # Never include actual category-to-category mappings in the diff sent to the model.
        local_diff = {
            "roles_after": normalized["role_overrides"] if "role_updates" in updates else None,
            "semantic_types_after": normalized["semantic_types"] if "semantic_type_updates" in updates else None,
            "qi_groups_after": normalized["quasi_identifier_groups"] if "qi_groups" in updates else None,
            "hierarchies_after": normalized["hierarchy_updates"] if "hierarchy_updates" in updates else None,
        }
        safe_diff = {
            key: value for key, value in diff.items()
        }
        pending = store.create(
            dataset_id=dataset_id,
            session_id=session.session_id,
            payload=normalized,
            profile_digest=profile_digest(current),
        )
        return {
            "ok": True,
            "change_id": pending["action_id"],
            "approval_token": pending["approval_token"],
            "diff": safe_diff,
            "local_diff": local_diff,
            "requires_local_confirmation": True,
            "warning": "Изменения сохраняются только после отдельного подтверждения в консоли Host.",
        }
    except LookupError:
        return {"ok": False, "error_code": "dataset_not_open", "message": "Сначала откройте CSV."}
    except (OSError, ValueError, TypeError) as error:
        return {"ok": False, "error_code": "invalid_profile_changes", "message": str(error)}


def apply_profile_changes(
    registry: DatasetRegistry,
    store: PendingActionStore,
    dataset_id: str,
    change_id: str,
    approval_token: str,
    profile_path: str = str(DEFAULT_PROFILE_PATH),
) -> dict[str, Any]:
    try:
        session = registry.get_active_session(dataset_id)
        current = _profile_snapshot(session, profile_path)
        payload = store.consume(
            change_id,
            approval_token,
            dataset_id=dataset_id,
            session_id=session.session_id,
            profile_digest=profile_digest(current),
        )
        save_profile_bundle(
            session.source_path,
            role_overrides=payload["role_overrides"],
            semantic_types=payload["semantic_types"],
            quasi_identifier_groups=payload["quasi_identifier_groups"],
            hierarchy_updates=payload["hierarchy_updates"],
            available_columns=set(map(str, session.source_dataframe.columns)),
            profile_path=profile_path,
        )
        return {"ok": True, "dataset_id": dataset_id, "message": "Профиль сохранён.", "reopen_required": False}
    except LookupError:
        return {"ok": False, "error_code": "dataset_not_open", "message": "Исходный CSV изменился или сессия закрыта."}
    except PermissionError:
        return {"ok": False, "error_code": "approval_invalid", "message": "Подтверждение недействительно."}
    except (OSError, ValueError, TypeError) as error:
        return {"ok": False, "error_code": "profile_save_failed", "message": "Не удалось сохранить профиль. Проверьте структуру изменений."}
