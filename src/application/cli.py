import argparse
import json
import sys
from pathlib import Path
from uuid import uuid4

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIRECTORY = PROJECT_ROOT / "src"
if str(SRC_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SRC_DIRECTORY))

from application.anonymization_workflow import (
    K_ANONYMITY,
    REMOVE_DIRECT_IDENTIFIERS,
    TOKENIZE_DIRECT_IDENTIFIERS,
)
from data_processing.attribute_classifier import (
    ROLE_LABELS,
    classify_attributes,
    role_labels,
)
from data_processing.csv_handler import load_csv
from data_processing.schema_inspector import ColumnTypeResult, analyze_column_types
from data_processing.semantic_types import SEMANTIC_TYPE_LABELS
from data_processing.quasi_identifier_analyzer import suggest_quasi_identifier_groups
from infrastructure.attribute_profile_store import (
    DEFAULT_PROFILE_PATH,
    load_manual_role_overrides,
    save_manual_role_overrides,
    load_quasi_identifier_groups,
    save_quasi_identifier_groups,
    new_manual_quasi_identifier_group,
    load_quasi_identifier_hierarchies,
    save_quasi_identifier_hierarchy,
    load_quasi_identifier_correlation_blocks,
    save_quasi_identifier_correlation_blocks,
    load_semantic_types,
    save_semantic_type,
)
from infrastructure.settings_manager import DEFAULT_SETTINGS_PATH, load_settings
from infrastructure.file_safety import validate_input_file, validate_output_file
from application.analysis_workflow import export_analysis_results
from application.service import analyze_session_source, execute_anonymization_for_session
from application.session_workflow import DatasetSession
from data_analysis.descriptive_statistics import detect_date_format
from application.k_anonymization_workflow import (
    LDiversityViolationError,
    TClosenessViolationError,
    evaluate_current_k,
    evaluate_current_l,
    save_k_anonymity_report,
)


PROFILE_PATH = DEFAULT_PROFILE_PATH
SETTINGS_PATH = DEFAULT_SETTINGS_PATH


def _format_analysis(
    results: list[ColumnTypeResult],
    settings_enabled: bool,
    semantic_types: dict[str, str] | None = None,
) -> str:
    headers = (
        "АТРИБУТ",
        "ТИП PANDAS",
        "СЕМАНТИЧЕСКИЙ ТИП",
        "НОМИНАЛЬНЫЙ",
        "УНИКАЛЬНЫЕ ЗНАЧЕНИЯ",
    )
    rows = []
    semantic_types = semantic_types or {}
    for result in results:
        if result.is_nominal is None:
            nominal = "не проверялось" if not settings_enabled else "нет данных"
        else:
            nominal = "да" if result.is_nominal else "нет"
        if result.unique_count is None:
            ratio = "не рассчитывалось"
        elif result.unique_percent is None:
            ratio = f"{result.unique_count}/{result.non_null_count} (нет данных)"
        else:
            ratio = (
                f"{result.unique_count}/{result.non_null_count} "
                f"({result.unique_percent:.2f}%)"
            )
        semantic = SEMANTIC_TYPE_LABELS.get(semantic_types.get(result.attribute, "auto"), "Автоматически")
        rows.append((result.attribute, result.pandas_type, semantic, nominal, ratio))

    widths = [
        max([len(headers[index])] + [len(row[index]) for row in rows])
        for index in range(len(headers))
    ]
    line = "-+-".join("-" * width for width in widths)
    output = [
        " | ".join(headers[index].ljust(widths[index]) for index in range(len(headers))),
        line,
    ]
    output.extend(
        " | ".join(row[index].ljust(widths[index]) for index in range(len(headers)))
        for row in rows
    )
    return "\n".join(output)


def _format_attribute_classification(csv_path: Path, include_qi_groups: bool = False) -> str:
    dataframe = load_csv(csv_path)
    overrides = load_manual_role_overrides(csv_path, PROFILE_PATH)
    results = classify_attributes(dataframe, overrides)
    lines = [
        f"Файл: {csv_path}",
        f"Размер: {len(dataframe)} строк × {len(dataframe.columns)} столбцов",
        "",
    ]

    for result in results:
        lines.append(f"{result.attribute} [{result.pandas_type}]")
        if result.suggestions:
            lines.append("  Автоматические предложения:")
            for suggestion in result.suggestions:
                lines.append(
                    f"    - {ROLE_LABELS[suggestion.role]} "
                    f"(эвристическая уверенность: {suggestion.confidence})"
                )
                lines.extend(f"      {reason}" for reason in suggestion.reasons)
        else:
            lines.append("  Автоматических предложений нет.")

        if result.assignment_source == "Вручную":
            lines.append(f"  Ручное назначение: {role_labels(result.assigned_roles)}")
        lines.append("")

    lines.append(
        "Примечание: предложения эвристические и не являются гарантией "
        "обнаружения всех идентификаторов."
    )
    if include_qi_groups:
        manual_groups = load_quasi_identifier_groups(csv_path, PROFILE_PATH)
        manual_only = [group for group in manual_groups if group.get("source") != "automatic"]
        suggested_groups = suggest_quasi_identifier_groups(dataframe)
        manual_ids = {group["id"] for group in manual_only}
        merged_groups = manual_only + [
            group for group in suggested_groups if group["id"] not in manual_ids
        ]
        save_quasi_identifier_groups(
            csv_path,
            merged_groups,
            available_columns=list(dataframe.columns),
            profile_path=PROFILE_PATH,
        )
        lines.extend(["", "Предлагаемые группы квази-идентификаторов:"])
        lines.extend(_format_qi_groups(suggested_groups).splitlines())
    return "\n".join(lines)


