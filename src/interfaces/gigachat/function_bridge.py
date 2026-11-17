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


def _clean_schema(schema: Any) -> dict[str, Any]:
    value = _plain(schema)
    if not isinstance(value, dict):
        value = {"type": "object", "properties": {}, "required": []}
    value = json.loads(json.dumps(value, ensure_ascii=False, default=str))
    properties = value.get("properties")
    if isinstance(properties, dict):
        for name in HIDDEN_ARGUMENTS:
            properties.pop(name, None)
    required = value.get("required")
    if isinstance(required, list):
        value["required"] = [item for item in required if item not in HIDDEN_ARGUMENTS]
    value.setdefault("type", "object")
    value.setdefault("properties", {})
    return value


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
        functions.append({
            "name": name,
            "description": (description or f"Инструмент сервиса анонимизации: {name}")[:1000],
            "parameters": _clean_schema(schema),
        })
    return functions


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
