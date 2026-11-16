from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from application.analysis_workflow import AnalysisResults, run_analysis
from application.anonymization_workflow import (
    K_ANONYMITY,
    REMOVE_DIRECT_IDENTIFIERS,
    TOKENIZE_DIRECT_IDENTIFIERS,
    AnonymizationExecutionResult,
    apply_anonymization_operations,
)
from application.session_workflow import DatasetSession
from data_processing.csv_handler import save_csv
from evaluation.privacy.release_check import evaluate_release_readiness
from evaluation.utility.utility_evaluator import UtilityEvaluation, evaluate_utility
from infrastructure.attribute_profile_store import (
    DEFAULT_PROFILE_PATH,
    load_manual_role_overrides,
    load_quasi_identifier_groups,
)


@dataclass
class SessionExecutionResult:
    execution: AnonymizationExecutionResult
    release_check: dict[str, Any]
    utility: UtilityEvaluation
    output_path: Path


def prepare_anonymization_plan(
    session: DatasetSession,
    operations: list[str],
    default_k: int = 5,
    enable_l_diversity: bool = False,
    default_l: int = 2,
    l_variant: str = "both",
    profile_path: str | Path = DEFAULT_PROFILE_PATH,
) -> dict[str, Any]:
    """Формирует проверяемый план без изменения таблицы и файлов."""
    if not operations:
        raise ValueError("Не выбрана ни одна операция анонимизации.")
    supported = {TOKENIZE_DIRECT_IDENTIFIERS, REMOVE_DIRECT_IDENTIFIERS, K_ANONYMITY}
    unknown = sorted(set(operations) - supported)
    if unknown:
        raise ValueError("Неизвестные операции: " + ", ".join(unknown))
    if len(operations) != len(set(operations)):
        raise ValueError("В плане обнаружены повторяющиеся операции.")
    if TOKENIZE_DIRECT_IDENTIFIERS in operations and REMOVE_DIRECT_IDENTIFIERS in operations:
        raise ValueError("Токенизация и удаление прямых идентификаторов являются альтернативными операциями.")

    roles = load_manual_role_overrides(session.source_path, profile_path)
    direct = [
        column for column, assigned in roles.items()
        if "direct_identifier" in assigned and column in session.source_dataframe.columns
    ]
    if ({TOKENIZE_DIRECT_IDENTIFIERS, REMOVE_DIRECT_IDENTIFIERS} & set(operations)) and not direct:
        raise ValueError(
            "Для текущей таблицы вручную не назначен ни один прямой идентификатор. "
            "Назначьте роль direct_identifier в классификации атрибутов."
        )

    groups = load_quasi_identifier_groups(session.source_path, profile_path)
    active_groups = [
        group for group in groups
        if group.get("active", group.get("source") != "automatic")
    ]
    if K_ANONYMITY in operations:
        if isinstance(default_k, bool) or not isinstance(default_k, int) or default_k < 2:
            raise ValueError("Значение k должно быть целым числом не меньше 2.")
        if not active_groups:
            raise ValueError("Для k-анонимизации необходимо подтвердить хотя бы один QI-профиль.")
        for group in active_groups:
            absent = [column for column in group["attributes"] if column not in session.source_dataframe.columns]
            if absent:
                raise ValueError(
                    f"QI-профиль «{group['name']}» ссылается на отсутствующие столбцы: "
                    + ", ".join(absent)
                )
            direct_in_qi = [column for column in group["attributes"] if column in direct]
            if direct_in_qi:
                raise ValueError(
                    f"QI-профиль «{group['name']}» содержит прямые идентификаторы: "
                    + ", ".join(direct_in_qi)
                    + ". Удалите их из QI-профиля: прямые идентификаторы обрабатываются отдельно."
                )

    sensitive = [
        column for column, assigned in roles.items()
        if "sensitive_attribute" in assigned
        and "direct_identifier" not in assigned
        and column in session.source_dataframe.columns
    ]
    excluded_sensitive = [
        column for column, assigned in roles.items()
        if "sensitive_attribute" in assigned
        and "direct_identifier" in assigned
        and column in session.source_dataframe.columns
    ]
    plan_warnings: list[str] = []
    if enable_l_diversity and K_ANONYMITY in operations:
        if isinstance(default_l, bool) or not isinstance(default_l, int) or default_l < 2:
            raise ValueError("Значение l должно быть целым числом не меньше 2.")
        if l_variant not in {"distinct", "entropy", "both"}:
            raise ValueError("Вариант l-проверки должен быть distinct, entropy или both.")
        if not sensitive:
            plan_warnings.append(
                "Нет подходящих конфиденциальных атрибутов для l-проверки. "
                "Исполнитель сформирует подробную диагностику not_evaluable."
            )
        if excluded_sensitive:
            plan_warnings.append(
                "Поля одновременно с ролями sensitive_attribute и direct_identifier "
                "не участвуют в l-проверке: " + ", ".join(excluded_sensitive) + "."
            )

    return {
        "dataset_id": session.dataset_id,
        "source_name": session.source_path.name,
        "rows": len(session.source_dataframe),
        "columns": len(session.source_dataframe.columns),
        "operations": list(operations),
        "direct_identifier_columns": direct,
        "active_qi_profiles": [
            {
                "name": group["name"],
                "attributes": list(group["attributes"]),
                "k": group.get("k_override") or default_k,
            }
            for group in active_groups
        ] if K_ANONYMITY in operations else [],
        "sensitive_attributes": sensitive if enable_l_diversity else [],
        "excluded_sensitive_direct_identifiers": excluded_sensitive if enable_l_diversity else [],
        "l_value": default_l if enable_l_diversity and K_ANONYMITY in operations else None,
        "l_variant": l_variant if enable_l_diversity and K_ANONYMITY in operations else None,
        "requires_confirmation": True,
        "warnings": plan_warnings + ([
            "Токенизация является псевдонимизацией, а не доказательством анонимности."
        ] if TOKENIZE_DIRECT_IDENTIFIERS in operations else []),
    }


