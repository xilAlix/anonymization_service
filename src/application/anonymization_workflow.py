from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from anonymization.column_removal_adapter import remove_identifier_columns
from anonymization.tokenization_adapter import tokenize_identifier_columns
from infrastructure.attribute_profile_store import (
    DEFAULT_PROFILE_PATH,
    load_manual_role_overrides,
)

TOKENIZE_DIRECT_IDENTIFIERS = "tokenize_direct_identifiers"
REMOVE_DIRECT_IDENTIFIERS = "remove_direct_identifiers"
K_ANONYMITY = "k_anonymity"
SUPPORTED_OPERATIONS = {
    TOKENIZE_DIRECT_IDENTIFIERS,
    REMOVE_DIRECT_IDENTIFIERS,
    K_ANONYMITY,
}


@dataclass(frozen=True)
class AnonymizationExecutionResult:
    dataframe: pd.DataFrame
    affected_columns: list[str]
    operations: list[str]
    k_report: dict[str, Any] | None = None


def get_manual_direct_identifier_columns(
    dataframe: pd.DataFrame,
    source_csv_path: str | Path,
    profile_path: str | Path = DEFAULT_PROFILE_PATH,
) -> list[str]:
    manual_overrides = load_manual_role_overrides(source_csv_path, profile_path)
    selected_columns = [
        attribute
        for attribute, roles in manual_overrides.items()
        if "direct_identifier" in roles and attribute in dataframe.columns
    ]

    if not selected_columns:
        raise ValueError(
            "Для текущей таблицы вручную не назначен ни один прямой идентификатор. "
            "Откройте классификацию атрибутов и назначьте роль "
            "«Прямой идентификатор» хотя бы одному столбцу."
        )

    return selected_columns


def anonymize_manual_direct_identifiers(
    dataframe: pd.DataFrame,
    source_csv_path: str | Path,
    profile_path: str | Path = DEFAULT_PROFILE_PATH,
) -> tuple[pd.DataFrame, list[str]]:
    selected_columns = get_manual_direct_identifier_columns(
        dataframe,
        source_csv_path,
        profile_path,
    )
    return tokenize_identifier_columns(dataframe, selected_columns), selected_columns


def remove_manual_direct_identifiers(
    dataframe: pd.DataFrame,
    source_csv_path: str | Path,
    profile_path: str | Path = DEFAULT_PROFILE_PATH,
) -> tuple[pd.DataFrame, list[str]]:
    selected_columns = get_manual_direct_identifier_columns(
        dataframe,
        source_csv_path,
        profile_path,
    )
    manual_overrides = load_manual_role_overrides(source_csv_path, profile_path)
    analytical_columns = [
        column
        for column in selected_columns
        if "analytical_attribute" in manual_overrides.get(column, [])
    ]
    if analytical_columns:
        raise ValueError(
            "Удаление отменено. Столбцы одновременно помечены как прямые "
            "идентификаторы и аналитические атрибуты: "
            + ", ".join(analytical_columns)
            + ". Такие столбцы сохраняются, чтобы не потерять данные, "
            "назначенные для аналитики. Для их защиты выберите токенизацию "
            "или пересмотрите назначенные роли."
        )

    return remove_identifier_columns(dataframe, selected_columns), selected_columns


def apply_anonymization_operations(
    dataframe: pd.DataFrame,
    source_csv_path: str | Path,
    operations: list[str],
    profile_path: str | Path = DEFAULT_PROFILE_PATH,
    default_k: int = 5,
    representative: str = "mean",
) -> AnonymizationExecutionResult:
    if not operations:
        raise ValueError("Не выбрана ни одна операция анонимизации.")

    unknown_operations = [
        operation for operation in operations if operation not in SUPPORTED_OPERATIONS
    ]
    if unknown_operations:
        raise ValueError(
            "Неизвестные операции анонимизации: " + ", ".join(unknown_operations)
        )

    if len(operations) != len(set(operations)):
        raise ValueError("Список операций анонимизации содержит повторы.")

    if (
        TOKENIZE_DIRECT_IDENTIFIERS in operations
        and REMOVE_DIRECT_IDENTIFIERS in operations
    ):
        raise ValueError(
            "Токенизация и удаление являются альтернативными способами обработки "
            "одних и тех же прямых идентификаторов. Для суммарной анонимизации "
            "выберите один из этих способов. Независимо запустить каждую операцию "
            "можно через меню «Операции»."
        )

    result = dataframe.copy(deep=True)
    affected_columns: list[str] = []
    direct_identifier_columns: list[str] = []
    k_report = None
    applied_operations: list[str] = []

    # k-анонимизация выполняется до обработки прямых идентификаторов,
    # чтобы QI-профили могли использовать исходные значения своих столбцов.
    if K_ANONYMITY in operations:
        from application.k_anonymization_workflow import execute_k_anonymization

        result, k_report = execute_k_anonymization(
            result,
            source_csv_path,
            default_k=default_k,
            representative=representative,
            profile_path=profile_path,
        )
        for component in k_report.get("components", []):
            affected_columns.extend(component.get("attributes", []))
        applied_operations.append(K_ANONYMITY)

    if TOKENIZE_DIRECT_IDENTIFIERS in operations:
        result, columns = anonymize_manual_direct_identifiers(
            result,
            source_csv_path,
            profile_path,
        )
        direct_identifier_columns = list(columns)
        affected_columns.extend(columns)
        applied_operations.append(TOKENIZE_DIRECT_IDENTIFIERS)
    elif REMOVE_DIRECT_IDENTIFIERS in operations:
        result, columns = remove_manual_direct_identifiers(
            result,
            source_csv_path,
            profile_path,
        )
        direct_identifier_columns = list(columns)
        affected_columns.extend(columns)
        applied_operations.append(REMOVE_DIRECT_IDENTIFIERS)

    if k_report is not None:
        k_report["combined_operations"] = applied_operations
        k_report["direct_identifier_columns"] = direct_identifier_columns

    return AnonymizationExecutionResult(
        dataframe=result,
        affected_columns=list(dict.fromkeys(affected_columns)),
        operations=applied_operations,
        k_report=k_report,
    )
