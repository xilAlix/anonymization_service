from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from typing import Any

import numpy as np
import pandas as pd

from anonymization.algorithms.mdav import mdav_partition
from anonymization.algorithms.mixed_distance import MixedRecordDistance, parse_date_value


MISSING_LABEL = "<ПРОПУСК>"
SUPPRESSION_LABEL = "*"


def _is_missing(value: Any) -> bool:
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _is_date_column(series: pd.Series) -> bool:
    if pd.api.types.is_datetime64_any_dtype(series.dtype):
        return True
    sample = series.dropna().astype(str).head(100)
    if sample.empty:
        return False
    patterns = (
        r"^\d{4}-\d{1,2}-\d{1,2}(?:[T ].*)?$",
        r"^\d{1,2}[./-]\d{1,2}[./-]\d{2,4}$",
        r"^\d{4}/\d{1,2}/\d{1,2}$",
    )
    return bool(sample.str.match("|".join(f"(?:{pattern})" for pattern in patterns)).mean() >= 0.85)


def _group_count(frame: pd.DataFrame, columns: list[str]) -> tuple[int, int]:
    if not columns:
        return 0, 0
    grouper = columns[0] if len(columns) == 1 else columns
    counts = frame.groupby(grouper, dropna=False, sort=False).size()
    return (int(counts.min()) if len(counts) else 0, int(len(counts)))


def evaluate_qi_profiles(
    dataframe: pd.DataFrame,
    profiles: list[dict],
    default_k: int,
) -> list[dict]:
    results: list[dict] = []
    for profile in profiles:
        columns = list(profile["attributes"])
        required_k = int(profile.get("k_override") or default_k)
        missing_columns = [column for column in columns if column not in dataframe.columns]
        if missing_columns:
            raise ValueError(
                f"В QI-профиле «{profile['name']}» отсутствуют столбцы: "
                + ", ".join(missing_columns)
            )
        minimum_size, equivalence_classes = _group_count(dataframe, columns)
        results.append({
            "group_id": profile["id"],
            "group_name": profile["name"],
            "attributes": columns,
            "required_k": required_k,
            "minimum_equivalence_class_size": minimum_size,
            "equivalence_class_count": equivalence_classes,
            "satisfied": minimum_size >= required_k,
        })
    return results


def _connected_components(profiles: list[dict], correlation_blocks: list[dict]) -> list[dict]:
    profile_count = len(profiles)
    node_count = profile_count + len(correlation_blocks)
    parent = list(range(node_count))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(first: int, second: int) -> None:
        first_root = find(first)
        second_root = find(second)
        if first_root != second_root:
            parent[second_root] = first_root

    profile_sets = [set(profile["attributes"]) for profile in profiles]
    block_sets = [set(block.get("attributes", [])) for block in correlation_blocks]

    for first in range(profile_count):
        for second in range(first + 1, profile_count):
            if profile_sets[first] & profile_sets[second]:
                union(first, second)

    for block_index, block_columns in enumerate(block_sets):
        block_node = profile_count + block_index
        for profile_index, profile_columns in enumerate(profile_sets):
            if block_columns & profile_columns:
                union(block_node, profile_index)
        for other_index in range(block_index):
            if block_columns & block_sets[other_index]:
                union(block_node, profile_count + other_index)

    profile_components: dict[int, list[int]] = defaultdict(list)
    for index in range(profile_count):
        profile_components[find(index)].append(index)

    result: list[dict] = []
    for component_index, (root, indices) in enumerate(profile_components.items(), start=1):
        component_profiles = [profiles[index] for index in indices]
        columns: list[str] = []
        for profile in component_profiles:
            for column in profile["attributes"]:
                if column not in columns:
                    columns.append(column)

        related_blocks = []
        for block_index, block in enumerate(correlation_blocks):
            if find(profile_count + block_index) != root:
                continue
            block_columns = list(block.get("attributes", []))
            related_blocks.append({**block, "attributes": block_columns})
            for column in block_columns:
                if column not in columns:
                    columns.append(column)

        required_k = max(int(profile.get("k_override") or 0) for profile in component_profiles)
        result.append({
            "id": f"block_{component_index}",
            "profiles": component_profiles,
            "columns": columns,
            "required_k_override": required_k,
            "correlation_blocks": related_blocks,
        })
    return result


