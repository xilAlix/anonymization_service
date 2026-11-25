from __future__ import annotations

from typing import Any

import pandas as pd

from application.service import analyze_session_result, analyze_session_source
from infrastructure.attribute_profile_store import (
    DEFAULT_PROFILE_PATH,
    load_quasi_identifier_groups,
)
from interfaces.mcp.registry import DatasetRegistry


SAFE_STATISTIC_ROWS = {
    "Количество непустых значений (n)": "non_null_count",
    "Среднее (оценка мат. ожидания)": "mean",
    "Выборочная дисперсия": "sample_variance",
    "Стандартное отклонение": "standard_deviation",
    "Медиана": "median",
    "Q1 (25%)": "q1",
    "Q3 (75%)": "q3",
    "Межквартильный размах (IQR = Q3 − Q1)": "iqr",
    "Уникальные значения": "unique_count",
    "Пропуски": "missing_count",
    "Пропуски, %": "missing_percent",
    "Энтропия (бит)": "entropy_bits",
    "Ошибки распознавания дат": "date_parse_errors",
}


def minimum_group_size(registry: DatasetRegistry, dataset_id: str) -> int:
    threshold = 5
    try:
        session = registry.get_active_session(dataset_id)
        groups = load_quasi_identifier_groups(session.source_path)
        for group in groups:
            if group.get("active", group.get("source") != "automatic"):
                threshold = max(threshold, int(group.get("k_override") or 2))
    except (LookupError, OSError, ValueError):
        pass
    return threshold


def _json_value(value: Any) -> Any:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "item"):
        try:
            value = value.item()
        except (ValueError, TypeError):
            pass
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def serialize_analysis(results, min_group_size: int) -> dict[str, Any]:
    """Builds an aggregate-only payload with suppression of small counts."""
    frame = results.statistics
    source_rows = int(results.source_rows)
    if source_rows < min_group_size:
        return {
            "details_withheld": True,
            "minimum_group_size": min_group_size,
            "statistics": [],
            "correlations": {"pearson": [], "spearman": []},
            "message": "Размер набора меньше минимального порога; агрегированные детали не переданы.",
            "outlier_values_included": False,
            "category_names_included": False,
            "direct_identifier_values_included": False,
            "source_rows_included": False,
        }

    statistics: list[dict[str, Any]] = []
    for column in results.included_columns:
        n = int(frame.loc["Количество непустых значений (n)", column]) if "Количество непустых значений (n)" in frame.index else 0
        missing = int(frame.loc["Пропуски", column]) if "Пропуски" in frame.index and pd.notna(frame.loc["Пропуски", column]) else 0
        item: dict[str, Any] = {
            "attribute": column,
            "kind": results.column_kinds.get(column, "unknown"),
            "suppressed": n < min_group_size,
        }
        if n < min_group_size:
            item["minimum_group_size"] = min_group_size
            statistics.append(item)
            continue

        if missing == 0 or missing >= min_group_size:
            item["non_null_count"] = n
        else:
            item["non_null_count_withheld"] = True
        if missing >= min_group_size:
            item["missing_count"] = missing
            if "Пропуски, %" in frame.index:
                item["missing_percent"] = _json_value(frame.loc["Пропуски, %", column])
        elif missing:
            item["missing_details_withheld"] = True

        unique_for_entropy = None
        if "Уникальные значения" in frame.index:
            unique_for_entropy = _json_value(frame.loc["Уникальные значения", column])
        for row, key in SAFE_STATISTIC_ROWS.items():
            if row not in frame.index or key in {"non_null_count", "missing_count", "missing_percent"}:
                continue
            value = _json_value(frame.loc[row, column])
            if key == "unique_count" and isinstance(value, (int, float)) and value < min_group_size:
                item["unique_count_withheld"] = True
                continue
            if key == "entropy_bits" and isinstance(unique_for_entropy, (int, float)) and unique_for_entropy < min_group_size:
                item["entropy_withheld"] = True
                continue
            if key == "date_parse_errors" and isinstance(value, (int, float)) and 0 < value < min_group_size:
                item["date_error_details_withheld"] = True
                continue
            item[key] = value
        statistics.append(item)

    correlations: dict[str, list[dict[str, Any]]] = {"pearson": [], "spearman": []}
    for method, matrix in (("pearson", results.pearson), ("spearman", results.spearman)):
        for first_index, first in enumerate(matrix.index):
            for second in list(matrix.columns)[first_index + 1:]:
                n = None
                if results.correlation_n is not None and first in results.correlation_n.index and second in results.correlation_n.columns:
                    n = int(results.correlation_n.loc[first, second])
                if n is None or n < min_group_size:
                    continue
                pair_missing = source_rows - n
                if 0 < pair_missing < min_group_size:
                    continue
                coefficient = _json_value(matrix.loc[first, second])
                if coefficient is None:
                    continue
                correlations[method].append({
                    "attribute_1": str(first),
                    "attribute_2": str(second),
                    "coefficient": coefficient,
                    "pair_count": n,
                })

    return {
        "row_count": source_rows,
        "column_count": int(results.source_columns),
        "included_columns": list(results.included_columns),
        "excluded_columns": list(results.excluded_columns),
        "column_kinds": dict(results.column_kinds),
        "statistics": statistics,
        "correlations": correlations,
        "minimum_group_size": min_group_size,
        "outlier_values_included": False,
        "category_names_included": False,
        "direct_identifier_values_included": False,
        "source_rows_included": False,
    }



