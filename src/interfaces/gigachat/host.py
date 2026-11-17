from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SRC_DIRECTORY = PROJECT_ROOT / "src"
if str(SRC_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SRC_DIRECTORY))

from interfaces.gigachat.config import (  # noqa: E402
    AssistantConfig,
    CredentialStore,
    load_config,
    save_config,
)
from interfaces.gigachat.conversation import GigaChatConversation  # noqa: E402
from interfaces.gigachat.gigachat_client import GigaChatAPIError, GigaChatClient  # noqa: E402
from interfaces.gigachat.mcp_client import connect_mcp  # noqa: E402


def _resolve_workspace(value: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.exists() or not path.is_dir():
        raise ValueError("Рабочая папка не найдена или не является каталогом.")
    return path


def _ask_workspace(default: str = "") -> Path:
    while True:
        prompt = f"Папка с CSV [{default}]: " if default else "Папка с CSV: "
        entered = input(prompt).strip().strip('"')
        chosen = entered or default
        if not chosen:
            print("Укажи папку, в которой лежат CSV-файлы.")
            continue
        try:
            return _resolve_workspace(chosen)
        except ValueError as error:
            print(error)


def _get_authorization_key(store: CredentialStore, allow_store: bool = True) -> str:
    try:
        existing = store.get()
    except ValueError:
        existing = None
    if existing:
        from interfaces.gigachat.config import _normalize_auth_key
        return _normalize_auth_key(existing)
    print("\nДля подключения нужен GigaChat Authorization key.")
    print("Ключ можно взять в кабинете GigaChat API. Он не будет записан в файлы проекта.")
    entered = getpass.getpass("Authorization key (ввод скрыт): ").strip()
    if not entered:
        raise ValueError("Authorization key не указан.")
    if allow_store:
        remember = input("Сохранить ключ в защищённом хранилище Windows? [Да/н]: ").strip().casefold()
        if remember in {"", "да", "д", "y", "yes"}:
            if store.set(entered):
                print("Ключ сохранён в системном хранилище учётных данных.")
            else:
                print("Не удалось использовать системное хранилище. Ключ будет действовать только в этом запуске.")
    from interfaces.gigachat.config import _normalize_auth_key
    return _normalize_auth_key(entered)


def _print_help() -> None:
    print("""
Команды консоли:
  /help       показать команды
  /files      локально перечислить CSV без передачи списка GigaChat
  /open NAME  локально открыть CSV по имени или номеру из /files
  /workspace  показать рабочую папку
  /privacy    показать и изменить согласия на передачу метаданных/агрегатов
  /clear      очистить историю текущего диалога
  /exit       завершить работу

Обычный текст отправляется GigaChat. Исходные строки CSV не передаются модели.
""".strip())


async def _run_chat(workspace: Path, config: AssistantConfig, api_key: str) -> int:
    mcp_context = connect_mcp(workspace)
    async with mcp_context as mcp_client:
        giga = GigaChatClient(
            authorization_key=api_key,
            scope=config.gigachat_scope,
            model=config.gigachat_model,
        )
        conversation = GigaChatConversation(
            giga,
            mcp_client,
            workspace,
        )
        await conversation.initialize()
        print("\nПодключение готово.")
        print(f"Рабочая папка: {workspace}")
        print(f"GigaChat: {config.gigachat_model}")
        print(f"MCP-инструментов: {len(conversation.functions)}")
        print("Введи /help для списка команд.")
        print("Важно: текст твоих сообщений отправляется в GigaChat. Не вводи ФИО, email, телефоны и исходные значения CSV.\n")

        local_file_list: list[dict] = []
        while True:
            try:
                text = input("ты> ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nЗавершение работы.")
                break
            if not text:
                continue
            command = text.casefold()
            if command in {"/exit", "/quit", "/выход"}:
                break
            if command == "/help":
                _print_help()
                continue
            if command == "/workspace":
                print(f"Рабочая папка: {workspace}")
                continue
            if command == "/files":
                result = await mcp_client.call_tool("list_datasets", {})
                from interfaces.gigachat.mcp_client import mcp_result_to_json
                payload = mcp_result_to_json(result)
                if payload.get("ok"):
                    local_file_list = payload.get("datasets", [])
                    print("\nCSV в рабочей папке (локально, без передачи GigaChat):")
                    for index, item in enumerate(local_file_list, start=1):
                        print(f"  {index}. {item.get('name')}  ({item.get('size_bytes')} байт)")
                    print("Выбери набор командой /open <номер или точное имя>.")
                else:
                    print(payload.get("message", "Не удалось получить список CSV."))
                continue
            if command.startswith("/open "):
                selector = text[6:].strip().strip('"')
                if not local_file_list:
                    result = await mcp_client.call_tool("list_datasets", {})
                    from interfaces.gigachat.mcp_client import mcp_result_to_json
                    local_file_list = mcp_result_to_json(result).get("datasets", [])
                selected = None
                if selector.isdigit():
                    index = int(selector) - 1
                    if 0 <= index < len(local_file_list):
                        selected = local_file_list[index]
                else:
                    matches = [item for item in local_file_list if str(item.get("name", "")).casefold() == selector.casefold()]
                    if len(matches) == 1:
                        selected = matches[0]
                    elif len(matches) > 1:
                        print("Имя неоднозначно. Выбери CSV по номеру через /files.")
                        continue
                if not selected:
                    print("Файл не найден. Выполни /files и выбери номер или точное имя.")
                    continue
                result = await mcp_client.call_tool("open_dataset", {"dataset_id": selected["dataset_id"]})
                from interfaces.gigachat.mcp_client import mcp_result_to_json
                opened = mcp_result_to_json(result)
                if opened.get("ok"):
                    dataset_id = str(opened.get("dataset_id"))
                    conversation.messages.append({
                        "role": "user",
                        "content": "Пользователь локально выбрал и открыл CSV. Текущий dataset_id: " + dataset_id + ". Используй этот набор. Имя файла и его содержимое не передавались модели.",
                    })
                    print(f"Открыт локально: {selected.get('name')} ({opened.get('rows')} строк × {opened.get('columns')} столбцов).")
                    print("Чтобы продолжить исследование, напиши запрос обычным текстом. Передача структуры и агрегатов будет отдельно согласована.")
                else:
                    print(opened.get("message", "Не удалось открыть CSV."))
                continue
            if command == "/privacy":
                gate = conversation.privacy_gate
                print("\nСогласия текущей консоли:")
                print(f"  Список имён CSV: {'разрешён' if gate.catalog_consent else 'не разрешён'}")
                print(f"  Структура наборов: {len(gate.schema_consent)} набор(а/ов)")
                print(f"  Агрегаты: {len(gate.aggregate_consent)} набор(а/ов)")
                print(f"  Отдельные наборы категорий: {len(gate.category_consent)}")
                action = input("Отозвать все согласия до завершения консоли? [да/Н]: ").strip().casefold()
                if action in {"да", "д", "y", "yes"}:
                    gate.catalog_consent = False
                    gate.schema_consent.clear()
                    gate.aggregate_consent.clear()
                    gate.category_consent.clear()
                    gate.blocked_datasets.clear()
                    from interfaces.gigachat.conversation import SYSTEM_PROMPT
                    conversation.messages = [{"role": "system", "content": SYSTEM_PROMPT}]
                    conversation.pending_profile_actions.clear()
                    conversation.pending_anonymization_actions.clear()
                    print("Согласия отозваны; локальная история диалога и ожидающие подтверждения очищены.")
                    print("Ранее отправленные в GigaChat сведения уже были переданы и этим действием не отзываются.")
                continue
            if command == "/clear":
                from interfaces.gigachat.conversation import SYSTEM_PROMPT
                conversation.messages = [{"role": "system", "content": SYSTEM_PROMPT}]
                conversation.pending_profile_actions.clear()
                conversation.pending_anonymization_actions.clear()
                print("История диалога и ожидающие подтверждения очищены. Согласия сохранены до выхода.")
                continue
            try:
                await conversation.ask(text)
            except GigaChatAPIError as error:
                print(f"Ошибка GigaChat: {error}")
            except (OSError, RuntimeError, ValueError) as error:
                print(f"Ошибка взаимодействия: {error}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Консольный AI Host для сервиса анонимизации 0.6.1")
    parser.add_argument("--workspace", help="Рабочая папка с CSV")
    parser.add_argument("--model", help="Название модели GigaChat")
    parser.add_argument("--scope", choices=["GIGACHAT_API_PERS", "GIGACHAT_API_B2B", "GIGACHAT_API_CORP"])
    parser.add_argument("--no-keyring", action="store_true", help="Не сохранять ключ в системном хранилище")
    args = parser.parse_args(argv)

    try:
        config = load_config()
        workspace = _resolve_workspace(args.workspace) if args.workspace else (
            _resolve_workspace(config.workspace) if config.workspace else _ask_workspace()
        )
        if args.model:
            config.gigachat_model = args.model
        if args.scope:
            config.gigachat_scope = args.scope
        config.workspace = str(workspace)
        save_config(config)
        store = CredentialStore()
        if args.no_keyring:
            store = CredentialStoreWithoutKeyring()
        api_key = _get_authorization_key(store, allow_store=not args.no_keyring and config.remember_credentials)
        return asyncio.run(_run_chat(workspace, config, api_key))
    except (OSError, RuntimeError, ValueError) as error:
        print(f"Не удалось запустить AI Host: {error}", file=sys.stderr)
        return 2


class CredentialStoreWithoutKeyring(CredentialStore):
    def get(self):
        return os.environ.get("GIGACHAT_AUTH_KEY")

    def set(self, value: str) -> bool:
        return False


def run() -> None:
    raise SystemExit(main())


if __name__ == "__main__":
    run()