def profiles_columns(profiles: list[dict]) -> set[str]:
    return {column for profile in profiles for column in profile["attributes"]}


def _date_generalization(values: list[Any]) -> tuple[Any, int, bool]:
    parsed = [parse_date_value(value) if not _is_missing(value) else pd.NaT for value in values]
    if all(pd.isna(value) for value in parsed):
        return pd.NA, 0, False
    if any(pd.isna(value) for value in parsed):
        return SUPPRESSION_LABEL, 3, True
    exact = [value.strftime("%Y-%m-%d") for value in parsed]
    if len(set(exact)) == 1:
        return exact[0], 0, False
    months = [value.strftime("%Y-%m") for value in parsed]
    if len(set(months)) == 1:
        return months[0], 1, False
    years = [value.strftime("%Y") for value in parsed]
    if len(set(years)) == 1:
        return years[0], 2, False
    return SUPPRESSION_LABEL, 3, True


def _categorical_generalization(
    values: list[Any],
    hierarchy_levels: list[dict],
) -> tuple[Any, int, bool]:
    if all(_is_missing(value) for value in values):
        return pd.NA, 0, False
    if any(_is_missing(value) for value in values):
        return SUPPRESSION_LABEL, len(hierarchy_levels) + 1, True
    normalized = [str(value) for value in values]
    if len(set(normalized)) == 1:
        return values[0], 0, False

    current = normalized
    for level_index, mapping in enumerate(hierarchy_levels, start=1):
        if not isinstance(mapping, dict):
            continue
        current = [str(mapping.get(value, value)) for value in current]
        if len(set(current)) == 1:
            return current[0], level_index, False
    return SUPPRESSION_LABEL, len(hierarchy_levels) + 1, True


def _numeric_medoid_index(
    indices: list[int],
    distance: MixedRecordDistance,
) -> int:
    totals = {
        index: sum(distance.distance_between(index, other) for other in indices)
        for index in indices
    }
    return min(indices, key=lambda index: (totals[index], index))


def _round_to_integer(value: float) -> int:
    """Округляет половинные значения от нуля, сохраняя целочисленный смысл поля."""
    return int(np.sign(value) * np.floor(abs(value) + 0.5))


def _has_integer_semantics(series: pd.Series) -> bool:
    if pd.api.types.is_integer_dtype(series.dtype):
        return True
    if not pd.api.types.is_float_dtype(series.dtype) or not series.isna().any():
        return False
    numeric = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    if numeric.empty:
        return False
    values = numeric.to_numpy(dtype=float)
    return bool(np.equal(values, np.trunc(values)).all())


def _nullable_integer_dtype(dtype: Any) -> str:
    dtype_name = str(dtype).lower()
    mapping = {
        "int8": "Int8",
        "int16": "Int16",
        "int32": "Int32",
        "int64": "Int64",
        "uint8": "UInt8",
        "uint16": "UInt16",
        "uint32": "UInt32",
        "uint64": "UInt64",
    }
    return mapping.get(dtype_name, "Int64")


def _restore_numeric_series(
    original: pd.Series,
    values: list[Any],
    index: pd.Index,
    integer_semantics: bool,
) -> pd.Series:
    dtype = original.dtype
    if integer_semantics:
        if pd.api.types.is_integer_dtype(dtype):
            integer_dtype = _nullable_integer_dtype(dtype)
        else:
            integer_dtype = "Int64"
        if any(_is_missing(value) for value in values):
            return pd.Series(values, index=index, dtype=integer_dtype)
        if pd.api.types.is_integer_dtype(dtype):
            return pd.Series(values, index=index, dtype=dtype)
        return pd.Series(values, index=index, dtype="int64")

    if pd.api.types.is_float_dtype(dtype):
        normalized = [np.nan if _is_missing(value) else value for value in values]
        return pd.Series(normalized, index=index, dtype=dtype)

    non_missing = original.dropna()
    if len(non_missing) and non_missing.map(lambda value: isinstance(value, str)).all():
        normalized = [
            pd.NA if _is_missing(value) else str(value)
            for value in values
        ]
        return pd.Series(normalized, index=index, dtype=object)

    return pd.Series(values, index=index, dtype=object)


