import argparse
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIRECTORY = PROJECT_ROOT / "src"
if str(SRC_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SRC_DIRECTORY))

from data_processing.csv_handler import load_csv
from data_processing.schema_inspector import ColumnTypeResult, analyze_column_types
from infrastructure.settings_manager import load_settings


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
            nominal = (
                "не проверялось" if not settings_enabled else "нет данных"
            )
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="Сервис анонимизации",
        description=(
            "Локальный просмотр таблиц и анализ "
            "технических типов CSV."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    analyze_parser = subparsers.add_parser(
        "analyze-types",
        help="Определить типы столбцов указанного CSV-файла.",
    )
    analyze_parser.add_argument("csv_path", type=Path, help="Путь к CSV-файлу.")
    return parser


def run_cli(arguments: list[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(arguments)

    if args.command == "analyze-types":
        try:
            dataframe = load_csv(args.csv_path)
            settings = load_settings()
            analysis_settings = settings.data_type_analysis
            results = analyze_column_types(
                dataframe,
                detect_nominal_attributes=analysis_settings.detect_nominal_attributes,
                nominal_unique_threshold_percent=(
                    analysis_settings.nominal_unique_threshold_percent
                ),
            )
        except (OSError, ValueError, pd.errors.ParserError) as error:
            print(f"Ошибка: {error}", file=sys.stderr)
            return 1

        print(f"Файл: {args.csv_path}")
        print(
            f"Размер: {len(dataframe)} строк × "
            f"{len(dataframe.columns)} столбцов\n"
        )
        print(
            _format_analysis(
                results,
                settings.data_type_analysis.detect_nominal_attributes,
            )
        )
        if not settings.data_type_analysis.detect_nominal_attributes:
            print(
                "\nОпределение номинальных атрибутов "
                "выключено в настройках."
            )
        else:
            threshold = settings.data_type_analysis.nominal_unique_threshold_percent
            print(
                f"\nПорог номинальности: не более {threshold:g}% "
                "уникальных непустых значений."
            )
        return 0

    parser.print_help()
    return 0

