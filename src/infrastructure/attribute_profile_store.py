import hashlib
import json
from pathlib import Path

from data_processing.attribute_classifier import ROLE_LABELS


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROFILE_PATH = PROJECT_ROOT / "data" / "metadata" / "attribute_profiles.json"


def dataset_profile_key(csv_path: str | Path) -> str:
    normalized_path = str(Path(csv_path).resolve()).casefold()
    return hashlib.sha256(normalized_path.encode("utf-8")).hexdigest()


def _read_registry(path: Path) -> dict:
    if not path.exists():
        return {"format_version": 1, "datasets": {}}
    try:
        registry = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Не удалось прочитать профили атрибутов {path}: {error}") from error
    if not isinstance(registry, dict) or not isinstance(registry.get("datasets", {}), dict):
        raise ValueError("Файл профилей атрибутов имеет некорректную структуру.")
    registry.setdefault("format_version", 1)
    registry.setdefault("datasets", {})
    return registry


def load_manual_role_overrides(
    csv_path: str | Path,
    profile_path: str | Path = DEFAULT_PROFILE_PATH,
) -> dict[str, list[str]]:
    registry = _read_registry(Path(profile_path))
    fingerprint = dataset_profile_key(csv_path)
    dataset_profile = registry["datasets"].get(fingerprint, {})
    overrides = dataset_profile.get("manual_overrides", {})
    if not isinstance(overrides, dict):
        raise ValueError("Список ручных назначений атрибутов повреждён.")

    validated: dict[str, list[str]] = {}
    for attribute, roles in overrides.items():
        if not isinstance(attribute, str) or not isinstance(roles, list):
            raise ValueError("Некорректная запись ручного назначения атрибута.")
        if any(role not in ROLE_LABELS for role in roles):
            raise ValueError(f"Неизвестная роль атрибута для столбца «{attribute}».")
        validated[attribute] = roles
    return validated


def save_manual_role_overrides(
    csv_path: str | Path,
    manual_overrides: dict[str, list[str]],
    profile_path: str | Path = DEFAULT_PROFILE_PATH,
) -> None:
    valid_roles = set(ROLE_LABELS)
    for attribute, roles in manual_overrides.items():
        if not isinstance(attribute, str) or not isinstance(roles, list):
            raise ValueError("Ручные назначения должны иметь формат «столбец: список ролей».")
        if len(roles) != len(set(roles)) or any(role not in valid_roles for role in roles):
            raise ValueError(f"Некорректные роли для столбца «{attribute}».")

    path = Path(profile_path)
    registry = _read_registry(path)
    fingerprint = dataset_profile_key(csv_path)

    if manual_overrides:
        registry["datasets"][fingerprint] = {
            "source_name": Path(csv_path).name,
            "manual_overrides": manual_overrides,
        }
    else:
        registry["datasets"].pop(fingerprint, None)

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(
        json.dumps(registry, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(path)