def _release_summary(release: Any) -> dict[str, Any]:
    if not isinstance(release, dict):
        return {"privacy_status": "not_checked", "privacy_checks": [], "blocked_checks": [], "warning_checks": []}
    checks = [
        {"check": str(item.get("check", "")), "status": str(item.get("status", "unknown"))}
        for item in release.get("checks", [])
        if isinstance(item, dict)
    ]
    return {
        "privacy_status": str(release.get("status", "unknown")),
        "privacy_checks": checks,
        "blocked_checks": [item["check"] for item in checks if item["status"] == "blocked"],
        "warning_checks": [item["check"] for item in checks if item["status"] == "warning"],
    }


def _blocked_release_message(summary: dict[str, Any]) -> str:
    blocked = summary.get("blocked_checks") or []
    if blocked:
        checks_text = ", ".join(blocked)
    else:
        checks_text = "инструмент не передал названия блокирующих проверок"
    return (
        "Подробные метрики сравнения не передаются внешней модели, поскольку текущий "
        f"Privacy Release Check имеет статус blocked. Блокирующие проверки: {checks_text}. "
        "Это ограничение передачи подробных метрик. Сам по себе статус blocked не сообщает, "
        "какие преобразования применились или какие локальные вычисления завершились. "
        "Безопасные статусы проверок приведены отдельно."
    )

def analyze_dataset(
    registry: DatasetRegistry,
    dataset_id: str,
    profile_path: str = str(DEFAULT_PROFILE_PATH),
) -> dict[str, Any]:
    try:
        session = registry.get_active_session(dataset_id)
        results = analyze_session_source(session, profile_path)
        threshold = minimum_group_size(registry, dataset_id)
        safe = serialize_analysis(results, threshold)
        return {"ok": True, "dataset_id": dataset_id, "analysis": safe}
    except LookupError:
        return {"ok": False, "error_code": "dataset_not_open", "message": "Сначала откройте CSV."}
    except (OSError, ValueError) as error:
        return {"ok": False, "error_code": "analysis_failed", "message": str(error)}


