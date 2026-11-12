import hashlib
import json
from pathlib import Path
from uuid import uuid4

from data_processing.attribute_classifier import ROLE_LABELS


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROFILE_PATH = PROJECT_ROOT / "data" / "metadata" / "attribute_profiles.json"


def dataset_profile_key(csv_path: str | Path) -> str:
    normalized_path = str(Path(csv_path).resolve()).casefold()
    return hashlib.sha256(normalized_path.encode("utf-8")).hexdigest()


def _read_registry(path: Path) -> dict:
    if not path.exists():
        return {"format_version": 2, "datasets": {}}
    try:
        registry = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Не удалось прочитать профили атрибутов {path}: {error}") from error
    if not isinstance(registry, dict) or not isinstance(registry.get("datasets", {}), dict):
        raise ValueError("Файл профилей атрибутов имеет некорректную структуру.")
    registry["format_version"] = max(int(registry.get("format_version", 1)), 2)
    registry.setdefault("datasets", {})
    for dataset_key, dataset_profile in registry["datasets"].items():
        if not isinstance(dataset_profile, dict):
            raise ValueError(f"Профиль набора данных «{dataset_key}» повреждён.")
    return registry


def _write_registry(path: Path, registry: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(
        json.dumps(registry, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(path)


def _dataset_profile(registry: dict, csv_path: str | Path) -> dict:
    fingerprint = dataset_profile_key(csv_path)
    return registry["datasets"].get(fingerprint, {})


def load_manual_role_overrides(
    csv_path: str | Path,
    profile_path: str | Path = DEFAULT_PROFILE_PATH,
) -> dict[str, list[str]]:
    registry = _read_registry(Path(profile_path))
    dataset_profile = _dataset_profile(registry, csv_path)
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
    dataset = registry["datasets"].setdefault(fingerprint, {"source_name": Path(csv_path).name})
    dataset["source_name"] = Path(csv_path).name
    if manual_overrides:
        dataset["manual_overrides"] = manual_overrides
    else:
        dataset.pop("manual_overrides", None)
    if not any(dataset.get(key) for key in (
        "manual_overrides", "quasi_identifier_groups", "generalization_hierarchies", "correlation_blocks"
    )):
        registry["datasets"].pop(fingerprint, None)
    _write_registry(path, registry)


def _validate_groups(groups: list[dict], available_columns: set[str] | None = None) -> list[dict]:
    if not isinstance(groups, list):
        raise ValueError("Группы QI должны быть представлены списком.")

    validated: list[dict] = []
    seen_ids: set[str] = set()
    seen_names: set[str] = set()
    for index, group in enumerate(groups, start=1):
        if not isinstance(group, dict):
            raise ValueError(f"Группа QI №{index} имеет некорректный формат.")
        group_id = group.get("id")
        name = group.get("name")
        attributes = group.get("attributes")
        if not isinstance(group_id, str) or not group_id.strip():
            raise ValueError(f"У группы QI №{index} отсутствует идентификатор.")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"У группы QI №{index} должно быть непустое название.")
        if group_id in seen_ids:
            raise ValueError(f"Идентификатор группы QI «{group_id}» повторяется.")
        normalized_name = name.strip().casefold()
        if normalized_name in seen_names:
            raise ValueError(f"Название группы QI «{name}» повторяется.")
        if not isinstance(attributes, list) or any(
            not isinstance(attribute, str) or not attribute for attribute in attributes
        ):
            raise ValueError(f"Список атрибутов группы «{name}» имеет некорректный формат.")
        if not attributes:
            raise ValueError(f"Группа «{name}» должна содержать хотя бы один атрибут.")
        if len(attributes) != len(set(attributes)):
            raise ValueError(f"В группе «{name}» атрибуты не должны повторяться.")
        if available_columns is not None:
            missing = [attribute for attribute in attributes if attribute not in available_columns]
            if missing:
                raise ValueError(
                    f"В группе «{name}» указаны отсутствующие столбцы: {', '.join(missing)}."
                )
        seen_ids.add(group_id)
        seen_names.add(normalized_name)
        k_override = group.get("k_override")
        if k_override is not None and (
            isinstance(k_override, bool) or not isinstance(k_override, int) or k_override < 2
        ):
            raise ValueError(f"Для группы «{name}» k_override должен быть целым числом не меньше 2.")
        active = group.get("active", group.get("source", "manual") != "automatic")
        if not isinstance(active, bool):
            raise ValueError(f"Для группы «{name}» параметр active должен быть логическим.")
        validated.append({
            "id": group_id,
            "name": name.strip(),
            "attributes": list(attributes),
            "source": group.get("source", "manual"),
            "confidence": group.get("confidence", "ручная"),
            "description": group.get("description", ""),
            "external_source_families": list(group.get("external_source_families", [])),
            "attribute_evidence": dict(group.get("attribute_evidence", {})),
            "reasons": list(group.get("reasons", [])),
            "unique_tuple_count": group.get("unique_tuple_count"),
            "unique_tuple_ratio": group.get("unique_tuple_ratio"),
            "row_count": group.get("row_count"),
            "active": active,
            "k_override": k_override,
        })
    return validated


def load_quasi_identifier_groups(
    csv_path: str | Path,
    profile_path: str | Path = DEFAULT_PROFILE_PATH,
) -> list[dict]:
    registry = _read_registry(Path(profile_path))
    groups = _dataset_profile(registry, csv_path).get("quasi_identifier_groups", [])
    return _validate_groups(groups)


def save_quasi_identifier_groups(
    csv_path: str | Path,
    groups: list[dict],
    available_columns: set[str] | list[str] | tuple[str, ...] | None = None,
    profile_path: str | Path = DEFAULT_PROFILE_PATH,
) -> None:
    validated = _validate_groups(
        groups,
        set(available_columns) if available_columns is not None else None,
    )
    path = Path(profile_path)
    registry = _read_registry(path)
    fingerprint = dataset_profile_key(csv_path)
    dataset = registry["datasets"].setdefault(fingerprint, {"source_name": Path(csv_path).name})
    dataset["source_name"] = Path(csv_path).name
    if validated:
        dataset["quasi_identifier_groups"] = validated
    else:
        dataset.pop("quasi_identifier_groups", None)
    if not any(dataset.get(key) for key in (
        "manual_overrides", "quasi_identifier_groups", "generalization_hierarchies", "correlation_blocks"
    )):
        registry["datasets"].pop(fingerprint, None)
    _write_registry(path, registry)


def new_manual_quasi_identifier_group(name: str, attributes: list[str]) -> dict:
    return {
        "id": uuid4().hex[:10],
        "name": name.strip(),
        "attributes": list(attributes),
        "source": "manual",
        "confidence": "ручная",
        "description": "Группа, созданная пользователем.",
        "external_source_families": [],
        "attribute_evidence": {},
        "reasons": ["Состав группы задан пользователем."],
        "unique_tuple_count": None,
        "unique_tuple_ratio": None,
        "active": True,
        "k_override": None,
    }



def load_quasi_identifier_hierarchies(
    csv_path: str | Path,
    profile_path: str | Path = DEFAULT_PROFILE_PATH,
) -> dict[str, list[dict]]:
    registry = _read_registry(Path(profile_path))
    dataset = _dataset_profile(registry, csv_path)
    hierarchies = dataset.get("generalization_hierarchies", {})
    if not isinstance(hierarchies, dict):
        raise ValueError("Иерархии обобщения QI имеют некорректную структуру.")
    validated: dict[str, list[dict]] = {}
    for column, levels in hierarchies.items():
        if not isinstance(column, str) or not isinstance(levels, list):
            raise ValueError("Некорректная запись иерархии обобщения.")
        if any(not isinstance(level, dict) for level in levels):
            raise ValueError(f"Уровни иерархии столбца «{column}» должны быть JSON-объектами.")
        validated[column] = levels
    return validated


def save_quasi_identifier_hierarchy(
    csv_path: str | Path,
    column: str,
    levels: list[dict],
    available_columns: set[str] | list[str] | tuple[str, ...],
    profile_path: str | Path = DEFAULT_PROFILE_PATH,
) -> None:
    if column not in set(available_columns):
        raise ValueError(f"Столбец «{column}» отсутствует в CSV.")
    if not isinstance(levels, list) or not levels:
        raise ValueError("Нужно задать хотя бы один уровень иерархии.")
    for index, level in enumerate(levels, start=1):
        if not isinstance(level, dict) or not level:
            raise ValueError(f"Уровень {index} должен быть непустым JSON-объектом.")
        if any(not isinstance(key, str) or not isinstance(value, str) or not value.strip() for key, value in level.items()):
            raise ValueError(f"Уровень {index} содержит некорректные значения.")
    path = Path(profile_path)
    registry = _read_registry(path)
    fingerprint = dataset_profile_key(csv_path)
    dataset = registry["datasets"].setdefault(fingerprint, {"source_name": Path(csv_path).name})
    hierarchies = dataset.setdefault("generalization_hierarchies", {})
    hierarchies[column] = levels
    _write_registry(path, registry)


def load_quasi_identifier_correlation_blocks(
    csv_path: str | Path,
    profile_path: str | Path = DEFAULT_PROFILE_PATH,
) -> list[dict]:
    registry = _read_registry(Path(profile_path))
    blocks = _dataset_profile(registry, csv_path).get("correlation_blocks", [])
    if not isinstance(blocks, list):
        raise ValueError("Блоки сохранения корреляций имеют некорректную структуру.")
    validated = []
    seen_ids: set[str] = set()
    for block in blocks:
        if not isinstance(block, dict):
            raise ValueError("Некорректная запись блока корреляций.")
        block_id = block.get("id")
        name = block.get("name")
        attributes = block.get("attributes")
        if not isinstance(block_id, str) or not block_id or block_id in seen_ids:
            raise ValueError("Некорректный или повторяющийся ID блока корреляций.")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("У блока корреляций должно быть название.")
        if not isinstance(attributes, list) or len(attributes) < 2 or len(attributes) != len(set(attributes)):
            raise ValueError(f"Блок «{name}» должен содержать минимум два различных столбца.")
        seen_ids.add(block_id)
        validated.append({"id": block_id, "name": name.strip(), "attributes": list(attributes)})
    return validated


def save_quasi_identifier_correlation_blocks(
    csv_path: str | Path,
    blocks: list[dict],
    available_columns: set[str] | list[str] | tuple[str, ...],
    profile_path: str | Path = DEFAULT_PROFILE_PATH,
) -> None:
    available = set(available_columns)
    ids: set[str] = set()
    names: set[str] = set()
    validated = []
    for block in blocks:
        if not isinstance(block, dict):
            raise ValueError("Некорректная запись блока корреляций.")
        block_id = block.get("id")
        name = str(block.get("name", "")).strip()
        attributes = block.get("attributes")
        if not isinstance(block_id, str) or not block_id or block_id in ids:
            raise ValueError("ID блока корреляций должен быть уникальным.")
        if not name or name.casefold() in names:
            raise ValueError("Название блока корреляций должно быть уникальным и непустым.")
        if not isinstance(attributes, list) or len(attributes) < 2 or len(attributes) != len(set(attributes)):
            raise ValueError(f"Блок «{name}» должен содержать минимум два различных столбца.")
        missing = [column for column in attributes if column not in available]
        if missing:
            raise ValueError(f"В блоке «{name}» отсутствуют столбцы: {', '.join(missing)}")
        ids.add(block_id)
        names.add(name.casefold())
        validated.append({"id": block_id, "name": name, "attributes": list(attributes)})
    path = Path(profile_path)
    registry = _read_registry(path)
    fingerprint = dataset_profile_key(csv_path)
    dataset = registry["datasets"].setdefault(fingerprint, {"source_name": Path(csv_path).name})
    if validated:
        dataset["correlation_blocks"] = validated
    else:
        dataset.pop("correlation_blocks", None)
    _write_registry(path, registry)


def delete_quasi_identifier_hierarchy(
    csv_path: str | Path,
    column: str,
    profile_path: str | Path = DEFAULT_PROFILE_PATH,
) -> None:
    path = Path(profile_path)
    registry = _read_registry(path)
    fingerprint = dataset_profile_key(csv_path)
    dataset = registry["datasets"].get(fingerprint)
    if not dataset or column not in dataset.get("generalization_hierarchies", {}):
        raise ValueError(f"Для столбца «{column}» иерархия не найдена.")
    dataset["generalization_hierarchies"].pop(column, None)
    if not dataset["generalization_hierarchies"]:
        dataset.pop("generalization_hierarchies", None)
    if not any(dataset.get(key) for key in (
        "manual_overrides", "quasi_identifier_groups", "generalization_hierarchies", "correlation_blocks"
    )):
        registry["datasets"].pop(fingerprint, None)
    _write_registry(path, registry)
