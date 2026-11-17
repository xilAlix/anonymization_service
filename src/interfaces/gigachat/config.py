from __future__ import annotations

import json
import os
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
    gigachat_model: str = "GigaChat-2-Pro"
    gigachat_scope: str = "GIGACHAT_API_PERS"
    remember_credentials: bool = True


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
        gigachat_model=str(raw.get("gigachat_model", "GigaChat-2-Pro")),
        gigachat_scope=str(raw.get("gigachat_scope", "GIGACHAT_API_PERS")),
        remember_credentials=bool(raw.get("remember_credentials", True)),
    )
    if config.gigachat_scope not in {"GIGACHAT_API_PERS", "GIGACHAT_API_B2B", "GIGACHAT_API_CORP"}:
        raise ValueError("Неизвестный GigaChat scope в config/assistant.json.")
    if not config.gigachat_model.strip():
        raise ValueError("Название модели GigaChat не должно быть пустым.")
    return config


def save_config(config: AssistantConfig, path: str | Path = ASSISTANT_CONFIG_PATH) -> None:
    target = Path(path)
    content = json.dumps(asdict(config), ensure_ascii=False, indent=2) + "\n"
    atomic_write_text(target, content, create_parents=True)


class CredentialStore:
    def get(self) -> str | None:
        environment_value = os.environ.get("GIGACHAT_AUTH_KEY", "").strip()
        if environment_value:
            return _normalize_auth_key(environment_value)
        try:
            import keyring
            stored = keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME)
            return _normalize_auth_key(stored) if stored else None
        except Exception:
            return None

    def set(self, value: str) -> bool:
        try:
            import keyring
            keyring.set_password(KEYRING_SERVICE, KEYRING_USERNAME, _normalize_auth_key(value))
            return True
        except Exception:
            return False

    def delete(self) -> None:
        try:
            import keyring
            keyring.delete_password(KEYRING_SERVICE, KEYRING_USERNAME)
        except Exception:
            pass


def _normalize_auth_key(value: str) -> str:
    cleaned = value.strip()
    if cleaned.casefold().startswith("basic "):
        cleaned = cleaned[6:].strip()
    if not cleaned or any(character.isspace() for character in cleaned):
        raise ValueError("GigaChat Authorization key имеет некорректный формат.")
    return cleaned
