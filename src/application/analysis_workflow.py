from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from data_analysis.correlation import calculate_correlations
from data_analysis.descriptive_statistics import (
    calculate_descriptive_statistics,
    classify_analysis_columns,
)
from infrastructure.attribute_profile_store import (
    DEFAULT_PROFILE_PATH,
    load_manual_role_overrides,
)


@dataclass
class AnalysisResults:
    statistics: pd.DataFrame
    pearson: pd.DataFrame
    spearman: pd.DataFrame
    correlation_n: pd.DataFrame
    included_columns: list[str]
    excluded_columns: list[str]
    column_kinds: dict[str, str]
    date_errors: dict[str, int]
    source_rows: int
    source_columns: int


def run_analysis(
    dataframe: pd.DataFrame,
    csv_path: str | Path,
    profile_path: str | Path = DEFAULT_PROFILE_PATH,
    date_formats: dict[str, str] | None = None,
    min_correlation_periods: int = 3,
) -> AnalysisResults:
    if len(dataframe.columns) == 0:
        raise ValueError("Таблица не содержит столбцов для анализа.")

    manual_overrides = load_manual_role_overrides(csv_path, profile_path)
    excluded_columns = [
        str(column)
        for column in dataframe.columns
        if "direct_identifier" in manual_overrides.get(str(column), [])
    ]
    included_columns = [
        str(column) for column in dataframe.columns
        if str(column) not in excluded_columns
    ]
    if not included_columns:
        raise ValueError(
            "Все столбцы исключены из анализа: каждому назначена роль "
            "direct_identifier. Оставьте хотя бы один анализируемый атрибут."
        )

    analysis_frame = dataframe.loc[:, included_columns].copy(deep=True)
    kinds, parsed_dates, date_errors = classify_analysis_columns(
        analysis_frame,
        date_formats=date_formats,
    )
    statistics = calculate_descriptive_statistics(
        analysis_frame,
        kinds,
        parsed_dates=parsed_dates,
        date_errors=date_errors,
    )
    pearson, spearman, correlation_n = calculate_correlations(
        analysis_frame,
        kinds,
        min_periods=min_correlation_periods,
    )

    return AnalysisResults(
        statistics=statistics,
        pearson=pearson,
        spearman=spearman,
        correlation_n=correlation_n,
        included_columns=included_columns,
        excluded_columns=excluded_columns,
        column_kinds=kinds,
        date_errors=date_errors,
        source_rows=len(dataframe),
        source_columns=len(dataframe.columns),
    )


def export_analysis_results(
    results: AnalysisResults,
    source_path: str | Path,
    output_directory: str | Path,
) -> list[Path]:
    source = Path(source_path)
    directory = Path(output_directory)
    directory.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []

    tables = [
        (results.statistics, f"{source.stem}_statistics.csv", "Показатель"),
        (results.pearson, f"{source.stem}_pearson.csv", "Атрибут"),
        (results.spearman, f"{source.stem}_spearman.csv", "Атрибут"),
    ]
    for table, filename, index_label in tables:
        if table.empty:
            continue
        destination = directory / filename
        table.to_csv(
            destination,
            index=True,
            index_label=index_label,
            encoding="utf-8-sig",
        )
        outputs.append(destination)
    return outputs
