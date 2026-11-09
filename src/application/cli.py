import argparse
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIRECTORY = PROJECT_ROOT / "src"
if str(SRC_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SRC_DIRECTORY))

from application.anonymization_workflow import anonymize_manual_direct_identifiers
from data_processing.attribute_classifier import (
    ROLE_LABELS,
    classify_attributes,
    role_labels,
)
from data_processing.csv_handler import load_csv, save_csv
from data_processing.schema_inspector import ColumnTypeResult, analyze_column_types
from infrastructure.attribute_profile_store import (
    DEFAULT_PROFILE_PATH,
    load_manual_role_overrides,
    save_manual_role_overrides,
)
from infrastructure.settings_manager import DEFAULT_SETTINGS_PATH, load_settings


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


def _format_attribute_classification(csv_path: Path) -> str:
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
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="Сервис анонимизации",
        description="Просмотр, классификация и токенизация CSV-таблиц.",
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
            print(_format_attribute_classification(args.csv_path))
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

        if args.command == "anonymize":
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
            anonymized_dataframe, tokenized_columns = anonymize_manual_direct_identifiers(
                dataframe,
                input_path,
                PROFILE_PATH,
            )
            save_csv(anonymized_dataframe, output_path)
            print(f"Результат сохранён: {output_path}")
            print("Токенизированные столбцы: " + ", ".join(tokenized_columns))
            print(
                "Важно: токенизация является псевдонимизацией и сама по себе "
                "не гарантирует анонимность набора данных."
            )
            return 0

    except (OSError, ValueError, pd.errors.ParserError) as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        return 2

    parser.print_help()
    return 0