def _format_qi_groups(groups: list[dict]) -> str:
    if not groups:
        return "  Кандидаты QI не обнаружены по текущему каталогу. Это не доказывает отсутствие QI."
    lines: list[str] = []
    for group in groups:
        lines.append(
            f"  {group['id']} | {group['name']} | уверенность: {group['confidence']}"
        )
        lines.append("    Атрибуты: " + ", ".join(group["attributes"]))
        row_count = group.get("row_count")
        row_count_label = str(row_count) if row_count is not None else "неизвестно"
        lines.append(
            "    Уникальность комбинаций внутри файла: "
            f"{group.get('unique_tuple_ratio', 0.0):.1%} "
            f"({group.get('unique_tuple_count', 0)} из {row_count_label} строк)"
        )
        for reason in group.get("reasons", []):
            lines.append("    Основание: " + reason)
        for attribute, evidence in group.get("attribute_evidence", {}).items():
            lines.append(
                f"    {attribute} ({evidence.get('confidence', 'не указана')}): "
                + " ".join(evidence.get("reasons", []))
            )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="Сервис анонимизации",
        description="Анализ CSV, управление QI-профилями и методы обезличивания.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    analyze_parser = subparsers.add_parser(
        "analyze-types",
        help="Определить технические типы столбцов CSV-файла.",
    )
    analyze_parser.add_argument("csv_path", type=Path, help="Путь к CSV-файлу.")

    semantic_list_parser = subparsers.add_parser(
        "list-semantic-types",
        help="Показать сохранённые семантические типы столбцов CSV.",
    )
    semantic_list_parser.add_argument("csv_path", type=Path, help="Путь к CSV-файлу.")

    semantic_set_parser = subparsers.add_parser(
        "set-semantic-type",
        help="Сохранить семантический тип одного столбца CSV.",
    )
    semantic_set_parser.add_argument("csv_path", type=Path, help="Путь к CSV-файлу.")
    semantic_set_parser.add_argument("--column", required=True, help="Название столбца.")
    semantic_set_parser.add_argument(
        "--type", dest="semantic_type", required=True, choices=tuple(SEMANTIC_TYPE_LABELS),
        help="Тип: auto, numeric, categorical, datetime или identifier.",
    )

    analysis_data_parser = subparsers.add_parser(
        "analyze-data",
        help="Рассчитать описательную статистику и парные корреляции исходного CSV.",
    )
    analysis_data_parser.add_argument("input_csv", type=Path, help="Исходный CSV-файл.")
    analysis_data_parser.add_argument(
        "--output-dir",
        type=Path,
        help="Необязательный каталог для экспорта таблиц статистики и корреляций.",
    )
    analysis_data_parser.add_argument(
        "--date-columns",
        nargs="+",
        default=[],
        help="Столбцы, которые нужно вручную трактовать как даты.",
    )
    analysis_data_parser.add_argument(
        "--date-format",
        action="append",
        default=[],
        metavar="СТОЛБЕЦ=ФОРМАТ",
        help="Явный strptime-формат для даты, например order_date=%%d/%%m/%%Y. Можно повторять.",
    )
    analysis_data_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Разрешить перезапись существующих CSV-таблиц анализа.",
    )

    classify_parser = subparsers.add_parser(
        "classify-attributes",
        help="Показать автоматические предложения по ролям атрибутов.",
    )
    classify_parser.add_argument("csv_path", type=Path, help="Путь к CSV-файлу.")

    roles_parser = subparsers.add_parser(
        "set-roles",
        help="Сохранить ручные роли одного столбца для указанного CSV.",
    )
    roles_parser.add_argument("csv_path", type=Path, help="Путь к CSV-файлу.")
    roles_parser.add_argument("--column", required=True, help="Название столбца.")
    role_action = roles_parser.add_mutually_exclusive_group(required=True)
    role_action.add_argument(
        "--roles",
        nargs="+",
        choices=tuple(ROLE_LABELS),
        help="Роли через пробел, например direct_identifier sensitive_attribute.",
    )
    role_action.add_argument(
        "--clear",
        action="store_true",
        help="Явно снять все роли и отключить автоматические предложения для столбца.",
    )

    anonymize_parser = subparsers.add_parser(
        "anonymize",
        help="Токенизировать вручную назначенные прямые идентификаторы.",
    )
    anonymize_parser.add_argument("input_csv", type=Path, help="Исходный CSV.")
    anonymize_parser.add_argument("output_csv", type=Path, help="Новый CSV для результата.")
    anonymize_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Разрешить перезапись существующего выходного файла.",
    )

    remove_parser = subparsers.add_parser(
        "remove-direct-identifiers",
        help="Удалить столбцы с вручную назначенной ролью прямого идентификатора.",
    )
    remove_parser.add_argument("input_csv", type=Path, help="Исходный CSV.")
    remove_parser.add_argument("output_csv", type=Path, help="Новый CSV для результата.")
    remove_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Разрешить перезапись существующего выходного файла.",
    )

    qi_analyze_parser = subparsers.add_parser(
        "analyze-quasi-identifier-groups",
        help="Сформировать объяснимые предложения по нескольким группам QI.",
    )
    qi_analyze_parser.add_argument("csv_path", type=Path, help="Путь к CSV-файлу.")
    qi_analyze_parser.add_argument(
        "--save",
        action="store_true",
        help="Сохранить автоматические группы в профиле CSV, сохранив пользовательские группы.",
    )

    qi_list_parser = subparsers.add_parser(
        "list-quasi-identifier-groups",
        help="Показать сохранённые группы QI для CSV-файла.",
    )
    qi_list_parser.add_argument("csv_path", type=Path, help="Путь к CSV-файлу.")

    qi_add_parser = subparsers.add_parser(
        "add-quasi-identifier-group",
        help="Создать пользовательскую группу QI.",
    )
    qi_add_parser.add_argument("csv_path", type=Path, help="Путь к CSV-файлу.")
    qi_add_parser.add_argument("--name", required=True, help="Название группы.")
    qi_add_parser.add_argument(
        "--columns", nargs="+", required=True,
        help="Названия столбцов, входящих в группу. Допускается пересечение групп.",
    )

    qi_edit_parser = subparsers.add_parser(
        "edit-quasi-identifier-group",
        help="Переименовать группу или изменить список её атрибутов.",
    )
    qi_edit_parser.add_argument("csv_path", type=Path, help="Путь к CSV-файлу.")
    qi_edit_parser.add_argument("--group-id", required=True, help="ID из list-quasi-identifier-groups.")
    qi_edit_parser.add_argument("--name", help="Новое название группы.")
    qi_edit_parser.add_argument("--add-columns", nargs="*", default=[], help="Столбцы для добавления.")
    qi_edit_parser.add_argument("--remove-columns", nargs="*", default=[], help="Столбцы для удаления.")
    qi_edit_state = qi_edit_parser.add_mutually_exclusive_group()
    qi_edit_state.add_argument("--activate", action="store_true", help="Подтвердить и активировать профиль для k-анонимизации.")
    qi_edit_state.add_argument("--deactivate", action="store_true", help="Исключить профиль из k-анонимизации.")
    qi_edit_parser.add_argument("--k-override", type=int, help="Переопределить k для этой группы.")
    qi_edit_parser.add_argument("--clear-k-override", action="store_true", help="Использовать общее k из настроек.")

    qi_delete_parser = subparsers.add_parser(
        "delete-quasi-identifier-group",
        help="Удалить группу QI из профиля CSV.",
    )
    qi_delete_parser.add_argument("csv_path", type=Path, help="Путь к CSV-файлу.")
    qi_delete_parser.add_argument("--group-id", required=True, help="ID группы.")

    hierarchy_parser = subparsers.add_parser(
        "set-quasi-identifier-hierarchy",
        help="Задать пользовательскую иерархию категориального QI.",
    )
    hierarchy_parser.add_argument("csv_path", type=Path)
    hierarchy_parser.add_argument("--column", required=True)
    hierarchy_source = hierarchy_parser.add_mutually_exclusive_group(required=True)
    hierarchy_source.add_argument("--levels-json", help="JSON-массив уровней обобщения.")
    hierarchy_source.add_argument("--levels-file", type=Path, help="Файл с JSON-массивом уровней.")

    correlation_add_parser = subparsers.add_parser(
        "add-qi-correlation-block",
        help="Объединить признаки для совместной микроагрегации ради сохранения аналитических связей.",
    )
    correlation_add_parser.add_argument("csv_path", type=Path)
    correlation_add_parser.add_argument("--name", required=True)
    correlation_add_parser.add_argument("--columns", nargs="+", required=True)

    correlation_list_parser = subparsers.add_parser(
        "list-qi-correlation-blocks",
        help="Показать блоки признаков для сохранения корреляций.",
    )
    correlation_list_parser.add_argument("csv_path", type=Path)

    correlation_delete_parser = subparsers.add_parser(
        "delete-qi-correlation-block",
        help="Удалить блок признаков для совместной микроагрегации.",
    )
    correlation_delete_parser.add_argument("csv_path", type=Path)
    correlation_delete_parser.add_argument("--block-id", required=True)

    k_anonymize_parser = subparsers.add_parser(
        "k-anonymize",
        help="Выполнить k-анонимизацию по активным QI-профилям и сохранить подробный отчёт.",
    )
    k_anonymize_parser.add_argument("input_csv", type=Path)
    k_anonymize_parser.add_argument("output_csv", type=Path)
    k_anonymize_parser.add_argument("--k", type=int, help="Общее значение k. По умолчанию берётся из настроек.")
    k_anonymize_parser.add_argument("--representative", choices=("mean", "median", "medoid"), help="Представитель числовой группы.")
    k_anonymize_parser.add_argument("--report-json", type=Path, help="Путь к подробному JSON-отчёту.")
    k_l_group = k_anonymize_parser.add_mutually_exclusive_group()
    k_l_group.add_argument("--l-diversity", dest="enable_l_diversity", action="store_true", help="Включить проверку l-разнообразия независимо от настройки.")
    k_l_group.add_argument("--no-l-diversity", dest="enable_l_diversity", action="store_false", help="Отключить проверку l-разнообразия для этого запуска.")
    k_anonymize_parser.set_defaults(enable_l_diversity=None)
    k_anonymize_parser.add_argument("--l", type=int, help="Переопределить значение l (само по себе включает l-проверку).")
    k_anonymize_parser.add_argument("--l-variant", choices=("distinct", "entropy", "both"), help="Вариант l-проверки.")
    t_group = k_anonymize_parser.add_mutually_exclusive_group()
    t_group.add_argument("--t-closeness", dest="enable_t_closeness", action="store_true", help="Включить t-близость.")
    t_group.add_argument("--no-t-closeness", dest="enable_t_closeness", action="store_false", help="Отключить t-близость.")
    k_anonymize_parser.set_defaults(enable_t_closeness=None)
    k_anonymize_parser.add_argument("--t", type=float, help="Порог t от 0 до 1; автоматически включает t-близость.")
    k_anonymize_parser.add_argument("--overwrite", action="store_true", help="Разрешить перезапись выходного CSV и отчёта.")

    k_evaluate_parser = subparsers.add_parser(
        "evaluate-k-anonymity",
        help="Проверить k-анонимность существующего CSV по активным QI-профилям.",
    )
    k_evaluate_parser.add_argument("csv_path", type=Path)
    k_evaluate_parser.add_argument("--k", type=int, help="Общее значение k. По умолчанию берётся из настроек.")

    l_evaluate_parser = subparsers.add_parser(
        "evaluate-l-diversity",
        help="Проверить l-разнообразие существующего CSV по активным QI-профилям и ручным sensitive-ролям.",
    )
    l_evaluate_parser.add_argument("csv_path", type=Path)
    l_evaluate_parser.add_argument("--l", type=int, help="Значение l; по умолчанию берётся из настроек.")
    l_evaluate_parser.add_argument("--variant", choices=("distinct", "entropy", "both"), help="Критерий; по умолчанию берётся из настроек.")
    l_evaluate_parser.add_argument("--report-json", type=Path, help="Сохранить подробный отчёт проверки.")
    l_evaluate_parser.add_argument(
        "--profile-source",
        type=Path,
        help="Исходный CSV, к которому привязаны ручные роли и QI-профили (для проверки отдельного выходного файла).",
    )

    selected_anonymize_parser = subparsers.add_parser(
        "anonymize-selected",
        help="Выполнить операции, выбранные в настройках суммарной анонимизации.",
    )
    selected_anonymize_parser.add_argument("input_csv", type=Path)
    selected_anonymize_parser.add_argument("output_csv", type=Path)
    selected_anonymize_parser.add_argument("--k", type=int, help="Переопределить общее значение k.")
    selected_anonymize_parser.add_argument(
        "--representative",
        choices=("mean", "median", "medoid"),
        help="Переопределить способ замены числовых значений.",
    )
    selected_anonymize_parser.add_argument(
        "--report-json",
        type=Path,
        help="Путь к подробному JSON-отчёту k-анонимизации.",
    )
    selected_l_group = selected_anonymize_parser.add_mutually_exclusive_group()
    selected_l_group.add_argument("--l-diversity", dest="enable_l_diversity", action="store_true", help="Включить проверку l-разнообразия независимо от настройки.")
    selected_l_group.add_argument("--no-l-diversity", dest="enable_l_diversity", action="store_false", help="Отключить проверку l-разнообразия для этого запуска.")
    selected_anonymize_parser.set_defaults(enable_l_diversity=None)
    selected_anonymize_parser.add_argument("--l", type=int, help="Переопределить значение l (само по себе включает l-проверку).")
    selected_anonymize_parser.add_argument("--l-variant", choices=("distinct", "entropy", "both"), help="Вариант l-проверки.")
    selected_t_group = selected_anonymize_parser.add_mutually_exclusive_group()
    selected_t_group.add_argument("--t-closeness", dest="enable_t_closeness", action="store_true", help="Включить t-близость.")
    selected_t_group.add_argument("--no-t-closeness", dest="enable_t_closeness", action="store_false", help="Отключить t-близость.")
    selected_anonymize_parser.set_defaults(enable_t_closeness=None)
    selected_anonymize_parser.add_argument("--t", type=float, help="Порог t от 0 до 1; автоматически включает t-близость.")
    selected_anonymize_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Разрешить перезапись выходного CSV и отчёта.",
    )

    return parser


