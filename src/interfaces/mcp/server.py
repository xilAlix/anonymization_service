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
from interfaces.mcp.action_store import PendingActionStore  # noqa: E402
from interfaces.mcp.profile_tools import (  # noqa: E402
    apply_profile_changes as apply_profile_changes_operation,
    get_category_values_tool,
    get_dataset_profile,
    preview_profile_changes as preview_profile_changes_operation,
    suggest_attribute_roles as suggest_attribute_roles_operation,
    suggest_qi_groups_tool,
    suggest_semantic_types_tool,
)
from interfaces.mcp.analysis_tools import (  # noqa: E402
    analyze_anonymized_result as analyze_anonymized_result_operation,
    analyze_dataset as analyze_dataset_operation,
    get_privacy_result as get_privacy_result_operation,
    get_utility_result as get_utility_result_operation,
)
from interfaces.mcp.anonymization_tools import (  # noqa: E402
    execute_anonymization as execute_anonymization_operation,
    prepare_anonymization_plan as prepare_anonymization_plan_operation,
)


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
    """Создаёт MCP Server v2 и регистрирует инструменты AI Host."""
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
        description="Локальные инструменты изучения CSV, управления профилями, аналитики и анонимизации для GigaChat AI Host.",
        instructions=SERVER_INSTRUCTIONS,
        version="0.6.1",
    )

    pending_actions = PendingActionStore()

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

    @mcp_server.tool()
    def suggest_attribute_roles(dataset_id: str) -> dict[str, Any]:
        """Возвращает локальные предложения ролей без передачи примеров значений."""
        return suggest_attribute_roles_operation(registry, dataset_id)

    @mcp_server.tool()
    def suggest_semantic_types(dataset_id: str) -> dict[str, Any]:
        """Возвращает назначенные и предложенные семантические типы атрибутов."""
        return suggest_semantic_types_tool(registry, dataset_id)

    @mcp_server.tool()
    def suggest_qi_groups(dataset_id: str) -> dict[str, Any]:
        """Возвращает локальные предложения QI-групп без строк данных."""
        return suggest_qi_groups_tool(registry, dataset_id)

    @mcp_server.tool()
    def get_dataset_profile(dataset_id: str) -> dict[str, Any]:
        """Возвращает ручные роли, семантические типы, QI-группы и безопасную сводку иерархий."""
        return get_dataset_profile(registry, dataset_id)

    @mcp_server.tool()
    def get_category_values(dataset_id: str, column: str, minimum_frequency: int = 5) -> dict[str, Any]:
        """Возвращает частые категории одного столбца; Host обязан запросить отдельное согласие на передачу названий."""
        return get_category_values_tool(registry, dataset_id, column, minimum_frequency)

    @mcp_server.tool()
    def preview_profile_changes(dataset_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        """Проверяет и показывает изменения ролей, типов, QI-групп и иерархий без записи."""
        return preview_profile_changes_operation(registry, pending_actions, dataset_id, updates)

    @mcp_server.tool()
    def apply_profile_changes(dataset_id: str, change_id: str, approval_token: str) -> dict[str, Any]:
        """Сохраняет подготовленный профиль только с одноразовым токеном, который выдаёт локальный Host после подтверждения."""
        return apply_profile_changes_operation(registry, pending_actions, dataset_id, change_id, approval_token)

    @mcp_server.tool()
    def analyze_dataset(dataset_id: str) -> dict[str, Any]:
        """Запускает существующий статистический анализ; возвращает только агрегаты с подавлением малых групп."""
        return analyze_dataset_operation(registry, dataset_id)

    @mcp_server.tool()
    def prepare_anonymization_plan(
        dataset_id: str,
        operations: list[str],
        default_k: int = 5,
        representative: str = "mean",
        enable_l_diversity: bool = True,
        default_l: int = 2,
        l_variant: str = "both",
    ) -> dict[str, Any]:
        """Подготавливает план существующей анонимизации без выполнения и сохранения файла."""
        return prepare_anonymization_plan_operation(
            registry, pending_actions, dataset_id, operations, default_k,
            representative, enable_l_diversity, default_l, l_variant,
        )

    @mcp_server.tool()
    def execute_anonymization(
        dataset_id: str,
        plan_id: str,
        approval_token: str,
        destination: str,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        """Выполняет ранее подготовленный план только после локального подтверждения Host."""
        return execute_anonymization_operation(
            registry, pending_actions, dataset_id, plan_id, approval_token,
            destination, overwrite,
        )

    @mcp_server.tool()
    def get_privacy_result(dataset_id: str) -> dict[str, Any]:
        """Возвращает безопасный статус Privacy Release Check без подробностей заблокированного выпуска."""
        return get_privacy_result_operation(registry, dataset_id)

    @mcp_server.tool()
    def get_utility_result(dataset_id: str) -> dict[str, Any]:
        """Возвращает агрегированную оценку полезности с фильтрацией малых групп."""
        return get_utility_result_operation(registry, dataset_id)

    @mcp_server.tool()
    def analyze_anonymized_result(dataset_id: str) -> dict[str, Any]:
        """Запускает существующий анализ уже созданного результата анонимизации."""
        return analyze_anonymized_result_operation(registry, dataset_id)

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
        description="Локальный MCP Server сервиса анонимизации версии 0.6.1."
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
