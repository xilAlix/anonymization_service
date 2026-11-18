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
    normalize_auth_key,
    save_config,
)
from interfaces.gigachat.conversation import GigaChatConversation  # noqa: E402
from interfaces.gigachat.gigachat_client import GigaChatAPIError, GigaChatClient  # noqa: E402
from interfaces.gigachat.mcp_client import connect_mcp  # noqa: E402


def _configure_console() -> None:
    if os.name != "nt":
        return
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError, ValueError):
            pass


def _resolve_workspace(value: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.exists() or not path.is_dir():
        raise ValueError("Рабочая папка не найдена или не является каталогом.")
    return path


def _ask_workspace(default: str = "") -> Path:
    if not default and not sys.stdin.isatty():
        raise RuntimeError("Для первого выбора рабочей папки нужен интерактивный терминал. Запусти Host из PyCharm Terminal/PowerShell или задай --workspace.")
    while True:
        prompt = f"Папка с CSV [{default}]: " if default else "Папка с CSV: "
        entered = input(prompt).strip().strip('"')
        chosen = entered or default
        if not chosen:
            print("Укажи папку, в которой лежат CSV-файлы.", flush=True)
            continue
        try:
            return _resolve_workspace(chosen)
        except ValueError as error:
            print(error, flush=True)


def _get_authorization_key(
    store: CredentialStore,
    allow_store: bool = True,
    force_prompt: bool = False,
) -> str:
    if not force_prompt:
        try:
            existing = store.get()
        except ValueError as error:
            print(f"\n{error}", flush=True)
            existing = None
            force_prompt = True
        if existing:
            return normalize_auth_key(existing)

    if force_prompt:
        print("\nЗапрошена замена ранее сохранённого Authorization Key.", flush=True)
        if os.environ.get("GIGACHAT_AUTH_KEY"):
            print("Внимание: переменная GIGACHAT_AUTH_KEY имеет приоритет над Keyring. После замены удали её командой Remove-Item Env:GIGACHAT_AUTH_KEY, иначе при следующем запуске будет прочитан старый ключ.", flush=True)
        store.delete()
    if not sys.stdin.isatty():
        raise RuntimeError("Нет интерактивного терминала для скрытого ввода Authorization Key. Запусти Host из PyCharm Terminal/PowerShell, используй run_assistant.bat или задай GIGACHAT_AUTH_KEY.")
    print("\nДля подключения нужен GigaChat Authorization Key.", flush=True)
    print("Вставь полное значение поля Authorization Key из настроек проекта GigaChat API.", flush=True)
    print("Не используй отдельно Client ID, Client Secret или Access Token.", flush=True)
    try:
        entered = getpass.getpass("Authorization Key (ввод скрыт): ").strip()
    except (EOFError, KeyboardInterrupt):
        raise ValueError("Ввод Authorization Key отменён.") from None
    if not entered:
        raise ValueError("Authorization Key не указан.")
    try:
        normalized = normalize_auth_key(entered)
    except ValueError as error:
        raise ValueError(f"\n{error}\nКлюч не сохранён. Получи новый Authorization Key и запусти Host повторно.") from None

    if allow_store:
        remember = input("Сохранить ключ в защищённом хранилище Windows? [Да/н]: ").strip().casefold()
        if remember in {"", "да", "д", "y", "yes"}:
            if store.set(normalized):
                print("Ключ сохранён в системном хранилище учётных данных.", flush=True)
            else:
                print("Не удалось использовать системное хранилище. Ключ будет действовать только в этом запуске.", flush=True)
    return normalized


def _select_model(
    models: list[str],
    saved_model: str = "",
    requested_model: str = "",
    input_func=None,
    print_func=print,
) -> str:
    if requested_model:
        if requested_model not in models:
            raise ValueError(
                f"Модель {requested_model!r} не найдена среди доступных этому Authorization Key. "
                f"Доступные модели: {', '.join(models)}"
            )
        return requested_model
    if saved_model and saved_model in models:
        print_func(f"Используется сохранённая модель: {saved_model}")
        return saved_model

    if input_func is None and not sys.stdin.isatty():
        raise RuntimeError("Не удалось выбрать модель: интерактивный ввод недоступен. Запусти Host из Terminal или укажи --model из API-каталога.")
    if input_func is None:
        input_func = input
    print_func("\nМодели, доступные этому GigaChat API ключу:")
    for index, model in enumerate(models, start=1):
        print_func(f"  {index}. {model}")
    default = 1
    answer = input_func(f"Выбери номер модели [1]: ").strip()
    if not answer:
        return models[default - 1]
    if answer.isdigit():
        position = int(answer) - 1
        if 0 <= position < len(models):
            return models[position]
    if answer in models:
        return answer
    raise ValueError("Выбор модели не распознан. Запусти Host повторно и укажи номер из списка.")


def _print_help() -> None:
    print("""
Команды консоли:
  /help       показать команды
  /files      локально перечислить CSV без передачи списка GigaChat
  /open NAME  локально открыть CSV по имени или номеру из /files
  /workspace  показать рабочую папку
  /models     показать модели, доступные текущему ключу GigaChat
  /privacy    показать и изменить согласия на передачу метаданных/агрегатов
  /clear      очистить историю текущего диалога
  /exit       завершить работу

Обычный текст отправляется GigaChat. Исходные строки CSV не передаются модели.
""".strip(), flush=True)


async def _run_chat(workspace: Path, config: AssistantConfig, giga: GigaChatClient) -> int:
    print("\n[4/4] Подключение к локальному MCP Server...", flush=True)
    try:
        async with asyncio.timeout(35):
            async with connect_mcp(workspace) as mcp_client:
                print("MCP Server запущен; получение списка инструментов...", flush=True)
                conversation = GigaChatConversation(giga, mcp_client, workspace)
                await asyncio.wait_for(conversation.initialize(), timeout=20)
                print("\nПодключение готово.", flush=True)
                print(f"Python: {sys.executable}", flush=True)
                print(f"Рабочая папка: {workspace}", flush=True)
                print(f"GigaChat: {config.gigachat_model}", flush=True)
                print(f"MCP-инструментов: {len(conversation.functions)}", flush=True)
                print("Введи /help для списка команд.", flush=True)
                print("Важно: текст твоих сообщений отправляется в GigaChat. Не вводи ФИО, email, телефоны и исходные значения CSV.\n", flush=True)

                local_file_list: list[dict] = []
                while True:
                    try:
                        text = input("ты> ").strip()
                    except (EOFError, KeyboardInterrupt):
                        print("\nЗавершение работы.", flush=True)
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
                        print(f"Рабочая папка: {workspace}", flush=True)
                        continue
                    if command == "/models":
                        print("Доступные модели:", flush=True)
                        for model in giga.list_models():
                            print(f"  - {model}", flush=True)
                        continue
                    if command == "/files":
                        result = await mcp_client.call_tool("list_datasets", {})
                        from interfaces.gigachat.mcp_client import mcp_result_to_json
                        payload = mcp_result_to_json(result)
                        if payload.get("ok"):
                            local_file_list = payload.get("datasets", [])
                            print("\nCSV в рабочей папке (локально, без передачи GigaChat):", flush=True)
                            for index, item in enumerate(local_file_list, start=1):
                                print(f"  {index}. {item.get('name')}  ({item.get('size_bytes')} байт)", flush=True)
                            print("Выбери набор командой /open <номер или точное имя>.", flush=True)
                        else:
                            print(payload.get("message", "Не удалось получить список CSV."), flush=True)
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
                                print("Имя неоднозначно. Выбери CSV по номеру через /files.", flush=True)
                                continue
                        if not selected:
                            print("Файл не найден. Выполни /files и выбери номер или точное имя.", flush=True)
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
                            print(f"Открыт локально: {selected.get('name')} ({opened.get('rows')} строк × {opened.get('columns')} столбцов).", flush=True)
                            print("Чтобы продолжить исследование, напиши запрос обычным текстом. Передача структуры и агрегатов будет отдельно согласована.", flush=True)
                        else:
                            print(opened.get("message", "Не удалось открыть CSV."), flush=True)
                        continue
                    if command == "/privacy":
                        gate = conversation.privacy_gate
                        print("\nСогласия текущей консоли:", flush=True)
                        print(f"  Список имён CSV: {'разрешён' if gate.catalog_consent else 'не разрешён'}", flush=True)
                        print(f"  Структура наборов: {len(gate.schema_consent)} набор(а/ов)", flush=True)
                        print(f"  Агрегаты: {len(gate.aggregate_consent)} набор(а/ов)", flush=True)
                        print(f"  Отдельные наборы категорий: {len(gate.category_consent)}", flush=True)
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
                            print("Согласия отозваны; локальная история диалога и ожидающие подтверждения очищены.", flush=True)
                            print("Ранее отправленные в GigaChat сведения уже были переданы и этим действием не отзываются.", flush=True)
                        continue
                    if command == "/clear":
                        from interfaces.gigachat.conversation import SYSTEM_PROMPT
                        conversation.messages = [{"role": "system", "content": SYSTEM_PROMPT}]
                        conversation.pending_profile_actions.clear()
                        conversation.pending_anonymization_actions.clear()
                        print("История диалога и ожидающие подтверждения очищены. Согласия сохранены до выхода.", flush=True)
                        continue
                    try:
                        print("GigaChat обрабатывает запрос...", flush=True)
                        await conversation.ask(text)
                    except GigaChatAPIError as error:
                        print(f"Ошибка GigaChat: {error}", flush=True)
                    except (OSError, RuntimeError, ValueError) as error:
                        print(f"Ошибка взаимодействия: {error}", flush=True)
    except TimeoutError:
        raise RuntimeError(
            "Истекло время подключения к MCP Server. Проверь установку зависимостей текущего Python "
            "и запусти Host из корня проекта через .venv."
        ) from None
    return 0


def main(argv: list[str] | None = None) -> int:
    _configure_console()
    parser = argparse.ArgumentParser(description="Консольный AI Host для сервиса анонимизации 0.6.2")
    parser.add_argument("--workspace", help="Рабочая папка с CSV")
    parser.add_argument("--model", help="ID модели из списка, доступного GigaChat API")
    parser.add_argument("--scope", choices=["GIGACHAT_API_PERS", "GIGACHAT_API_B2B", "GIGACHAT_API_CORP"])
    parser.add_argument("--ca-bundle", help="Дополнительный PEM/DER CA-сертификат для TLS")
    parser.add_argument("--no-keyring", action="store_true", help="Не сохранять ключ в системном хранилище")
    parser.add_argument("--change-key", action="store_true", help="Запросить новый Authorization Key вместо сохранённого")
    args = parser.parse_args(argv)

    try:
        os.chdir(PROJECT_ROOT)
        print("Anonymization Service AI Host 0.6.2", flush=True)
        print(f"Python: {sys.executable}", flush=True)
        try:
            import mcp  # noqa: F401
        except ImportError:
            raise RuntimeError(r"В выбранном Python не установлен MCP SDK. Запусти .venv\Scripts\python.exe src\interfaces\gigachat\host.py либо активируй виртуальное окружение проекта.") from None
        config = load_config()
        workspace = _resolve_workspace(args.workspace) if args.workspace else (
            _resolve_workspace(config.workspace) if config.workspace else _ask_workspace()
        )
        if args.scope:
            config.gigachat_scope = args.scope
        if args.model:
            config.gigachat_model = args.model
            config.model_selection_confirmed = True
        if args.ca_bundle:
            config.ca_bundle_file = str(Path(args.ca_bundle).expanduser().resolve())
        elif os.environ.get("GIGACHAT_CA_BUNDLE_FILE"):
            config.ca_bundle_file = os.environ["GIGACHAT_CA_BUNDLE_FILE"]
        config.workspace = str(workspace)
        save_config(config)

        store = CredentialStore()
        if args.no_keyring:
            store = CredentialStoreWithoutKeyring()
        print("[1/4] Получение Authorization Key...", flush=True)
        api_key = _get_authorization_key(
            store,
            allow_store=not args.no_keyring and config.remember_credentials,
            force_prompt=args.change_key,
        )

        print("[2/4] Проверка TLS и авторизации GigaChat...", flush=True)
        giga = GigaChatClient(
            authorization_key=api_key,
            scope=config.gigachat_scope,
            model=config.gigachat_model,
            ca_bundle_file=config.ca_bundle_file,
        )
        giga.authenticate()

        print("[3/4] Получение списка моделей, доступных этому ключу...", flush=True)
        models = giga.list_models()
        chosen_model = _select_model(models, config.gigachat_model, args.model)
        if chosen_model != config.gigachat_model or not config.model_selection_confirmed:
            config.gigachat_model = chosen_model
            config.model_selection_confirmed = True
            giga.model = chosen_model
            save_config(config)
        print(f"Выбрана модель: {chosen_model}", flush=True)
        return asyncio.run(_run_chat(workspace, config, giga))
    except GigaChatAPIError as error:
        print(f"Ошибка GigaChat при проверке подключения: {error}", file=sys.stderr, flush=True)
        return 2
    except (OSError, RuntimeError, ValueError) as error:
        print(f"Не удалось запустить AI Host: {error}", file=sys.stderr, flush=True)
        return 2


class CredentialStoreWithoutKeyring(CredentialStore):
    def get(self):
        return os.environ.get("GIGACHAT_AUTH_KEY")

    def set(self, value: str) -> bool:
        return False

    def delete(self) -> None:
        pass


def run() -> None:
    raise SystemExit(main())


if __name__ == "__main__":
    run()