def _print_session_evaluation(outcome) -> None:
    release = outcome.release_check
    print(f"Оценка приватности: {release['status_label']} ({release['status']}).")
    status_labels = {"passed": "пройдена", "warning": "предупреждение", "blocked": "заблокирована"}
    for check in release.get("checks", []):
        label = status_labels.get(check.get("status"), check.get("status", "неизвестно"))
        details = check.get("details")
        suffix = f" — {details}" if details and check.get("status") != "passed" else ""
        print(f"  {check.get('check')}: {label}{suffix}")
    summary = outcome.utility.summary
    print(
        "Оценка полезности: "
        f"общих атрибутов={summary['common_columns']}, "
        f"числовых={summary['numeric_columns']}, "
        f"категориальных/прочих={summary['categorical_columns']}."
    )


def run_cli(arguments: list[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(arguments)

    try:
        if args.command == "analyze-data":
            input_path = validate_input_file(args.input_csv)
            dataframe = load_csv(input_path)
            date_formats: dict[str, str] = {}
            requested_dates = set(args.date_columns)
            unknown_dates = requested_dates - {str(column) for column in dataframe.columns}
            if unknown_dates:
                raise ValueError(
                    "Столбцы дат отсутствуют в CSV: " + ", ".join(sorted(unknown_dates))
                )

            for item in args.date_format:
                column, separator, date_format = item.partition("=")
                if not separator or not column.strip() or not date_format.strip():
                    raise ValueError(
                        "Формат --date-format должен иметь вид СТОЛБЕЦ=ФОРМАТ, "
                        "например order_date=%d/%m/%Y."
                    )
                column = column.strip()
                if column not in dataframe.columns:
                    raise ValueError(f"Столбец «{column}» отсутствует в CSV.")
                if requested_dates and column not in requested_dates:
                    raise ValueError(
                        f"Для «{column}» задан формат, но столбец не указан в --date-columns."
                    )
                date_formats[column] = date_format.strip()

            for column in requested_dates:
                if column in date_formats:
                    continue
                detected_format, ambiguous = detect_date_format(dataframe[column])
                if detected_format is None:
                    reason = "формат неоднозначен" if ambiguous else "формат не распознан"
                    raise ValueError(
                        f"Для столбца «{column}» {reason}. Укажи явный формат: "
                        f'--date-format "{column}=%d/%m/%Y".'
                    )
                date_formats[column] = detected_format

            session = DatasetSession.start(input_path, dataframe)
            results = analyze_session_source(
                session,
                profile_path=PROFILE_PATH,
                date_formats=date_formats,
            )
            print(f"Файл: {input_path}")
            print(
                f"Размер: {results.source_rows} строк × {results.source_columns} столбцов. "
                f"Анализируемых атрибутов: {len(results.included_columns)}."
            )
            if results.excluded_columns:
                print("Исключены вручную назначенные direct_identifier: " + ", ".join(results.excluded_columns))
            print("\nОПИСАТЕЛЬНАЯ СТАТИСТИКА")
            print(results.statistics.to_string())
            if results.pearson.empty:
                print("\nКорреляции не рассчитаны: нет количественных числовых атрибутов.")
            else:
                print("\nКОРРЕЛЯЦИЯ PEARSON")
                print(results.pearson.to_string())
                print("\nКОРРЕЛЯЦИЯ SPEARMAN")
                print(results.spearman.to_string())
            if args.output_dir is not None:
                expected = [
                    args.output_dir / f"{input_path.stem}_statistics.csv",
                    args.output_dir / f"{input_path.stem}_pearson.csv",
                    args.output_dir / f"{input_path.stem}_spearman.csv",
                ]
                existing = [path for path in expected if path.exists()]
                if existing and not args.overwrite:
                    raise FileExistsError(
                        "Файлы анализа уже существуют: " + ", ".join(map(str, existing))
                        + ". Для перезаписи используй --overwrite."
                    )
                outputs = export_analysis_results(results, input_path, args.output_dir)
                print("\nСохранены таблицы:")
                for path in outputs:
                    print(f"  {path}")
            else:
                print("\nЭкспорт не выполнялся. Для сохранения укажи --output-dir.")
            print("\nАнализ не изменяет исходный CSV.")
            return 0

        if args.command == "analyze-types":
            dataframe = load_csv(args.csv_path)
            settings = load_settings(SETTINGS_PATH)
            analysis_settings = settings.data_type_analysis
            results = analyze_column_types(
                dataframe,
                detect_nominal_attributes=analysis_settings.detect_nominal_attributes,
                nominal_unique_threshold_percent=(
                    analysis_settings.nominal_unique_threshold_percent
                ),
            )
            print(f"Файл: {args.csv_path}")
            print(
                f"Размер: {len(dataframe)} строк × "
                f"{len(dataframe.columns)} столбцов\n"
            )
            print(
                _format_analysis(
                    results,
                    analysis_settings.detect_nominal_attributes,
                    load_semantic_types(args.csv_path, PROFILE_PATH),
                )
            )
            if not analysis_settings.detect_nominal_attributes:
                print("\nОпределение номинальных атрибутов выключено в настройках.")
            else:
                threshold = analysis_settings.nominal_unique_threshold_percent
                print(
                    f"\nПорог номинальности: не более {threshold:g}% "
                    "уникальных непустых значений."
                )
            return 0

        if args.command == "list-semantic-types":
            dataframe = load_csv(args.csv_path)
            stored = load_semantic_types(args.csv_path, PROFILE_PATH)
            print(f"Файл: {args.csv_path}")
            for column in dataframe.columns:
                semantic_type = stored.get(str(column), "auto")
                print(f"{column}: {SEMANTIC_TYPE_LABELS[semantic_type]} [{semantic_type}]")
            return 0

        if args.command == "set-semantic-type":
            dataframe = load_csv(args.csv_path)
            if args.column not in dataframe.columns:
                raise ValueError(f"Столбец «{args.column}» отсутствует в указанном CSV.")
            save_semantic_type(
                args.csv_path, args.column, args.semantic_type, PROFILE_PATH
            )
            print(
                f"Семантический тип столбца «{args.column}» сохранён: "
                f"{SEMANTIC_TYPE_LABELS[args.semantic_type]}."
            )
            return 0

        if args.command == "classify-attributes":
            settings = load_settings(SETTINGS_PATH)
            include_qi_groups = settings.data_type_analysis.enable_multiple_quasi_identifier_groups
            print(_format_attribute_classification(args.csv_path, include_qi_groups))
            if include_qi_groups:
                print("\nАвтоматические группы сохранены в профиле набора данных.")
            return 0

        if args.command == "set-roles":
            dataframe = load_csv(args.csv_path)
            if args.column not in dataframe.columns:
                raise ValueError(
                    f"Столбец «{args.column}» отсутствует в указанном CSV."
                )
            overrides = load_manual_role_overrides(args.csv_path, PROFILE_PATH)
            overrides[args.column] = [] if args.clear else list(args.roles)
            save_manual_role_overrides(args.csv_path, overrides, PROFILE_PATH)
            assigned = role_labels(overrides[args.column])
            print(f"Ручные роли столбца «{args.column}» сохранены: {assigned}.")
            if {
                "direct_identifier",
                "sensitive_attribute",
            }.issubset(set(overrides[args.column])):
                print(
                    "Предупреждение: столбец одновременно назначен прямым идентификатором "
                    "и конфиденциальным атрибутом. Он будет исключён из l-проверки "
                    "как прямой идентификатор."
                )
            print(f"Профиль: {PROFILE_PATH}")
            return 0

        if args.command == "analyze-quasi-identifier-groups":
            dataframe = load_csv(args.csv_path)
            groups = suggest_quasi_identifier_groups(dataframe)
            print(f"Файл: {args.csv_path}")
            print(f"Размер: {len(dataframe)} строк × {len(dataframe.columns)} столбцов")
            print(_format_qi_groups(groups))
            if args.save:
                existing = load_quasi_identifier_groups(args.csv_path, PROFILE_PATH)
                manual_groups = [group for group in existing if group.get("source") != "automatic"]
                manual_ids = {group["id"] for group in manual_groups}
                fresh_groups = [group for group in groups if group["id"] not in manual_ids]
                save_quasi_identifier_groups(
                    args.csv_path,
                    manual_groups + fresh_groups,
                    available_columns=list(dataframe.columns),
                    profile_path=PROFILE_PATH,
                )
                print(f"\nАвтоматические предложения сохранены. Профиль: {PROFILE_PATH}")
            print(
                "\nВажно: группы являются гипотезами о возможных источниках фоновой "
                "информации. Они не доказывают фактическую доступность внешних данных."
            )
            return 0

        if args.command == "list-quasi-identifier-groups":
            groups = load_quasi_identifier_groups(args.csv_path, PROFILE_PATH)
            if not groups:
                print("Для этого CSV группы QI ещё не сохранены.")
                return 0
            for group in groups:
                print(
                    f"{group['id']} | {group['name']} | {group.get('source', 'manual')} | "
                    f"атрибуты: {', '.join(group['attributes'])}"
                )
            return 0

        if args.command == "add-quasi-identifier-group":
            dataframe = load_csv(args.csv_path)
            groups = load_quasi_identifier_groups(args.csv_path, PROFILE_PATH)
            new_group = new_manual_quasi_identifier_group(args.name, args.columns)
            groups.append(new_group)
            save_quasi_identifier_groups(
                args.csv_path,
                groups,
                available_columns=list(dataframe.columns),
                profile_path=PROFILE_PATH,
            )
            print(f"Создана группа «{new_group['name']}» с ID {new_group['id']}.")
            return 0

        if args.command == "edit-quasi-identifier-group":
            dataframe = load_csv(args.csv_path)
            groups = load_quasi_identifier_groups(args.csv_path, PROFILE_PATH)
            group = next((item for item in groups if item["id"] == args.group_id), None)
            if group is None:
                raise ValueError(f"Группа с ID «{args.group_id}» не найдена.")
            if args.name is not None:
                group["name"] = args.name.strip()
            attributes = list(group["attributes"])
            for column in args.remove_columns:
                if column in attributes:
                    attributes.remove(column)
            for column in args.add_columns:
                if column not in attributes:
                    attributes.append(column)
            group["attributes"] = attributes
            group["source"] = "manual"
            group["confidence"] = "ручная"
            group["reasons"] = ["Группа изменена пользователем через CLI."]
            if args.activate:
                group["active"] = True
            if args.deactivate:
                group["active"] = False
            if args.clear_k_override:
                group["k_override"] = None
            elif args.k_override is not None:
                if args.k_override < 2:
                    raise ValueError("Переопределение k должно быть не меньше 2.")
                group["k_override"] = args.k_override
            save_quasi_identifier_groups(
                args.csv_path,
                groups,
                available_columns=list(dataframe.columns),
                profile_path=PROFILE_PATH,
            )
            print(f"Группа «{group['name']}» обновлена.")
            return 0

        if args.command == "delete-quasi-identifier-group":
            groups = load_quasi_identifier_groups(args.csv_path, PROFILE_PATH)
            retained = [group for group in groups if group["id"] != args.group_id]
            if len(retained) == len(groups):
                raise ValueError(f"Группа с ID «{args.group_id}» не найдена.")
            save_quasi_identifier_groups(
                args.csv_path,
                retained,
                profile_path=PROFILE_PATH,
            )
            print(f"Группа «{args.group_id}» удалена.")
            return 0

        if args.command == "set-quasi-identifier-hierarchy":
            dataframe = load_csv(args.csv_path)
            if args.column not in dataframe.columns:
                raise ValueError(f"Столбец «{args.column}» отсутствует в CSV.")
            if args.levels_file:
                raw_levels = json.loads(args.levels_file.read_text(encoding="utf-8"))
            else:
                raw_levels = json.loads(args.levels_json)
            save_quasi_identifier_hierarchy(
                args.csv_path,
                args.column,
                raw_levels,
                list(dataframe.columns),
                PROFILE_PATH,
            )
            print(f"Иерархия обобщения для «{args.column}» сохранена.")
            return 0

        if args.command == "add-qi-correlation-block":
            dataframe = load_csv(args.csv_path)
            blocks = load_quasi_identifier_correlation_blocks(args.csv_path, PROFILE_PATH)
            block = {"id": uuid4().hex[:10], "name": args.name, "attributes": list(args.columns)}
            blocks.append(block)
            save_quasi_identifier_correlation_blocks(
                args.csv_path, blocks, list(dataframe.columns), PROFILE_PATH
            )
            print(f"Блок «{block['name']}» создан. Он объединяет признаки для совместной микроагрегации.")
            print(f"ID: {block['id']}")
            return 0

        if args.command == "list-qi-correlation-blocks":
            blocks = load_quasi_identifier_correlation_blocks(args.csv_path, PROFILE_PATH)
            if not blocks:
                print("Блоки корреляций не заданы.")
            for block in blocks:
                print(f"{block['id']} | {block['name']} | {', '.join(block['attributes'])}")
            return 0

        if args.command == "delete-qi-correlation-block":
            blocks = load_quasi_identifier_correlation_blocks(args.csv_path, PROFILE_PATH)
            retained = [block for block in blocks if block["id"] != args.block_id]
            if len(retained) == len(blocks):
                raise ValueError(f"Блок «{args.block_id}» не найден.")
            dataframe = load_csv(args.csv_path)
            save_quasi_identifier_correlation_blocks(
                args.csv_path, retained, list(dataframe.columns), PROFILE_PATH
            )
            print(f"Блок «{args.block_id}» удалён.")
            return 0

        if args.command == "evaluate-k-anonymity":
            dataframe = load_csv(args.csv_path)
            settings = load_settings(SETTINGS_PATH)
            k_value = args.k if args.k is not None else settings.k_anonymization.default_k
            if k_value < 2:
                raise ValueError("k должно быть не меньше 2.")
            results = evaluate_current_k(dataframe, args.csv_path, k_value, PROFILE_PATH)
            print(f"Файл: {args.csv_path}")
            for item in results:
                status = "выполнено" if item["satisfied"] else "не выполнено"
                print(
                    f"{item['group_name']} | k требуется: {item['required_k']} | "
                    f"минимальная группа: {item['minimum_equivalence_class_size']} | "
                    f"классов: {item['equivalence_class_count']} | {status}"
                )
            return 0 if all(item["satisfied"] for item in results) else 1

        if args.command == "evaluate-l-diversity":
            dataframe = load_csv(args.csv_path)
            settings = load_settings(SETTINGS_PATH)
            l_value = args.l if args.l is not None else settings.k_anonymization.default_l
            variant = args.variant or settings.k_anonymization.l_diversity_variant
            report = evaluate_current_l(
                dataframe,
                args.profile_source or args.csv_path,
                l_value=l_value,
                variant=variant,
                profile_path=PROFILE_PATH,
            )
            if args.report_json:
                save_k_anonymity_report(report, args.report_json)
                print(f"Отчёт: {args.report_json}")
            print(
                f"l={report['l']} | вариант={report['variant']} | "
                f"проверок={report['check_count']} | "
                f"нарушений={report['failed_check_count']} | "
                f"статус={report['status']}"
            )
            excluded = report.get("excluded_sensitive_direct_identifiers", [])
            if excluded:
                print(
                    "Исключены из l-проверки как прямые идентификаторы: "
                    + ", ".join(excluded)
                )
            if report.get("reason"):
                print("Причина: " + report["reason"])
            for profile in report["profiles"]:
                print(
                    f"{profile['profile_name']}: проверок={profile['check_count']}, "
                    f"нарушений={profile['failed_check_count']}, "
                    f"статус={'выполнено' if profile['satisfied'] else 'не выполнено'}"
                )
            return 0 if report["status"] == "satisfied" else 1

        if args.command == "k-anonymize":
            input_path = validate_input_file(args.input_csv)
            output_path = validate_output_file(args.output_csv)
            if input_path == output_path:
                raise ValueError("Выходной файл не должен совпадать с исходным CSV.")
            if output_path.exists() and not args.overwrite:
                raise FileExistsError(f"Выходной файл уже существует: {output_path}. Используй --overwrite.")
            settings = load_settings(SETTINGS_PATH)
            k_value = args.k if args.k is not None else settings.k_anonymization.default_k
            representative = args.representative or settings.k_anonymization.numeric_representative
            enable_l_diversity = (
                settings.k_anonymization.enable_l_diversity
                if args.enable_l_diversity is None
                else args.enable_l_diversity
            )
            if args.l is not None or args.l_variant is not None:
                enable_l_diversity = True
            l_value = args.l if args.l is not None else settings.k_anonymization.default_l
            l_variant = args.l_variant or settings.k_anonymization.l_diversity_variant
            enable_t_closeness = settings.k_anonymization.enable_t_closeness if args.enable_t_closeness is None else args.enable_t_closeness
            if args.t is not None:
                enable_t_closeness = True
            t_value = args.t if args.t is not None else settings.k_anonymization.default_t
            if not 0 <= t_value <= 1:
                raise ValueError("Порог t должен быть от 0 до 1.")
            if k_value < 2:
                raise ValueError("k должно быть не меньше 2.")

            report_path = (
                validate_output_file(args.report_json)
                if args.report_json is not None
                else output_path.with_name(output_path.stem + "_k_report.json")
            )
            if report_path in {input_path, output_path}:
                raise ValueError("Путь отчёта не должен совпадать с исходным или выходным CSV.")
            if report_path.exists() and not args.overwrite:
                raise FileExistsError(f"Файл отчёта уже существует: {report_path}. Используй --overwrite.")

            dataframe = load_csv(input_path)
            session = DatasetSession.start(input_path, dataframe)
            outcome = execute_anonymization_for_session(
                session,
                output_path,
                [K_ANONYMITY],
                default_k=k_value,
                representative=representative,
                enable_l_diversity=enable_l_diversity,
                default_l=l_value,
                l_variant=l_variant,
                enable_t_closeness=enable_t_closeness,
                default_t=t_value,
                profile_path=PROFILE_PATH,
                overwrite=args.overwrite,
            )
            report = outcome.execution.k_report
            if report is None:
                raise RuntimeError("Отчёт k-анонимизации не сформирован.")
            save_k_anonymity_report(report, report_path)
            print(f"k-анонимизация выполнена. Строк: {len(dataframe)}; столбцов: {len(dataframe.columns)}.")
            print(f"Значение k: {k_value}; представитель: {representative}.")
            for item in report["profiles"]:
                print(
                    f"{item['group_name']}: k={item['required_k']}, "
                    f"минимальный размер класса={item['minimum_equivalence_class_size']}, "
                    f"классов={item['equivalence_class_count']}, "
                    f"статус={'выполнено' if item['satisfied'] else 'не выполнено'}"
                )
            print(f"Результат: {output_path}")
            print(f"Подробный отчёт: {report_path}")
            _print_session_evaluation(outcome)
            print("Важно: k-анонимность, l-разнообразие и t-близость не гарантируют невозможность повторной идентификации.")
            return 0

        if args.command == "anonymize-selected":
            input_path = validate_input_file(args.input_csv)
            output_path = validate_output_file(args.output_csv)
            if input_path == output_path:
                raise ValueError("Выходной файл не должен совпадать с исходным CSV.")
            if output_path.exists() and not args.overwrite:
                raise FileExistsError(
                    f"Выходной файл уже существует: {output_path}. Используй --overwrite."
                )

            settings = load_settings(SETTINGS_PATH)
            selected_operations = []
            if settings.anonymization.tokenize_direct_identifiers:
                selected_operations.append(TOKENIZE_DIRECT_IDENTIFIERS)
            if settings.anonymization.remove_direct_identifiers:
                selected_operations.append(REMOVE_DIRECT_IDENTIFIERS)
            if settings.anonymization.enable_k_anonymity:
                selected_operations.append(K_ANONYMITY)

            enable_l_diversity = (
                (settings.k_anonymization.enable_l_diversity if args.enable_l_diversity is None else args.enable_l_diversity)
                or args.l is not None
                or args.l_variant is not None
            )
            k_value = args.k if args.k is not None else settings.k_anonymization.default_k
            representative = args.representative or settings.k_anonymization.numeric_representative
            l_value = args.l if args.l is not None else settings.k_anonymization.default_l
            l_variant = args.l_variant or settings.k_anonymization.l_diversity_variant
            enable_t_closeness = settings.k_anonymization.enable_t_closeness if args.enable_t_closeness is None else args.enable_t_closeness
            if args.t is not None:
                enable_t_closeness = True
            t_value = args.t if args.t is not None else settings.k_anonymization.default_t
            if not 0 <= t_value <= 1:
                raise ValueError("Порог t должен быть от 0 до 1.")
            report_path = None
            if K_ANONYMITY in selected_operations:
                report_path = (
                    Path(args.report_json).resolve()
                    if args.report_json is not None
                    else output_path.with_name(output_path.stem + "_k_report.json")
                )
                if report_path in {input_path, output_path}:
                    raise ValueError("Путь отчёта не должен совпадать с исходным или выходным CSV.")
                if report_path.exists() and not args.overwrite:
                    raise FileExistsError(
                        f"Файл отчёта уже существует: {report_path}. Используй --overwrite."
                    )

            dataframe = load_csv(input_path)
            session = DatasetSession.start(input_path, dataframe)
            outcome = execute_anonymization_for_session(
                session,
                output_path,
                selected_operations,
                default_k=k_value,
                representative=representative,
                enable_l_diversity=enable_l_diversity,
                default_l=l_value,
                l_variant=l_variant,
                enable_t_closeness=enable_t_closeness,
                default_t=t_value,
                profile_path=PROFILE_PATH,
                overwrite=args.overwrite,
            )
            execution = outcome.execution
            if execution.k_report is not None and report_path is not None:
                execution.k_report["combined_operations"] = execution.operations
                save_k_anonymity_report(execution.k_report, report_path)

            operation_labels = {
                TOKENIZE_DIRECT_IDENTIFIERS: "токенизация прямых идентификаторов",
                REMOVE_DIRECT_IDENTIFIERS: "удаление прямых идентификаторов",
                K_ANONYMITY: "k-анонимизация",
            }
            print("Выполненные операции: " + ", ".join(
                operation_labels[item] for item in execution.operations
            ))
            print("Обработанные столбцы: " + (", ".join(execution.affected_columns) or "нет"))
            print(f"Результат сохранён: {output_path}")
            if report_path is not None:
                print(f"Подробный отчёт: {report_path}")
            _print_session_evaluation(outcome)
            if TOKENIZE_DIRECT_IDENTIFIERS in execution.operations:
                print(
                    "Важно: токенизация является псевдонимизацией и сама по себе "
                    "не гарантирует анонимность набора данных."
                )
            return 0

        if args.command in {"anonymize", "remove-direct-identifiers"}:
            input_path = validate_input_file(args.input_csv)
            output_path = validate_output_file(args.output_csv)
            if input_path == output_path:
                raise ValueError("Выходной файл не должен совпадать с исходным CSV.")
            if output_path.exists() and not args.overwrite:
                raise FileExistsError(
                    f"Выходной файл уже существует: {output_path}. "
                    "Для перезаписи укажи --overwrite."
                )

            operation = (
                TOKENIZE_DIRECT_IDENTIFIERS
                if args.command == "anonymize"
                else REMOVE_DIRECT_IDENTIFIERS
            )
            dataframe = load_csv(input_path)
            session = DatasetSession.start(input_path, dataframe)
            outcome = execute_anonymization_for_session(
                session,
                output_path,
                [operation],
                profile_path=PROFILE_PATH,
                overwrite=args.overwrite,
            )
            if operation == TOKENIZE_DIRECT_IDENTIFIERS:
                print("Токенизированные столбцы: " + ", ".join(outcome.execution.affected_columns))
                print(
                    "Важно: токенизация является псевдонимизацией и сама по себе "
                    "не гарантирует анонимность набора данных."
                )
            else:
                print("Удалённые столбцы: " + ", ".join(outcome.execution.affected_columns))
            print(f"Результат сохранён: {output_path}")
            _print_session_evaluation(outcome)
            return 0

    except (LDiversityViolationError, TClosenessViolationError) as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        output_csv = getattr(args, "output_csv", None)
        report_path = getattr(args, "report_json", None)
        if report_path is None and output_csv is not None:
            suffix = "_t_closeness_failed_report.json" if isinstance(error, TClosenessViolationError) else "_l_diversity_failed_report.json"
            report_path = output_csv.with_name(output_csv.stem + suffix)
        if report_path is not None:
            try:
                safe_report_path = validate_output_file(report_path)
                safe_output_path = (
                    validate_output_file(output_csv) if output_csv is not None else None
                )
                input_argument = getattr(args, "input_csv", None)
                safe_input_path = (
                    validate_input_file(input_argument)
                    if input_argument is not None and Path(input_argument).exists()
                    else None
                )
                if safe_report_path in {safe_output_path, safe_input_path}:
                    raise ValueError(
                        "Путь диагностического отчёта совпадает с исходным или выходным файлом."
                    )
                if safe_report_path.exists() and not getattr(args, "overwrite", False):
                    print(
                        f"Диагностический отчёт не записан: файл уже существует {safe_report_path}. "
                        "Для перезаписи укажи --overwrite.",
                        file=sys.stderr,
                    )
                else:
                    save_k_anonymity_report(error.report, safe_report_path)
                    print(f"Диагностический отчёт: {safe_report_path}", file=sys.stderr)
            except (OSError, ValueError) as report_error:
                print(
                    f"Диагностический отчёт не записан: {report_error}",
                    file=sys.stderr,
                )
        return 2
    except (OSError, ValueError, RuntimeError, pd.errors.ParserError) as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        return 2

    parser.print_help()
    return 0
