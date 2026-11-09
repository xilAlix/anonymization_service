import secrets

import pandas as pd

from anonymization.algorithms.tokenization import tokenize_values


def tokenize_identifier_columns(
    dataframe: pd.DataFrame,
    columns: list[str],
) -> pd.DataFrame:
    if not columns:
        raise ValueError("Не выбраны столбцы для токенизации.")

    missing_columns = [column for column in columns if column not in dataframe.columns]
    if missing_columns:
        raise ValueError(
            "В таблице отсутствуют назначенные столбцы: "
            + ", ".join(missing_columns)
        )

    if len(columns) != len(set(columns)):
        raise ValueError("Список столбцов для токенизации содержит повторы.")

    result = dataframe.copy(deep=True)
    issued_tokens: set[str] = set()

    def create_token() -> str:
        while True:
            token = f"ID_{secrets.token_hex(8).upper()}"
            if token not in issued_tokens:
                issued_tokens.add(token)
                return token

    for column in columns:
        normalized_values = [
            None if pd.isna(value) else value
            for value in result[column].tolist()
        ]
        result[column] = pd.Series(
            tokenize_values(normalized_values, create_token),
            index=result.index,
            dtype="object",
        )

    return result
