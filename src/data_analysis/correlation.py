from __future__ import annotations

import pandas as pd
from pandas.api.types import is_bool_dtype, is_numeric_dtype


def calculate_correlations(
    dataframe: pd.DataFrame,
    column_kinds: dict[str, str],
    min_periods: int = 3,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if min_periods < 3:
        raise ValueError("По спецификации 0.5.0 корреляция рассчитывается минимум по 3 парам наблюдений.")

    numeric_columns = [
        str(column)
        for column in dataframe.columns
        if column_kinds.get(str(column)) == "numeric"
        and is_numeric_dtype(dataframe[column].dtype)
        and not is_bool_dtype(dataframe[column].dtype)
    ]

    if not numeric_columns:
        empty = pd.DataFrame(dtype=float)
        empty.index.name = "Атрибут"
        return empty.copy(), empty.copy(), empty.copy()

    numeric = dataframe.loc[:, numeric_columns]
    size = len(numeric_columns)
    pearson = pd.DataFrame(index=numeric_columns, columns=numeric_columns, dtype=float)
    spearman = pd.DataFrame(index=numeric_columns, columns=numeric_columns, dtype=float)
    pair_counts = pd.DataFrame(index=numeric_columns, columns=numeric_columns, dtype="int64")

    for left_index, left_name in enumerate(numeric_columns):
        for right_name in numeric_columns[left_index:]:
            left = numeric[left_name]
            right = numeric[right_name]
            valid = left.notna() & right.notna()
            pair_left = left.loc[valid]
            pair_right = right.loc[valid]
            count = int(valid.sum())

            pair_counts.loc[left_name, right_name] = count
            pair_counts.loc[right_name, left_name] = count

            pearson_value = float("nan")
            spearman_value = float("nan")
            if count >= min_periods and pair_left.nunique() > 1 and pair_right.nunique() > 1:
                pearson_value = float(pair_left.corr(pair_right, method="pearson"))
                left_ranks = pair_left.rank(method="average")
                right_ranks = pair_right.rank(method="average")
                spearman_value = float(left_ranks.corr(right_ranks, method="pearson"))

            if left_name == right_name and count >= min_periods and pair_left.nunique() > 1:
                pearson_value = 1.0
                spearman_value = 1.0

            pearson.loc[left_name, right_name] = pearson_value
            pearson.loc[right_name, left_name] = pearson_value
            spearman.loc[left_name, right_name] = spearman_value
            spearman.loc[right_name, left_name] = spearman_value

    pearson.index.name = "Атрибут"
    spearman.index.name = "Атрибут"
    pair_counts = pair_counts.astype("int64")
    pair_counts.index.name = "Атрибут"
    return pearson, spearman, pair_counts
