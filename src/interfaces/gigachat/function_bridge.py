from __future__ import annotations

import json
from typing import Any


HIDDEN_ARGUMENTS = {"approval_token"}
SENSITIVE_RESULT_KEYS = {
    "approval_token", "local_diff", "profile_digest", "source_rows", "source_dataframe",
    "sample_values", "raw_values", "token_mapping", "token_map",
}


def _plain(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(by_alias=True, exclude_none=True)
    if hasattr(value, "dict"):
        return value.dict(by_alias=True, exclude_none=True)
    return value


def _normalize_schema_node(node: Any) -> Any:
    """Нормализует вложенную JSON Schema под формат GigaChat Function Calling.

    GigaChat требует properties у каждого object-схемного узла. В JSON Schema
    для динамических словарей (например, dict[str, Any]) допустим только
    additionalProperties, но GigaChat отклоняет такой узел без properties.
    Пустой properties сохраняет возможность произвольных ключей.
    """
    if isinstance(node, list):
        return [_normalize_schema_node(item) for item in node]
    if not isinstance(node, dict):
        return node

    normalized = {key: _normalize_schema_node(value) for key, value in node.items()}
    node_type = normalized.get("type")
    is_object = node_type == "object" or "properties" in normalized or "additionalProperties" in normalized
    if is_object:
        normalized.setdefault("type", "object")
        properties = normalized.get("properties")
        if not isinstance(properties, dict):
            normalized["properties"] = {}
    return normalized


def _remove_hidden_arguments(schema: dict[str, Any]) -> dict[str, Any]:
    """Удаляет локальные approval-токены на любой глубине схемы."""
    properties = schema.get("properties")
    if isinstance(properties, dict):
        for name in HIDDEN_ARGUMENTS:
            properties.pop(name, None)
        for child in properties.values():
            if isinstance(child, dict):
                _remove_hidden_arguments(child)
    required = schema.get("required")
    if isinstance(required, list):
        schema["required"] = [name for name in required if name not in HIDDEN_ARGUMENTS]
    items = schema.get("items")
    if isinstance(items, dict):
        _remove_hidden_arguments(items)
    additional = schema.get("additionalProperties")
    if isinstance(additional, dict):
        _remove_hidden_arguments(additional)
    for keyword in ("anyOf", "oneOf", "allOf"):
        branches = schema.get(keyword)
        if isinstance(branches, list):
            for branch in branches:
                if isinstance(branch, dict):
                    _remove_hidden_arguments(branch)
    return schema


def _clean_schema(schema: Any) -> dict[str, Any]:
    value = _plain(schema)
    if not isinstance(value, dict):
        value = {"type": "object", "properties": {}, "required": []}
    value = json.loads(json.dumps(value, ensure_ascii=False, default=str))
    value = _normalize_schema_node(value)
    if not isinstance(value, dict):
        value = {"type": "object", "properties": {}, "required": []}
    value.setdefault("type", "object")
    value.setdefault("properties", {})
    return _remove_hidden_arguments(value)


def validate_gigachat_functions(functions: list[dict[str, Any]]) -> None:
    """Выполняет локальную проверку function definitions перед сетевым запросом."""
    import re

    if not isinstance(functions, list) or not functions:
        raise ValueError("Для GigaChat не переданы пользовательские функции.")
    seen_names: set[str] = set()
    for function in functions:
        name = function.get("name")
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", name):
            raise ValueError("Обнаружено недопустимое имя функции GigaChat.")
        if name in seen_names:
            raise ValueError(f"Функция GigaChat {name!r} зарегистрирована более одного раза.")
        seen_names.add(name)
        parameters = function.get("parameters")
        if not isinstance(parameters, dict) or parameters.get("type") != "object":
            raise ValueError(f"У функции {name!r} параметры должны иметь тип object.")
        properties = parameters.get("properties")
        if not isinstance(properties, dict):
            raise ValueError(f"У функции {name!r} отсутствует объект parameters.properties.")
        _validate_schema_node(parameters, f"{name}.parameters")


def _validate_schema_node(schema: Any, location: str) -> None:
    if not isinstance(schema, dict):
        raise ValueError(f"Некорректная JSON Schema в {location}.")
    schema_type = schema.get("type")
    if schema_type == "object":
        properties = schema.get("properties")
        if not isinstance(properties, dict):
            raise ValueError(f"В {location}.properties должен быть JSON-объект.")
        required = schema.get("required", [])
        if not isinstance(required, list) or any(name not in properties for name in required):
            raise ValueError(f"В {location}.required указаны отсутствующие свойства.")
        for name, child in properties.items():
            _validate_schema_node(child, f"{location}.properties.{name}")
        additional = schema.get("additionalProperties")
        if isinstance(additional, dict):
            _validate_schema_node(additional, f"{location}.additionalProperties")
    elif schema_type == "array":
        if "items" not in schema:
            raise ValueError(f"В {location} для массива не задан items.")
        _validate_schema_node(schema["items"], f"{location}.items")
    for keyword in ("anyOf", "oneOf", "allOf"):
        branches = schema.get(keyword)
        if branches is not None:
            if not isinstance(branches, list):
                raise ValueError(f"В {location}.{keyword} ожидается список схем.")
            for index, branch in enumerate(branches):
                _validate_schema_node(branch, f"{location}.{keyword}[{index}]")


def _apply_gigachat_function_hints(name: str, parameters: dict[str, Any]) -> None:
    """Добавляет ограничения, которые известны прикладному API, но не выводятся из Python-аннотаций."""
    properties = parameters.get("properties")
    if not isinstance(properties, dict):
        return

    if name == "get_category_values":
        threshold = properties.get("minimum_frequency")
        if isinstance(threshold, dict):
            threshold.setdefault("minimum", 5)

    if name == "prepare_anonymization_plan":
        operations = properties.get("operations")
        if isinstance(operations, dict):
            operations.setdefault("minItems", 1)
            operations.setdefault("uniqueItems", True)
            items = operations.get("items")
            if isinstance(items, dict):
                items.setdefault("enum", [
                    "tokenize_direct_identifiers",
                    "remove_direct_identifiers",
                    "k_anonymity",
                ])
                items.setdefault("description", "Операция; токенизация и удаление прямых идентификаторов взаимоисключающие.")
        default_k = properties.get("default_k")
        if isinstance(default_k, dict):
            default_k.setdefault("minimum", 2)
        default_l = properties.get("default_l")
        if isinstance(default_l, dict):
            default_l.setdefault("minimum", 2)
        representative = properties.get("representative")
        if isinstance(representative, dict):
            representative.setdefault("enum", ["mean", "median", "medoid"])
        l_variant = properties.get("l_variant")
        if isinstance(l_variant, dict):
            l_variant.setdefault("enum", ["distinct", "entropy", "both"])
        default_t = properties.get("default_t")
        if isinstance(default_t, dict):
            default_t.setdefault("minimum", 0)
            default_t.setdefault("maximum", 1)
        properties["operations"].setdefault("description", "Список операций; выбери ровно один способ обработки прямых идентификаторов.")

    if name == "preview_profile_changes":
        updates = properties.get("updates")
        if isinstance(updates, dict):
            # MCP-интерфейс принимает словари с именами столбцов в ключах, но
            # GigaChat надёжнее валидирует явные массивы типизированных записей.
            # conversation.py преобразует эти записи обратно в локальный формат.
            role_item = {
                "type": "object",
                "properties": {
                    "column": {"type": "string", "minLength": 1},
                    "roles": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": [
                                "direct_identifier",
                                "quasi_identifier",
                                "sensitive_attribute",
                                "analytical_attribute",
                            ],
                        },
                    },
                },
                "required": ["column", "roles"],
            }
            semantic_type_item = {
                "type": "object",
                "properties": {
                    "column": {"type": "string", "minLength": 1},
                    "semantic_type": {
                        "type": "string",
                        "enum": ["auto", "numeric", "categorical", "datetime", "identifier"],
                    },
                },
                "required": ["column", "semantic_type"],
            }
            mapping_item = {
                "type": "object",
                "properties": {
                    "value": {"type": "string", "minLength": 1},
                    "generalized_value": {"type": "string", "minLength": 1},
                },
                "required": ["value", "generalized_value"],
            }
            hierarchy_level_item = {
                "type": "object",
                "properties": {
                    "mappings": {"type": "array", "items": mapping_item},
                },
                "required": ["mappings"],
            }
            hierarchy_item = {
                "type": "object",
                "properties": {
                    "column": {"type": "string", "minLength": 1},
                    "levels": {"type": "array", "items": hierarchy_level_item, "maxItems": 10},
                },
                "required": ["column", "levels"],
            }
            qi_group_item = {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "name": {"type": "string", "minLength": 1},
                    "attributes": {"type": "array", "items": {"type": "string"}, "minItems": 1, "uniqueItems": True},
                    "description": {"type": "string"},
                    "active": {"type": "boolean"},
                    "k_override": {"type": "integer", "minimum": 2},
                },
                "required": ["name", "attributes"],
            }
            updates["type"] = "object"
            updates["properties"] = {
                "role_updates": {
                    "type": "array",
                    "description": "Изменения ролей: список записей column + roles. Пустой roles снимает ручные роли столбца.",
                    "items": role_item,
                },
                "semantic_type_updates": {
                    "type": "array",
                    "description": "Изменения семантических типов: список записей column + semantic_type.",
                    "items": semantic_type_item,
                },
                "qi_groups": {
                    "type": "array",
                    "description": "Полный новый список QI-групп; раздел заменяет прежний список целиком.",
                    "items": qi_group_item,
                },
                "hierarchy_updates": {
                    "type": "array",
                    "description": "Иерархии категорий: column → levels → mappings; каждый mapping содержит value и generalized_value.",
                    "items": hierarchy_item,
                },
            }
            updates.pop("additionalProperties", None)
            updates.pop("default", None)
            updates.setdefault(
                "description",
                "Объект обновлений профиля. Передавай role_updates, semantic_type_updates и hierarchy_updates "
                "как массивы объектов с явными полями, а не словари с динамическими именами столбцов.",
            )