def analyze_anonymized_result(
    registry: DatasetRegistry,
    dataset_id: str,
    profile_path: str = str(DEFAULT_PROFILE_PATH),
) -> dict[str, Any]:
    try:
        session = registry.get_active_session(dataset_id)
        release_summary = _release_summary(session.release_check)
        if release_summary["privacy_status"] == "blocked":
            return {
                "ok": True,
                "dataset_id": dataset_id,
                "available": False,
                "details_withheld": True,
                **release_summary,
                "message": _blocked_release_message(release_summary),
            }
        results = analyze_session_result(session, profile_path)
        threshold = minimum_group_size(registry, dataset_id)
        return {
            "ok": True,
            "dataset_id": dataset_id,
            **release_summary,
            "analysis": serialize_analysis(results, threshold),
            "anonymized_result": True,
        }
    except LookupError:
        return {"ok": False, "error_code": "dataset_not_open", "message": "Сначала откройте CSV."}
    except (OSError, ValueError) as error:
        return {"ok": False, "error_code": "result_analysis_failed", "message": str(error)}


def serialize_utility(utility, min_group_size: int) -> dict[str, Any]:
    if utility is None:
        return {"available": False, "message": "Оценка полезности ещё не выполнялась."}

    summary = dict(utility.summary)
    original_rows = int(summary.get("original_rows", 0))
    transformed_rows = int(summary.get("transformed_rows", 0))
    if min(original_rows, transformed_rows) < min_group_size:
        return {
            "available": True,
            "details_withheld": True,
            "minimum_group_size": min_group_size,
            "message": "Размер таблиц меньше минимального порога; детали оценки полезности не переданы.",
        }

    attributes: list[dict[str, Any]] = []
    for _, row in utility.attributes.iterrows():
        n_before = int(row.get("n до", 0))
        n_after = int(row.get("n после", 0))
        if min(n_before, n_after) < min_group_size:
            attributes.append({
                "attribute": str(row.get("Атрибут", "")),
                "suppressed": True,
                "minimum_group_size": min_group_size,
            })
            continue

        item = {
            "attribute": str(row.get("Атрибут", "")),
            "comparison_type": str(row.get("Тип сравнения", "")),
            "mean_before": _json_value(row.get("Среднее до")),
            "mean_after": _json_value(row.get("Среднее после")),
            "mean_change_percent": _json_value(row.get("Изменение среднего, %")),
            "variance_before": _json_value(row.get("Выборочная дисперсия до")),
            "variance_after": _json_value(row.get("Выборочная дисперсия после")),
            "variance_change_percent": _json_value(row.get("Изменение дисперсии, %")),
            "median_before": _json_value(row.get("Медиана до")),
            "median_after": _json_value(row.get("Медиана после")),
            "q1_before": _json_value(row.get("Q1 до")),
            "q1_after": _json_value(row.get("Q1 после")),
            "q3_before": _json_value(row.get("Q3 до")),
            "q3_after": _json_value(row.get("Q3 после")),
            "iqr_before": _json_value(row.get("IQR до")),
            "iqr_after": _json_value(row.get("IQR после")),
            "stddev_before": _json_value(row.get("Стандартное отклонение до")),
            "stddev_after": _json_value(row.get("Стандартное отклонение после")),
            "skewness_before": _json_value(row.get("Асимметрия до")),
            "skewness_after": _json_value(row.get("Асимметрия после")),
            "kurtosis_before": _json_value(row.get("Эксцесс до")),
            "kurtosis_after": _json_value(row.get("Эксцесс после")),
            "entropy_bits_before": _json_value(row.get("Энтропия до, бит")),
            "entropy_bits_after": _json_value(row.get("Энтропия после, бит")),
            "mode_frequency_before": _json_value(row.get("Частота моды до, %")),
            "mode_frequency_after": _json_value(row.get("Частота моды после, %")),
            "categorical_distribution_tvd": _json_value(row.get("TVD категорий")),
            "suppressed": False,
        }
        missing_before = original_rows - n_before
        missing_after = transformed_rows - n_after
        if missing_before == 0 or missing_before >= min_group_size:
            item["non_null_before"] = n_before
            item["missing_count_before"] = missing_before
            item["missing_percent_before"] = _json_value(row.get("Пропуски до, %"))
        else:
            item["non_null_before_withheld"] = True
            item["missing_before_withheld"] = True
        if missing_after == 0 or missing_after >= min_group_size:
            item["non_null_after"] = n_after
            item["missing_count_after"] = missing_after
            item["missing_percent_after"] = _json_value(row.get("Пропуски после, %"))
        else:
            item["non_null_after_withheld"] = True
            item["missing_after_withheld"] = True

        unique_before = _json_value(row.get("Уникальных до"))
        unique_after = _json_value(row.get("Уникальных после"))
        if isinstance(unique_before, (int, float)) and unique_before >= min_group_size:
            item["unique_before"] = unique_before
        elif unique_before is not None:
            item["unique_before_withheld"] = True
        if isinstance(unique_after, (int, float)) and unique_after >= min_group_size:
            item["unique_after"] = unique_after
        elif unique_after is not None:
            item["unique_after_withheld"] = True
        attributes.append(item)

    correlations: list[dict[str, Any]] = []
    for _, row in utility.correlations.iterrows():
        n_before = int(row.get("Парных наблюдений до", 0))
        n_after = int(row.get("Парных наблюдений после", 0))
        if min(n_before, n_after) < min_group_size:
            continue
        missing_before = original_rows - n_before
        missing_after = transformed_rows - n_after
        if (0 < missing_before < min_group_size) or (0 < missing_after < min_group_size):
            continue
        correlations.append({
            "attribute_1": str(row.get("Атрибут 1", "")),
            "attribute_2": str(row.get("Атрибут 2", "")),
            "method": str(row.get("Метод", "")),
            "coefficient_before": _json_value(row.get("Коэффициент до")),
            "coefficient_after": _json_value(row.get("Коэффициент после")),
            "absolute_change": _json_value(row.get("Абсолютное изменение")),
            "pair_count_before": n_before,
            "pair_count_after": n_after,
        })

    return {
        "available": True,
        "summary": summary,
        "attributes": attributes,
        "correlations": correlations,
        "excluded_columns": list(utility.excluded_columns),
        "removed_columns": list(utility.removed_columns),
        "added_columns": list(utility.added_columns),
        "minimum_group_size": min_group_size,
    }


