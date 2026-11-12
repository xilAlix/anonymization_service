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
    anonymize_manual_direct_identifiers,
    remove_manual_direct_identifiers,
)
from data_processing.attribute_classifier import (
    ROLE_LABELS,
    classify_attributes,
    role_labels,
)
from data_processing.csv_handler import load_csv, save_csv
from data_processing.schema_inspector import ColumnTypeResult, analyze_column_types
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
)
from infrastructure.settings_manager import DEFAULT_SETTINGS_PATH, load_settings
from application.k_anonymization_workflow import (
    execute_k_anonymization,
    evaluate_current_k,
    save_k_anonymity_report,
)


PROFILE_PATH = DEFAULT_PROFILE_PATH
SETTINGS_PATH = DEFAULT_SETTINGS_PATH


def _format_analysis(
    results: list[ColumnTypeResult],
    settings_enabled: bool,
) -> str:
    headers = (
        "АТРИБУТ",
        "ТИП PANDAS",
        "НОМИНАЛЬНЫЙ",
        "УНИКАЛЬНЫЕ ЗНАЧЕНИЯ",
    )
    rows = []
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
        rows.append((result.attribute, result.pandas_type, nominal, ratio))

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
    k_anonymize_parser.add_argument("--overwrite", action="store_true", help="Разрешить перезапись выходного CSV и отчёта.")

    k_evaluate_parser = subparsers.add_parser(
        "evaluate-k-anonymity",
        help="Проверить k-анонимность существующего CSV по активным QI-профилям.",
    )
    k_evaluate_parser.add_argument("csv_path", type=Path)
    k_evaluate_parser.add_argument("--k", type=int, help="Общее значение k. По умолчанию берётся из настроек.")

    return parser


def run_cli(arguments: list[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(arguments)

    try:
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

        if args.command == "k-anonymize":
            input_path = args.input_csv.resolve()
            output_path = args.output_csv.resolve()
            if input_path == output_path:
                raise ValueError("Выходной файл не должен совпадать с исходным CSV.")
            if output_path.exists() and not args.overwrite:
                raise FileExistsError(f"Выходной файл уже существует: {output_path}. Используй --overwrite.")
            settings = load_settings(SETTINGS_PATH)
            k_value = args.k if args.k is not None else settings.k_anonymization.default_k
            representative = args.representative or settings.k_anonymization.numeric_representative
            if k_value < 2:
                raise ValueError("k должно быть не меньше 2.")
            dataframe = load_csv(input_path)
            result_dataframe, report = execute_k_anonymization(
                dataframe,
                input_path,
                default_k=k_value,
                representative=representative,
                profile_path=PROFILE_PATH,
            )
            report_path = args.report_json or output_path.with_name(output_path.stem + "_k_report.json")
            if report_path.exists() and not args.overwrite:
                raise FileExistsError(f"Файл отчёта уже существует: {report_path}. Используй --overwrite.")
            save_csv(result_dataframe, output_path)
            save_k_anonymity_report(report, report_path)
            print(f"k-анонимизация выполнена. Строк: {len(dataframe)}; столбцов: {len(dataframe.columns)}.")
            print(f"Значение k по умолчанию: {k_value}; представитель: {representative}.")
            for item in report["profiles"]:
                print(
                    f"{item['group_name']}: k={item['required_k']}, "
                    f"минимальный размер класса={item['minimum_equivalence_class_size']}, "
                    f"классов={item['equivalence_class_count']}, "
                    f"статус={'выполнено' if item['satisfied'] else 'не выполнено'}"
                )
            print("Блоки обработки:")
            for block in report["components"]:
                print(
                    f"  {block['component_id']} | {block['algorithm']} | "
                    f"k={block['required_k']} | кластеры={block['cluster_count']} | "
                    f"столбцы={', '.join(block['attributes'])}"
                )
            print(f"Результат: {output_path}")
            print(f"Подробный отчёт: {report_path}")
            print("Важно: k-анонимность не гарантирует l-разнообразие, t-близость или DP.")
            return 0

        if args.command in {"anonymize", "remove-direct-identifiers"}:
            input_path = args.input_csv.resolve()
            output_path = args.output_csv.resolve()
            if input_path == output_path:
                raise ValueError("Выходной файл не должен совпадать с исходным CSV.")
            if output_path.exists() and not args.overwrite:
                raise FileExistsError(
                    f"Выходной файл уже существует: {output_path}. "
                    "Для перезаписи укажи --overwrite."
                )

            dataframe = load_csv(input_path)
            if args.command == "anonymize":
                result_dataframe, affected_columns = anonymize_manual_direct_identifiers(
                    dataframe,
                    input_path,
                    PROFILE_PATH,
                )
                print("Токенизированные столбцы: " + ", ".join(affected_columns))
                print(
                    "Важно: токенизация является псевдонимизацией и сама по себе "
                    "не гарантирует анонимность набора данных."
                )
            else:
                result_dataframe, affected_columns = remove_manual_direct_identifiers(
                    dataframe,
                    input_path,
                    PROFILE_PATH,
                )
                print("Удалённые столбцы: " + ", ".join(affected_columns))

            save_csv(result_dataframe, output_path)
            print(f"Результат сохранён: {output_path}")
            return 0

    except (OSError, ValueError, RuntimeError, pd.errors.ParserError) as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        return 2

    parser.print_help()
    return 0