def microaggregate_component(
    dataframe: pd.DataFrame,
    component: dict,
    k: int,
    representative: str = "mean",
    hierarchies: dict[str, list[dict]] | None = None,
) -> tuple[pd.DataFrame, dict]:
    columns = list(component["columns"])
    missing = [column for column in columns if column not in dataframe.columns]
    if missing:
        raise ValueError(f"В профиле отсутствуют столбцы: {', '.join(missing)}")
    if representative not in {"mean", "median", "medoid"}:
        raise ValueError("Представитель группы должен быть mean, median или medoid.")

    distance = MixedRecordDistance(dataframe, columns)
    row_indices = list(range(len(dataframe)))
    clusters = mdav_partition(
        row_indices,
        k,
        distance.centroid,
        distance.distance_to_centroid,
        distance.distance_between,
    )

    result = dataframe.copy(deep=True)
    hierarchy_map = hierarchies or {}
    suppression_counts: dict[str, int] = defaultdict(int)
    generalization_levels: dict[str, int] = defaultdict(int)
    cluster_details: list[dict] = []
    numeric_within_group_sse: dict[str, float] = defaultdict(float)
    normalized_numeric_within_group_sse: dict[str, float] = defaultdict(float)
    column_operations: dict[str, str] = {}
    transformed_values = {
        column: dataframe[column].tolist()
        for column in columns
    }
    metric_by_column = {metric.name: metric for metric in distance.metrics}
    numeric_columns = [metric.name for metric in distance.metrics if metric.kind == "numeric"]
    integer_semantics = {
        column: _has_integer_semantics(dataframe[column])
        for column in numeric_columns
    }

    for cluster_number, indices in enumerate(clusters, start=1):
        medoid_index = (
            _numeric_medoid_index(indices, distance)
            if representative == "medoid" and numeric_columns
            else None
        )
        for column in columns:
            metric = metric_by_column[column]
            source_values = dataframe.iloc[indices][column].tolist()
            if metric.kind == "numeric":
                numeric_values = pd.to_numeric(
                    dataframe.iloc[indices][column], errors="coerce"
                ).replace([np.inf, -np.inf], np.nan)
                valid_values = numeric_values.dropna().astype(float)
                if numeric_values.isna().all():
                    value = pd.NA
                elif numeric_values.isna().any():
                    value = pd.NA
                    suppression_counts[column] += len(indices)
                else:
                    group_mean = float(valid_values.mean())
                    if representative == "median":
                        value = float(valid_values.median())
                    elif representative == "medoid":
                        value = dataframe.iloc[medoid_index][column]
                    else:
                        value = group_mean

                    if integer_semantics[column]:
                        value = int(value) if representative == "medoid" else _round_to_integer(float(value))
                    elif pd.api.types.is_float_dtype(dataframe[column].dtype):
                        value = float(value)

                    published_center = float(value)
                    raw_sse = float(((valid_values - published_center) ** 2).sum())
                    scale = metric.scale
                    numeric_within_group_sse[column] += raw_sse
                    normalized_numeric_within_group_sse[column] += raw_sse / (scale ** 2)

                for index in indices:
                    transformed_values[column][index] = value
                column_operations[column] = f"микроагрегация ({representative})"
            elif metric.kind == "date":
                value, level, suppressed = _date_generalization(source_values)
                for index in indices:
                    transformed_values[column][index] = value
                generalization_levels[column] = max(generalization_levels[column], level)
                if suppressed:
                    suppression_counts[column] += len(indices)
                column_operations[column] = "обобщение даты по уровням: день → месяц → год; иначе подавление"
            else:
                value, level, suppressed = _categorical_generalization(
                    source_values,
                    hierarchy_map.get(column, []),
                )
                for index in indices:
                    transformed_values[column][index] = value
                generalization_levels[column] = max(generalization_levels[column], level)
                if suppressed:
                    suppression_counts[column] += len(indices)
                column_operations[column] = "пользовательская иерархия категорий; иначе подавление"
        cluster_details.append({"cluster": cluster_number, "size": len(indices)})

    for column in columns:
        metric = metric_by_column[column]
        if metric.kind == "numeric":
            result[column] = _restore_numeric_series(
                dataframe[column],
                transformed_values[column],
                dataframe.index,
                integer_semantics[column],
            )
        else:
            result[column] = pd.Series(
                transformed_values[column],
                index=dataframe.index,
                dtype=object,
            )

    return result, {
        "component_id": component["id"],
        "profiles": [
            {"id": profile["id"], "name": profile["name"]}
            for profile in component["profiles"]
        ],
        "attributes": columns,
        "required_k": k,
        "clusters": cluster_details,
        "cluster_count": len(clusters),
        "minimum_cluster_size": min(map(len, clusters)),
        "maximum_cluster_size": max(map(len, clusters)),
        "cell_suppression_counts": dict(suppression_counts),
        "generalization_levels": dict(generalization_levels),
        "column_operations": column_operations,
        "numeric_within_group_sse": dict(numeric_within_group_sse),
        "normalized_numeric_within_group_sse": dict(normalized_numeric_within_group_sse),
        "algorithm": "MDAV with robust feature scaling" if distance.numeric_only else "Gower-style mixed-distance MDAV adaptation",
        "distance": "robust-scaled Euclidean" if distance.numeric_only else "Gower-style mixed distance",
        "representative": representative,
    }