def get_utility_result(registry: DatasetRegistry, dataset_id: str) -> dict[str, Any]:
    try:
        session = registry.get_active_session(dataset_id)
        release_summary = _release_summary(session.release_check)
        if release_summary["privacy_status"] == "blocked":
            return {
                "ok": True,
                "dataset_id": dataset_id,
                **release_summary,
                "utility": {
                    "available": False,
                    "details_withheld": True,
                    "message": _blocked_release_message(release_summary),
                },
            }
        threshold = minimum_group_size(registry, dataset_id)
        return {
            "ok": True,
            "dataset_id": dataset_id,
            **release_summary,
            "utility": serialize_utility(session.utility_evaluation, threshold),
        }
    except LookupError:
        return {"ok": False, "error_code": "dataset_not_open", "message": "Сначала откройте CSV."}



UTILITY_TABLE_FIELDS = {
    "non_null": ("Непустые значения", "non_null_before", "non_null_after", "count"),
    "missing_count": ("Пропуски", "missing_count_before", "missing_count_after", "count"),
    "missing_percent": ("Пропуски, %", "missing_percent_before", "missing_percent_after", "number"),
    "unique": ("Уникальные значения", "unique_before", "unique_after", "count"),
    "mean": ("Среднее", "mean_before", "mean_after", "number"),
    "variance": ("Выборочная дисперсия", "variance_before", "variance_after", "number"),
    "stddev": ("Стандартное отклонение", "stddev_before", "stddev_after", "number"),
    "median": ("Медиана", "median_before", "median_after", "number"),
    "q1": ("Q1 (25%)", "q1_before", "q1_after", "number"),
    "q3": ("Q3 (75%)", "q3_before", "q3_after", "number"),
    "iqr": ("IQR", "iqr_before", "iqr_after", "number"),
    "skewness": ("Асимметрия", "skewness_before", "skewness_after", "number"),
    "kurtosis": ("Эксцесс", "kurtosis_before", "kurtosis_after", "number"),
    "entropy": ("Энтропия, бит", "entropy_bits_before", "entropy_bits_after", "number"),
    "mode_frequency": ("Частота моды, %", "mode_frequency_before", "mode_frequency_after", "number"),
}


