import csv
from pathlib import Path

import pandas as pd


def load_csv(file_path: str | Path) -> pd.DataFrame:
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"Файл не найден: {path}")

    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "utf-8", "cp1251"):
        try:
            with path.open("r", encoding=encoding, newline="") as file:
                sample = file.read(8192)
            try:
                separator = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
            except csv.Error:
                separator = ","

            dataframe = pd.read_csv(
                path,
                sep=separator,
                encoding=encoding,
                dtype_backend="numpy_nullable",
            )
            if len(dataframe.columns) == 0:
                raise ValueError("CSV-файл не содержит столбцов.")
            return dataframe
        except (UnicodeDecodeError, pd.errors.ParserError, ValueError) as error:
            last_error = error

    raise ValueError(
        "Не удалось прочитать CSV. Проверь кодировку, разделитель и структуру файла."
    ) from last_error


def save_csv(dataframe: pd.DataFrame, file_path: str | Path) -> None:
    path = Path(file_path)
    if not path.parent.exists():
        raise FileNotFoundError(f"Папка для сохранения не существует: {path.parent}")
    dataframe.to_csv(path, index=False, encoding="utf-8-sig")
