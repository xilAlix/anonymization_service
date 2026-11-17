from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SRC_DIRECTORY = PROJECT_ROOT / "src"
if str(SRC_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SRC_DIRECTORY))

from interfaces.mcp.dataset_tools import (  # noqa: E402
    inspect_dataset as inspect_dataset_tool,
    list_datasets as list_datasets_tool,
    open_dataset as open_dataset_tool,
)
from interfaces.mcp.registry import DatasetRegistry  # noqa: E402


SERVER_INSTRUCTIONS = (
    "Локальный MCP-сервер сервиса анонимизации. Доступны только CSV в настроенной "
    "рабочей папке. Исходные строки и примеры значений не возвращаются инструментами. "
    "Сначала вызовите list_datasets, затем open_dataset и inspect_dataset."
)

RESOURCE_CONTENT = {
    "anonymization://capabilities": {
        "name": "Возможности сервиса",
        "content": "Сервис обрабатывает табличные CSV. Доступны локальное открытие и осмотр структуры набора. Алгоритмы анонимизации и статистического анализа уже реализованы в основном приложении и не переписываются MCP-слоем.",
    },
    "anonymization://attribute-roles": {
        "name": "Роли атрибутов",
        "content": "direct_identifier — прямой идентификатор; quasi_identifier — квази-идентификатор; sensitive_attribute — конфиденциальный атрибут; analytical_attribute — аналитический атрибут. Автоматические предложения являются эвристиками и требуют проверки.",
    },
    "anonymization://semantic-types": {
        "name": "Семантические типы",
        "content": "auto — автоматическая подсказка; numeric — числовой; categorical — категориальный; datetime — дата и время; identifier — идентификатороподобный. Семантический тип не заменяет роль приватности.",
    },
    "anonymization://privacy-methods": {
        "name": "Методы приватности",
        "content": "Сервис реализует токенизацию, удаление прямых идентификаторов, k-анонимизацию и проверку l-разнообразия (Distinct, Entropy, Both). Токенизация является псевдонимизацией. Статус проверки не является абсолютной гарантией анонимности.",
    },
    "anonymization://workflow": {
        "name": "Порядок обработки",
        "content": "Рекомендуемый процесс: изучение CSV и профиля; подтверждение ролей и QI-групп; подготовка плана; подтверждение пользователя; выполнение существующих операций; локальная проверка приватности и оценка полезности.",
    },
}


def create_server(registry: DatasetRegistry):
    """Создаёт MCP Server v2 и регистрирует локальные инструменты первого этапа."""
    try:
        from mcp.server import MCPServer
    except ImportError as error:
        raise RuntimeError(
            "Не установлен MCP Python SDK. Выполните: "
            "python -m pip install -r requirements.txt"
        ) from error

    mcp_server = MCPServer(
        "anonymization-service",
        title="Сервис анонимизации",
        description="Локальные инструменты изучения CSV для последующего AI Host.",
        instructions=SERVER_INSTRUCTIONS,
        version="0.6.0-dev.1",
    )

    @mcp_server.tool()
    def list_datasets() -> dict[str, Any]:
        """Перечисляет CSV в корне разрешённой рабочей папки без выдачи абсолютных путей."""
        return list_datasets_tool(registry)

    @mcp_server.tool()
    def open_dataset(dataset_id: str) -> dict[str, Any]:
        """Открывает CSV по dataset_id, ранее выданному инструментом list_datasets."""
        return open_dataset_tool(registry, dataset_id)

    @mcp_server.tool()
    def inspect_dataset(dataset_id: str) -> dict[str, Any]:
        """Возвращает схему, типы, счётчики, предложения ролей и потенциальные QI-группы без строк данных."""
        return inspect_dataset_tool(registry, dataset_id)

    for uri, resource in RESOURCE_CONTENT.items():
        def make_resource_handler(payload: dict[str, str]):
            def read_resource() -> str:
                return json.dumps(payload, ensure_ascii=False)

            return read_resource

        handler = make_resource_handler(resource)
        handler.__name__ = "resource_" + uri.removeprefix("anonymization://").replace("-", "_")
        mcp_server.resource(uri)(handler)

    return mcp_server


def _resolve_workspace(argument: str | None) -> Path:
    configured = argument or os.environ.get("ANONYMIZATION_WORKSPACE")
    return Path(configured).expanduser() if configured else Path.cwd()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Локальный MCP Server сервиса анонимизации (этап 1 версии 0.6.0)."
    )
    parser.add_argument(
        "--workspace",
        help="Разрешённая папка с CSV. Также можно задать ANONYMIZATION_WORKSPACE.",
    )
    args = parser.parse_args(argv)

    try:
        registry = DatasetRegistry(_resolve_workspace(args.workspace))
        mcp_server = create_server(registry)
    except (OSError, ValueError, RuntimeError) as error:
        logging.basicConfig(stream=sys.stderr, level=logging.ERROR)
        logging.error("MCP Server не запущен: %s", error)
        return 2

    # Для STDIO stdout является каналом JSON-RPC: диагностические сообщения идут в stderr.
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
    mcp_server.run()
    return 0


# Переменная mcp нужна официальной команде `mcp dev` для обнаружения сервера.
# Рабочая папка задаётся через ANONYMIZATION_WORKSPACE до запуска Inspector.
if __name__ != "__main__":
    try:
        mcp = create_server(DatasetRegistry(_resolve_workspace(None)))
    except (ImportError, OSError, ValueError, RuntimeError):
        mcp = None
else:
    mcp = None


if __name__ == "__main__":
    raise SystemExit(main())