def execute_anonymization_for_session(
    session: DatasetSession,
    destination: str | Path,
    operations: list[str],
    default_k: int = 5,
    representative: str = "mean",
    enable_l_diversity: bool = False,
    default_l: int = 2,
    l_variant: str = "both",
    profile_path: str | Path = DEFAULT_PROFILE_PATH,
    overwrite: bool = False,
) -> SessionExecutionResult:
    """Выполняет анонимизацию, сохраняет результат и оценивает его в рамках той же сессии."""
    output_path = Path(destination).resolve()
    if output_path == session.source_path.resolve():
        raise ValueError("Нельзя сохранять результат поверх исходной таблицы.")
    if output_path.exists() and not overwrite:
        raise FileExistsError(f"Файл уже существует: {output_path}")

    if representative not in {"mean", "median", "medoid"}:
        raise ValueError("Представитель числовой группы должен быть mean, median или medoid.")

    prepare_anonymization_plan(
        session,
        operations,
        default_k,
        enable_l_diversity,
        default_l,
        l_variant,
        profile_path,
    )
    execution = apply_anonymization_operations(
        session.source_dataframe,
        session.source_path,
        operations,
        profile_path=profile_path,
        default_k=default_k,
        representative=representative,
        enable_l_diversity=enable_l_diversity,
        default_l=default_l,
        l_variant=l_variant,
    )

    release_check = evaluate_release_readiness(
        session.source_dataframe,
        execution.dataframe,
        session.source_path,
        execution.operations,
        execution.k_report,
        l_diversity_enabled=enable_l_diversity and K_ANONYMITY in execution.operations,
        profile_path=profile_path,
    )
    roles = load_manual_role_overrides(session.source_path, profile_path)
    excluded = [
        column for column, assigned in roles.items()
        if "direct_identifier" in assigned and column in session.source_dataframe.columns
    ]
    utility = evaluate_utility(
        session.source_dataframe,
        execution.dataframe,
        excluded_columns=excluded,
    )
    save_csv(execution.dataframe, output_path)
    session.set_result(
        output_path,
        execution.dataframe,
        execution.operations,
        execution.k_report,
    )
    session.release_check = release_check
    session.utility_evaluation = utility
    return SessionExecutionResult(execution, release_check, utility, output_path)


def analyze_session_source(
    session: DatasetSession,
    profile_path: str | Path = DEFAULT_PROFILE_PATH,
    date_formats: dict[str, str] | None = None,
) -> AnalysisResults:
    return run_analysis(
        session.source_dataframe,
        session.source_path,
        profile_path=profile_path,
        date_formats=date_formats,
    )


def analyze_session_result(
    session: DatasetSession,
    profile_path: str | Path = DEFAULT_PROFILE_PATH,
    date_formats: dict[str, str] | None = None,
) -> AnalysisResults:
    if session.result_dataframe is None:
        raise ValueError("В текущей сессии ещё нет результата анонимизации.")
    return run_analysis(
        session.result_dataframe,
        session.source_path,
        profile_path=profile_path,
        date_formats=date_formats,
    )
