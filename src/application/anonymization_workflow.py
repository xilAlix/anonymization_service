from pathlib import Path

import pandas as pd

from anonymization.tokenization_adapter import tokenize_identifier_columns
from infrastructure.attribute_profile_store import (
    DEFAULT_PROFILE_PATH,
    load_manual_role_overrides,
)


def anonymize_manual_direct_identifiers(
    dataframe: pd.DataFrame,
    source_csv_path: str | Path,
    profile_path: str | Path = DEFAULT_PROFILE_PATH,
) -> tuple[pd.DataFrame, list[str]]:
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

    anonymized_dataframe = tokenize_identifier_columns(dataframe, selected_columns)
    return anonymized_dataframe, selected_columns