def build_gigachat_functions(mcp_tools: list[Any]) -> list[dict[str, Any]]:
    """Converts MCP Tool definitions to GigaChat custom-function format."""
    functions = []
    for tool in mcp_tools:
        name = getattr(tool, "name", None)
        if not name and isinstance(tool, dict):
            name = tool.get("name")
        description = getattr(tool, "description", None)
        schema = getattr(tool, "inputSchema", None)
        if schema is None:
            schema = getattr(tool, "input_schema", None)
        if isinstance(tool, dict):
            description = description or tool.get("description")
            schema = schema or tool.get("inputSchema") or tool.get("input_schema")
        if not isinstance(name, str) or not name:
            continue
        parameters = _clean_schema(schema)
        _apply_gigachat_function_hints(name, parameters)
        functions.append({
            "name": name,
            "description": (description or f"Инструмент сервиса анонимизации: {name}")[:1000],
            "parameters": parameters,
        })
    validate_gigachat_functions(functions)
    return functions


def normalize_gigachat_arguments(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Преобразует безопасные явные DTO GigaChat в формат локального MCP-инструмента."""
    if name != "preview_profile_changes":
        return dict(arguments)

    normalized_arguments = dict(arguments)
    updates = arguments.get("updates")
    if updates is None:
        return normalized_arguments
    if not isinstance(updates, dict):
        raise ValueError("updates должен быть объектом.")

    normalized_updates = dict(updates)

    def entries_to_mapping(value: Any, value_key: str, *, transform=None, section: str) -> Any:
        if value is None or isinstance(value, dict):
            # Совместимость с ранними клиентами; локальный валидатор профиля
            # всё равно проверит названия столбцов и допустимые значения.
            return value
        if not isinstance(value, list):
            raise ValueError(f"{section} должен быть массивом записей.")
        result: dict[str, Any] = {}
        for index, entry in enumerate(value, start=1):
            if not isinstance(entry, dict):
                raise ValueError(f"Запись {index} в {section} должна быть объектом.")
            column = entry.get("column")
            if not isinstance(column, str) or not column.strip():
                raise ValueError(f"В записи {index} раздела {section} не указан column.")
            if column in result:
                raise ValueError(f"Столбец {column!r} повторяется в разделе {section}.")
            raw_value = entry.get(value_key)
            result[column] = transform(raw_value) if transform else raw_value
        return result

    if "role_updates" in normalized_updates:
        normalized_updates["role_updates"] = entries_to_mapping(
            normalized_updates["role_updates"], "roles", section="role_updates"
        )
    if "semantic_type_updates" in normalized_updates:
        normalized_updates["semantic_type_updates"] = entries_to_mapping(
            normalized_updates["semantic_type_updates"], "semantic_type", section="semantic_type_updates"
        )
    if "hierarchy_updates" in normalized_updates:
        def convert_levels(levels: Any) -> Any:
            if levels is None:
                return None
            if not isinstance(levels, list):
                raise ValueError("levels должен быть массивом уровней.")
            converted_levels = []
            for level_index, level in enumerate(levels, start=1):
                if not isinstance(level, dict) or not isinstance(level.get("mappings"), list):
                    raise ValueError(f"Уровень {level_index} должен содержать массив mappings.")
                mapping: dict[str, str] = {}
                for mapping_index, pair in enumerate(level["mappings"], start=1):
                    if not isinstance(pair, dict):
                        raise ValueError(f"Связь {mapping_index} уровня {level_index} должна быть объектом.")
                    source = pair.get("value")
                    target = pair.get("generalized_value")
                    if not isinstance(source, str) or not isinstance(target, str):
                        raise ValueError(f"Связь {mapping_index} уровня {level_index} содержит некорректные значения.")
                    if source in mapping:
                        raise ValueError(f"Категория {source!r} повторяется на уровне {level_index}.")
                    mapping[source] = target
                converted_levels.append(mapping)
            return converted_levels

        normalized_updates["hierarchy_updates"] = entries_to_mapping(
            normalized_updates["hierarchy_updates"], "levels", transform=convert_levels,
            section="hierarchy_updates",
        )

    normalized_arguments["updates"] = normalized_updates
    return normalized_arguments


def parse_function_call(message: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    call = message.get("function_call")
    if not isinstance(call, dict):
        return None
    name = call.get("name")
    arguments = call.get("arguments", {})
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError as error:
            raise ValueError("GigaChat вернул некорректные аргументы функции.") from error
    if not isinstance(name, str) or not name:
        raise ValueError("GigaChat вернул вызов функции без имени.")
    if not isinstance(arguments, dict):
        raise ValueError("Аргументы функции должны быть JSON-объектом.")
    return name, arguments


def sanitize_tool_result(value: Any) -> Any:
    """Removes local confirmation capabilities and source-value payloads recursively."""
    if isinstance(value, dict):
        return {
            key: sanitize_tool_result(item)
            for key, item in value.items()
            if key not in SENSITIVE_RESULT_KEYS
        }
    if isinstance(value, list):
        return [sanitize_tool_result(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_tool_result(item) for item in value]
    return value


def json_for_function_result(value: Any) -> str:
    return json.dumps(sanitize_tool_result(value), ensure_ascii=False, separators=(",", ":"), default=str)
