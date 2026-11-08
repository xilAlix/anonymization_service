from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class ColumnTypeResult:
    attribute: str
    pandas_type: str
    unique_count: int | None
    non_null_count: int | None
    unique_percent: float | None
    is_nominal: bool | None


def analyze_column_types(
    dataframe: pd.DataFrame,
    detect_nominal_attributes: bool = False,
    nominal_unique_threshold_percent: float = 10.0,
) -> list[ColumnTypeResult]:
    if not 0 <= nominal_unique_threshold_percent <= 100:
        raise ValueError(
            "Порог номинальности должен находиться "
            "в диапазоне от 0 до 100."
        )
    results: list[ColumnTypeResult] = []

    for column, dtype in dataframe.dtypes.items():
        unique_count = None
        non_null_count = None
        unique_percent = None
        is_nominal = None

        if detect_nominal_attributes:
            values = dataframe[column].dropna()
            non_null_count = int(values.size)
            unique_count = int(values.nunique(dropna=True))
            if non_null_count:
                unique_percent = unique_count / non_null_count * 100
                is_nominal = unique_percent <= nominal_unique_threshold_percent

        results.append(
            ColumnTypeResult(
                attribute=str(column),
                pandas_type=str(dtype),
                unique_count=unique_count,
                non_null_count=non_null_count,
                unique_percent=unique_percent,
                is_nominal=is_nominal,
            )
        )

    return results
