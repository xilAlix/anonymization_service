import json
from pathlib import Path
from typing import Any

import pandas as pd

from anonymization.algorithms.k_anonymity import (
    anonymize_k_anonymity,
    evaluate_qi_profiles,
)
from infrastructure.attribute_profile_store import (
    DEFAULT_PROFILE_PATH,
    load_quasi_identifier_correlation_blocks,
    load_quasi_identifier_groups,
    load_quasi_identifier_hierarchies,
)


def execute_k_anonymization(
    dataframe: pd.DataFrame,
    source_csv_path: str | Path,
    default_k: int = 5,
    representative: str = "mean",
    profile_path: str | Path = DEFAULT_PROFILE_PATH,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    profiles = load_quasi_identifier_groups(source_csv_path, profile_path)
    hierarchies = load_quasi_identifier_hierarchies(source_csv_path, profile_path)
    correlation_blocks = load_quasi_identifier_correlation_blocks(source_csv_path, profile_path)
    return anonymize_k_anonymity(
        dataframe,
        profiles,
        default_k=default_k,
        representative=representative,
        hierarchies=hierarchies,
        correlation_blocks=correlation_blocks,
    )


def evaluate_current_k(
    dataframe: pd.DataFrame,
    source_csv_path: str | Path,
    default_k: int = 5,
    profile_path: str | Path = DEFAULT_PROFILE_PATH,
) -> list[dict]:
    groups = load_quasi_identifier_groups(source_csv_path, profile_path)
    active = [group for group in groups if group.get("active", group.get("source") != "automatic")]
    if not active:
        raise ValueError("Нет активных QI-профилей для проверки. Сначала подтвердите группы.")
    return evaluate_qi_profiles(dataframe, active, default_k)


def save_k_anonymity_report(report: dict, output_path: str | Path) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(path)
