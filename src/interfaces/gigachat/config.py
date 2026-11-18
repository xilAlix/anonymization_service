from __future__ import annotations

import base64
import binascii
import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from infrastructure.file_safety import atomic_write_text, contains_link_component, MAX_JSON_FILE_BYTES

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ASSISTANT_CONFIG_PATH = PROJECT_ROOT / "config" / "assistant.json"
KEYRING_SERVICE = "anonymization-service-gigachat"
KEYRING_USERNAME = "authorization_key"


@dataclass
class AssistantConfig:
    workspace: str = ""
    # Пустое значение означает: запросить доступные модели у GigaChat API.
    gigachat_model: str = ""
    gigachat_scope: str = "GIGACHAT_API_PERS"
    model_selection_confirmed: bool = False
    remember_credentials: bool = True
    ca_bundle_file: str = ""


def load_config(path: str | Path = ASSISTANT_CONFIG_PATH) -> AssistantConfig:
    target = Path(path)
    if contains_link_component(target):
        raise ValueError("Путь к настройкам AI Host не должен содержать символические ссылки или junction.")
    if not target.exists():
        return AssistantConfig()
    if target.stat().st_size > MAX_JSON_FILE_BYTES:
        raise ValueError("Файл настроек AI Host слишком велик.")
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("Не удалось прочитать config/assistant.json.") from error
    if not isinstance(raw, dict):
        raise ValueError("Корень config/assistant.json должен быть JSON-объектом.")
    config = AssistantConfig(
        workspace=str(raw.get("workspace", "")),
        gigachat_model=(str(raw.get("gigachat_model", "")).strip() if bool(raw.get("model_selection_confirmed", False)) else ""),
        gigachat_scope=str(raw.get("gigachat_scope", "GIGACHAT_API_PERS")),
        model_selection_confirmed=bool(raw.get("model_selection_confirmed", False)),
        remember_credentials=bool(raw.get("remember_credentials", True)),
        ca_bundle_file=str(raw.get("ca_bundle_file", "")).strip(),
    )
    if config.gigachat_scope not in {"GIGACHAT_API_PERS", "GIGACHAT_API_B2B", "GIGACHAT_API_CORP"}:
        raise ValueError("Неизвестный GigaChat scope в config/assistant.json.")
    return config


def save_config(config: AssistantConfig, path: str | Path = ASSISTANT_CONFIG_PATH) -> None:
    target = Path(path)
    content = json.dumps(asdict(config), ensure_ascii=False, indent=2) + "\n"
    atomic_write_text(target, content, create_parents=True)


def normalize_auth_key(value: str) -> str:
    """Проверяет Authorization Key до сетевого запроса и возвращает Base64-часть."""
    if not isinstance(value, str):
        raise ValueError("Authorization Key должен быть текстовой строкой.")

    cleaned = value.strip().strip('"').strip("'").strip()
    if cleaned[:6].casefold() == "basic ":
        cleaned = cleaned[6:].strip()

    # Разрешаем переносы строк/пробелы, появившиеся при копировании ключа.
    cleaned = re.sub(r"\s+", "", cleaned)
    if not cleaned:
        raise ValueError("Authorization Key пустой.")
    if any(character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=" for character in cleaned):
        raise ValueError(
            "Authorization Key содержит недопустимые символы. Скопируй целиком поле "
            "Authorization Key из настроек проекта GigaChat API."
        )
    if len(cleaned) % 4 == 1:
        raise ValueError("Authorization Key имеет некорректную длину Base64.")
    padded = cleaned + ("=" * ((-len(cleaned)) % 4))
    try:
        decoded = base64.b64decode(padded, validate=True)
        decoded_text = decoded.decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        raise ValueError(
            "Authorization Key не является корректным Base64. Нужен именно ключ из поля "
            "Authorization Key в кабинете GigaChat API, а не Client Secret или Access Token."
        ) from None

    if decoded_text.count(":") != 1:
        raise ValueError(
            "Структура Authorization Key неверная. Используй полный ключ Authorization Key "
            "из кабинета GigaChat API, а не Client ID, Client Secret или Access Token."
        )
    client_id, client_secret = decoded_text.split(":", 1)
    if not client_id or not client_secret:
        raise ValueError("Authorization Key не содержит обе части учётных данных.")
    return padded


# Оставлено приватное имя для совместимости с существующими вызовами Host.
_normalize_auth_key = normalize_auth_key


class CredentialStore:
    def get(self) -> str | None:
        environment_value = os.environ.get("GIGACHAT_AUTH_KEY", "")
        if environment_value.strip():
            return normalize_auth_key(environment_value)
        try:
            import keyring
            stored = keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME)
        except Exception:
            return None
        if not stored:
            return None
        try:
            return normalize_auth_key(stored)
        except ValueError:
            raise ValueError(
                "Сохранённый в Windows Keyring Authorization Key имеет неверный формат. "
                "Замени его командой host.py --change-key. Сам ключ не был выведен на экран."
            ) from None

    def set(self, value: str) -> bool:
        normalized = normalize_auth_key(value)
        try:
            import keyring
            keyring.set_password(KEYRING_SERVICE, KEYRING_USERNAME, normalized)
            return True
        except Exception:
            return False

    def delete(self) -> None:
        try:
            import keyring
            keyring.delete_password(KEYRING_SERVICE, KEYRING_USERNAME)
        except Exception:
            pass