def _table_cell(value: Any, kind: str = "number") -> str:
    if value is None:
        return "не рассчитано"
    if isinstance(value, bool):
        return "да" if value else "нет"
    if isinstance(value, (int, float)):
        if kind == "count":
            return f"{int(value):,}".replace(",", " ")
        return f"{float(value):,.2f}".replace(",", " ").replace(".", ",")
    return str(value).replace("|", "\\|").replace("\n", " ")


def get_utility_table(
    registry: DatasetRegistry,
    dataset_id: str,
    attributes: list[str] | None = None,
    metrics: list[str] | None = None,
    include_correlations: bool = False,
) -> dict[str, Any]:
    """Формирует готовую Markdown-таблицу по сохранённой оценке полезности."""
    result = get_utility_result(registry, dataset_id)
    if not result.get("ok"):
        return result
    utility = result.get("utility", {})
    if not utility.get("available") or utility.get("details_withheld"):
        return {
            "ok": True,
            "available": False,
            "privacy_status": result.get("privacy_status", "unknown"),
            "message": utility.get("message", "Сравнение недоступно."),
            "markdown_table": None,
        }

    selected_metrics = metrics or [
        "mean", "variance", "stddev", "median", "q1", "q3", "iqr", "unique", "missing_count", "missing_percent", "entropy"
    ]
    unknown_metrics = [metric for metric in selected_metrics if metric not in UTILITY_TABLE_FIELDS]
    if unknown_metrics:
        return {
            "ok": False,
            "error_code": "unsupported_metrics",
            "message": "Неизвестные показатели: " + ", ".join(unknown_metrics),
            "supported_metrics": sorted(UTILITY_TABLE_FIELDS),
        }

    attribute_rows = utility.get("attributes", [])
    requested = set(attributes or [])
    available_names = [item.get("attribute") for item in attribute_rows]
    if requested:
        unknown_attributes = sorted(requested - set(available_names))
        if unknown_attributes:
            return {
                "ok": False,
                "error_code": "unknown_attributes",
                "message": "Запрошенные атрибуты отсутствуют в сравнении: " + ", ".join(unknown_attributes),
                "available_attributes": available_names,
            }
        attribute_rows = [item for item in attribute_rows if item.get("attribute") in requested]

    lines = [
        "| Атрибут | Показатель | До анонимизации | После анонимизации | Изменение | Изменение, % |",
        "|---|---|---:|---:|---:|---:|",
    ]
    table_rows: list[dict[str, Any]] = []
    for item in attribute_rows:
        attribute = _table_cell(str(item.get("attribute", "—")), "text")
        if item.get("suppressed"):
            lines.append(f"| {attribute} | Все показатели | подавлено | подавлено | — | — |")
            table_rows.append({"attribute": attribute, "suppressed": True})
            continue
        for metric in selected_metrics:
            label, before_key, after_key, value_kind = UTILITY_TABLE_FIELDS[metric]
            before = item.get(before_key)
            after = item.get(after_key)
            suppressed = (
                (item.get("unique_before_withheld") or item.get("unique_after_withheld"))
                if metric == "unique" else False
            ) or (
                (item.get("missing_before_withheld") or item.get("missing_after_withheld"))
                if metric in {"missing_count", "missing_percent"} else False
            )
            if suppressed:
                before_text = after_text = "подавлено"
                delta_text = percent_text = "—"
                delta = percent = None
            else:
                before_text = _table_cell(before, value_kind)
                after_text = _table_cell(after, value_kind)
                if isinstance(before, (int, float)) and isinstance(after, (int, float)):
                    delta = float(after) - float(before)
                    percent = (delta / abs(float(before)) * 100.0) if abs(float(before)) > 1e-15 else None
                    delta_text = _table_cell(delta, "count" if value_kind == "count" else "number")
                    percent_text = _table_cell(percent) + "%" if percent is not None else "не рассчитано"
                else:
                    delta = percent = None
                    delta_text = percent_text = "не рассчитано"
            lines.append(f"| {attribute} | {label} | {before_text} | {after_text} | {delta_text} | {percent_text} |")
            table_rows.append({
                "attribute": attribute,
                "metric": metric,
                "before": before,
                "after": after,
                "absolute_change": delta,
                "percent_change": percent,
                "suppressed": bool(suppressed),
            })

    if include_correlations:
        lines.extend([
            "", "**Корреляции**", "",
            "| Атрибуты | Метод | До | После | Абсолютное изменение |",
            "|---|---|---:|---:|---:|",
        ])
        for item in utility.get("correlations", []):
            lines.append(
                f"| {_table_cell(item.get('attribute_1'), 'text')} / {_table_cell(item.get('attribute_2'), 'text')} | {_table_cell(item.get('method'), 'text')} | "
                f"{_table_cell(item.get('coefficient_before'))} | {_table_cell(item.get('coefficient_after'))} | "
                f"{_table_cell(item.get('absolute_change'))} |"
            )

    summary = utility.get("summary", {})
    lines.extend([
        "",
        "**Изменение структуры набора**",
        "",
        "| Показатель | Значение |",
        "|---|---:|",
        f"| Строк до | {_table_cell(summary.get('original_rows'), 'count')} |",
        f"| Строк после | {_table_cell(summary.get('transformed_rows'), 'count')} |",
        f"| Общих атрибутов | {_table_cell(summary.get('common_columns'), 'count')} |",
        f"| Удалено атрибутов | {_table_cell(summary.get('removed_columns'), 'count')} |",
        f"| Добавлено атрибутов | {_table_cell(summary.get('added_columns'), 'count')} |",
    ])
    removed_columns = utility.get("removed_columns", [])
    added_columns = utility.get("added_columns", [])
    if removed_columns:
        lines.append("\nУдалённые атрибуты: " + ", ".join(_table_cell(name, "text") for name in removed_columns))
    if added_columns:
        lines.append("\nДобавленные атрибуты: " + ", ".join(_table_cell(name, "text") for name in added_columns))
    lines.extend([
        "",
        f"Статус Privacy Release Check: **{result.get('privacy_status', 'unknown')}**.",
        "Примечание: сравнение описывает статистические изменения и само по себе не доказывает приватность.",
    ])
    return {
        "ok": True,
        "available": True,
        "format": "markdown",
        "privacy_status": result.get("privacy_status", "unknown"),
        "selected_attributes": [item.get("attribute") for item in attribute_rows],
        "selected_metrics": list(selected_metrics),
        "table_rows": table_rows,
        "markdown_table": "\n".join(lines),
        "removed_columns": utility.get("removed_columns", []),
        "added_columns": utility.get("added_columns", []),
        "instruction": "Передай markdown_table пользователю без изменения структуры таблицы.",
    }

def get_privacy_result(registry: DatasetRegistry, dataset_id: str) -> dict[str, Any]:
    try:
        session = registry.get_active_session(dataset_id)
        release = session.release_check
        if not release:
            return {"ok": True, "available": False, "message": "Privacy Release Check ещё не выполнялся."}
        summary = _release_summary(release)
        status = summary["privacy_status"]
        checks = summary["privacy_checks"]
        if status == "blocked":
            return {
                "ok": True,
                "available": True,
                "status": status,
                "checks": checks,
                "blocked_checks": summary["blocked_checks"],
                "warning_checks": summary["warning_checks"],
                "details_withheld": True,
                "message": _blocked_release_message(summary),
            }
        return {
            "ok": True,
            "available": True,
            "status": status,
            "checks": checks,
            "blocked_checks": summary["blocked_checks"],
            "warning_checks": summary["warning_checks"],
            "limitations": [
                "Статус не гарантирует абсолютную анонимность.",
                "Не проверяются неизвестные внешние источники связывания данных.",
            ],
        }
    except LookupError:
        return {"ok": False, "error_code": "dataset_not_open", "message": "Сначала откройте CSV."}
