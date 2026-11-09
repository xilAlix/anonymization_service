from pathlib import Path

import pandas as pd

from anonymization.column_removal_adapter import remove_identifier_columns
from anonymization.tokenization_adapter import tokenize_identifier_columns
from infrastructure.attribute_profile_store import (
    DEFAULT_PROFILE_PATH,
    load_manual_role_overrides,
)

TOKENIZE_DIRECT_IDENTIFIERS = "tokenize_direct_identifiers"
REMOVE_DIRECT_IDENTIFIERS = "remove_direct_identifiers"
SUPPORTED_OPERATIONS = {
    TOKENIZE_DIRECT_IDENTIFIERS,
    REMOVE_DIRECT_IDENTIFIERS,
}


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
    return remove_identifier_columns(dataframe, selected_columns), selected_columns


def apply_anonymization_operations(
    dataframe: pd.DataFrame,
    source_csv_path: str | Path,
    operations: list[str],
    profile_path: str | Path = DEFAULT_PROFILE_PATH,
) -> tuple[pd.DataFrame, list[str], str]:
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

    if len(operations) > 1:
        raise ValueError(
            "Токенизация и удаление являются альтернативными способами обработки "
            "одних и тех же прямых идентификаторов. Для суммарной анонимизации "
            "выберите один из этих способов. Независимо запустить каждую операцию "
            "можно через меню «Операции»."
        )

    operation = operations[0]
    if operation == TOKENIZE_DIRECT_IDENTIFIERS:
        result, columns = anonymize_manual_direct_identifiers(
            dataframe,
            source_csv_path,
            profile_path,
        )
    else:
        result, columns = remove_manual_direct_identifiers(
            dataframe,
            source_csv_path,
            profile_path,
        )

    return result, columns, operation
