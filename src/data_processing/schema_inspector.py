from pandas import DataFrame


def get_column_types(dataframe: DataFrame) -> list[tuple[str, str]]:
    return [
        (str(column), str(dtype))
        for column, dtype in dataframe.dtypes.items()
    ]
