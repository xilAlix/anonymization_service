import csv
import os
import tempfile
from pathlib import Path

import pandas as pd

from infrastructure.file_safety import (
    MAX_CSV_CELLS,
    MAX_CSV_COLUMNS,
    MAX_CSV_ROWS,
    validate_input_file,
    validate_output_file,
)


CHUNK_SIZE = 25_000


def load_csv(file_path: str | Path) -> pd.DataFrame:
    path = validate_input_file(file_path)
    last_error: Exception | None = None

    for encoding in ("utf-8-sig", "utf-8", "cp1251"):
        try:
            with path.open("r", encoding=encoding, newline="") as file:
                sample = file.read(8192)
            try:
                separator = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
            except csv.Error:
                separator = ","

            chunks: list[pd.DataFrame] = []
            row_count = 0
            reader = pd.read_csv(
                path,
                sep=separator,
                encoding=encoding,
                dtype_backend="numpy_nullable",
                chunksize=CHUNK_SIZE,
            )
            with reader:
                for chunk in reader:
                    if len(chunk.columns) == 0:
                        raise ValueError("CSV-файл не содержит столбцов.")
                    column_count = len(chunk.columns)
                    if column_count > MAX_CSV_COLUMNS:
                        raise ValueError(
                            f"CSV содержит {column_count} столбцов; допустимо не более {MAX_CSV_COLUMNS}."
                        )
                    row_count += len(chunk)
                    if row_count > MAX_CSV_ROWS:
                        raise ValueError(
                            f"CSV содержит больше {MAX_CSV_ROWS:,} строк. Разделите файл на несколько частей."
                        )
                    if row_count * column_count > MAX_CSV_CELLS:
                        raise ValueError(
                            f"CSV превышает ограничение {MAX_CSV_CELLS:,} ячеек. "
                            "Разделите файл или сократите число столбцов."
                        )
                    chunks.append(chunk)

            if not chunks:
                raise ValueError("CSV-файл пуст или не содержит строк заголовка.")
            return pd.concat(chunks, ignore_index=True)
        except (UnicodeDecodeError, pd.errors.ParserError, pd.errors.EmptyDataError, ValueError) as error:
            if isinstance(error, ValueError) and any(
                marker in str(error)
                for marker in ("ограничение", "допустимо не более", "Разделите файл", "не содержит столбцов")
            ):
                raise
            last_error = error

    raise ValueError(
        "Не удалось прочитать CSV. Проверьте кодировку, разделитель и структуру файла."
    ) from last_error


def save_csv(
    dataframe: pd.DataFrame,
    file_path: str | Path,
    *,
    index: bool = False,
    index_label: str | None = None,
) -> None:
    path = validate_output_file(file_path)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8-sig",
            newline="",
            suffix=path.suffix or ".csv",
            prefix=".anonymization-",
            dir=path.parent,
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            dataframe.to_csv(
                temporary_file,
                index=index,
                index_label=index_label,
            )
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        if os.name != "nt":
            os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