def anonymize_k_anonymity(
    dataframe: pd.DataFrame,
    profiles: list[dict],
    default_k: int = 5,
    representative: str = "mean",
    hierarchies: dict[str, list[dict]] | None = None,
    correlation_blocks: list[dict] | None = None,
) -> tuple[pd.DataFrame, dict]:
    if dataframe.empty:
        raise ValueError("Нельзя выполнить k-анонимизацию пустой таблицы.")
    if isinstance(default_k, bool) or not isinstance(default_k, int) or default_k < 2:
        raise ValueError("Общее значение k должно быть целым числом не меньше 2.")
    active_profiles = [profile for profile in profiles if profile.get("active", False)]
    if not active_profiles:
        raise ValueError(
            "Нет активных QI-профилей. Подтвердите автоматические группы или создайте группу вручную."
        )

    normalized_profiles: list[dict] = []
    for profile in active_profiles:
        columns = list(profile.get("attributes", []))
        if not columns:
            raise ValueError(f"QI-профиль «{profile.get('name', profile.get('id'))}» пуст.")
        required_k = profile.get("k_override") or default_k
        if isinstance(required_k, bool) or not isinstance(required_k, int) or required_k < 2:
            raise ValueError(f"В QI-профиле «{profile['name']}» задан некорректный k.")
        normalized_profiles.append({**profile, "attributes": columns, "k_override": required_k})

    for profile in normalized_profiles:
        missing = [column for column in profile["attributes"] if column not in dataframe.columns]
        if missing:
            raise ValueError(
                f"В QI-профиле «{profile['name']}» отсутствуют столбцы: {', '.join(missing)}"
            )

    components = _connected_components(normalized_profiles, correlation_blocks or [])
    result = dataframe.copy(deep=True)
    component_reports: list[dict] = []

    for component in components:
        component_k = max(
            int(profile.get("k_override") or default_k)
            for profile in component["profiles"]
        )
        result, component_report = microaggregate_component(
            result,
            component,
            component_k,
            representative,
            hierarchies,
        )
        component_reports.append(component_report)

    profile_reports = evaluate_qi_profiles(result, normalized_profiles, default_k)
    failures = [report for report in profile_reports if not report["satisfied"]]
    if failures:
        details = "; ".join(
            f"{item['group_name']}: минимум {item['minimum_equivalence_class_size']}, "
            f"требуется {item['required_k']}"
            for item in failures
        )
        raise RuntimeError(
            "После преобразования не удалось подтвердить k-анонимность: " + details
        )

    utility = _utility_report(dataframe, result)
    report = {
        "status": "satisfied",
        "default_k": default_k,
        "input_rows": int(len(dataframe)),
        "output_rows": int(len(result)),
        "row_suppression_count": 0,
        "components": component_reports,
        "profiles": profile_reports,
        "utility": utility,
        "notes": [
            "MDAV является эвристикой и не гарантирует глобально оптимального разбиения.",
            "Gower-MDAV adaptation является реализацией проекта, а не классическим MDAV для смешанных данных.",
            "Соблюдение k проверяется на результирующей таблице для каждого активного QI-профиля.",
            "Категориальные значения без общей пользовательской иерархии подавляются символом '*'.",
            "Корреляции измеряются, но не гарантируется их точное сохранение.",
            "Результат k-анонимности не гарантирует l-разнообразие, t-близость или дифференциальную приватность.",
        ],
    }
    return result, report


