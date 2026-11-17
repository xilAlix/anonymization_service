from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def build_server_parameters(workspace: str | Path):
    try:
        from mcp import StdioServerParameters
    except ImportError as error:
        raise RuntimeError("MCP Python SDK 2.x не установлен. Установите requirements.txt.") from error

    child_env = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": str(PROJECT_ROOT / "src"),
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
        "ANONYMIZATION_WORKSPACE": str(Path(workspace).resolve()),
    }
    for key in (
        "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "APPDATA", "LOCALAPPDATA",
        "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "PATHEXT", "PROCESSOR_ARCHITECTURE",
    ):
        if os.environ.get(key):
            child_env[key] = os.environ[key]
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "interfaces.mcp.server", "--workspace", str(Path(workspace).resolve())],
        env=child_env,
        cwd=str(PROJECT_ROOT),
    )


def connect_mcp(workspace: str | Path):
    try:
        from mcp import Client
    except ImportError as error:
        raise RuntimeError("MCP Python SDK 2.x не установлен. Установите requirements.txt.") from error
    return Client(build_server_parameters(workspace))


def get_tool_items(list_tools_result: Any) -> list[Any]:
    tools = getattr(list_tools_result, "tools", None)
    if tools is None and isinstance(list_tools_result, dict):
        tools = list_tools_result.get("tools", [])
    return list(tools or [])


def mcp_result_to_json(result: Any) -> dict[str, Any]:
    structured = getattr(result, "structured_content", None)
    if structured is None:
        structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict):
        return structured
    content = getattr(result, "content", None) or []
    for item in content:
        text_value = getattr(item, "text", None)
        if text_value:
            import json
            try:
                parsed = json.loads(text_value)
                if isinstance(parsed, dict):
                    return parsed
                return {"ok": True, "result": parsed}
            except json.JSONDecodeError:
                return {"ok": False, "error_code": "invalid_tool_response", "message": text_value[:2000]}
    return {
        "ok": not bool(getattr(result, "is_error", False)),
        "content": [],
    }
