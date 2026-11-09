import pandas as pd


def remove_identifier_columns(
    dataframe: pd.DataFrame,
    columns: list[str],
) -> pd.DataFrame:
    if not columns:
        raise ValueError("Не выбраны столбцы для удаления.")

    missing_columns = [column for column in columns if column not in dataframe.columns]
    if missing_columns:
        raise ValueError(
            "В таблице отсутствуют назначенные столбцы: "
            + ", ".join(missing_columns)
        )

    if len(columns) != len(set(columns)):
        raise ValueError("Список столбцов для удаления содержит повторы.")

    return dataframe.drop(columns=columns).copy(deep=True)