def _utility_report(original: pd.DataFrame, transformed: pd.DataFrame) -> dict:
    def is_numeric_feature(column: str) -> bool:
        series = original[column]
        if pd.api.types.is_bool_dtype(series.dtype):
            return False
        tokens = set(str(column).casefold().replace("-", "_").split("_"))
        if tokens & {"id", "identifier", "postal", "postcode", "zip", "pin", "pincode", "phone", "account", "passport"}:
            return False
        if pd.api.types.is_numeric_dtype(series.dtype):
            return True
        converted = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan)
        non_missing = int(series.notna().sum())
        return bool(non_missing and converted.notna().sum() / non_missing >= 0.9)

    numeric_columns = [column for column in original.columns if is_numeric_feature(column)]
    numeric_before = {
        column: pd.to_numeric(original[column], errors="coerce").replace([np.inf, -np.inf], np.nan)
        for column in numeric_columns
    }
    numeric_after = {
        column: pd.to_numeric(transformed[column], errors="coerce").replace([np.inf, -np.inf], np.nan)
        for column in numeric_columns
    }
    columns: dict[str, dict] = {}
    for column in numeric_columns:
        before = numeric_before[column]
        after = numeric_after[column]
        mean_before = float(before.mean()) if before.notna().any() else None
        mean_after = float(after.mean()) if after.notna().any() else None
        variance_before = float(before.var(ddof=0)) if before.notna().any() else None
        variance_after = float(after.var(ddof=0)) if after.notna().any() else None
        quantiles = {}
        for quantile in (0.25, 0.5, 0.75):
            before_q = before.quantile(quantile)
            after_q = after.quantile(quantile)
            quantiles[str(quantile)] = {
                "before": None if pd.isna(before_q) else float(before_q),
                "after": None if pd.isna(after_q) else float(after_q),
                "absolute_change": None if pd.isna(before_q) or pd.isna(after_q) else float(abs(before_q - after_q)),
            }
        columns[str(column)] = {
            "mean_before": mean_before,
            "mean_after": mean_after,
            "mean_absolute_change": abs(mean_before - mean_after) if mean_before is not None and mean_after is not None else None,
            "variance_before": variance_before,
            "variance_after": variance_after,
            "variance_absolute_change": abs(variance_before - variance_after) if variance_before is not None and variance_after is not None else None,
            "quantiles": quantiles,
        }

    correlations: dict[str, dict] = {}
    before_frame = pd.DataFrame(numeric_before)
    after_frame = pd.DataFrame(numeric_after)
    for method in ("pearson", "spearman"):
        correlations[method] = {}
        if len(numeric_columns) >= 2:
            before_corr = before_frame.corr(method=method)
            after_corr = after_frame.corr(method=method)
            for first_index, first in enumerate(numeric_columns):
                for second in numeric_columns[first_index + 1:]:
                    before_value = before_corr.loc[first, second]
                    after_value = after_corr.loc[first, second]
                    correlations[method][f"{first} | {second}"] = {
                        "before": None if pd.isna(before_value) else float(before_value),
                        "after": None if pd.isna(after_value) else float(after_value),
                        "absolute_change": None if pd.isna(before_value) or pd.isna(after_value) else float(abs(before_value - after_value)),
                    }

    categorical_columns = [column for column in original.columns if column not in numeric_columns]
    distributions: dict[str, dict] = {}
    for column in categorical_columns:
        before = original[column].astype("string").fillna(MISSING_LABEL).value_counts(normalize=True)
        after = transformed[column].astype("string").fillna(MISSING_LABEL).value_counts(normalize=True)
        categories = set(before.index) | set(after.index)
        total_variation = 0.5 * sum(abs(float(before.get(value, 0.0)) - float(after.get(value, 0.0))) for value in categories)
        distributions[str(column)] = {
            "total_variation_distance": float(total_variation),
            "unique_values_before": int(original[column].nunique(dropna=False)),
            "unique_values_after": int(transformed[column].nunique(dropna=False)),
            "missing_ratio_before": float(original[column].isna().mean()),
            "missing_ratio_after": float(transformed[column].isna().mean()),
        }

    return {
        "numeric_columns": columns,
        "pearson_correlations": correlations["pearson"],
        "spearman_correlations": correlations["spearman"],
        "categorical_distributions": distributions,
        "optimization_note": "Критерии показываются раздельно. В данной реализации нет единого взвешенного целевого балла и глобального многокритериального оптимизатора.",
        "note": "Метрики описывают изменения данных. Они не являются гарантиями приватности.",
    }
