"""Простой интерфейс для просмотра одной CSV-таблицы.

Запуск из корня проекта:
    python src/application/main.py

Для работы требуется pandas. Tkinter входит в стандартную библиотеку Python.
"""

from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import pandas as pd


WINDOW_TITLE = "Сервис анонимизации"
MAX_PREVIEW_ROWS = 500


def read_csv_file(file_path: str | Path) -> pd.DataFrame:
    """Загрузить CSV, попробовав распространённые кодировки и разделители."""
    path = Path(file_path)
    encodings = ("utf-8-sig", "utf-8", "cp1251")
    separators = (";", ",", "\t", "|")
    last_error: Exception | None = None

    for encoding in encodings:
        try:
            # Автоопределение разделителя подходит для большинства обычных CSV.
            dataframe = pd.read_csv(path, sep=None, engine="python", encoding=encoding)

            # Если автоопределение оставило всё содержимое в одной колонке,
            # дополнительно проверяем распространённые разделители.
            if len(dataframe.columns) == 1:
                best_candidate = dataframe
                for separator in separators:
                    try:
                        candidate = pd.read_csv(path, sep=separator, encoding=encoding)
                        if len(candidate.columns) > len(best_candidate.columns):
                            best_candidate = candidate
                    except (pd.errors.ParserError, UnicodeDecodeError):
                        continue
                dataframe = best_candidate

            if dataframe.empty and len(dataframe.columns) == 0:
                raise ValueError("Файл не содержит таблицу с заголовками.")

            return dataframe
        except (UnicodeDecodeError, pd.errors.ParserError, ValueError) as error:
            last_error = error

    raise ValueError(
        "Не удалось прочитать CSV-файл. Проверьте кодировку, разделители и структуру файла."
    ) from last_error


def format_cell(value: object) -> str:
    """Подготовить значение ячейки к отображению в интерфейсе."""
    if pd.isna(value):
        return ""
    return str(value)


def populate_table(table: ttk.Treeview, dataframe: pd.DataFrame) -> None:
    """Отобразить содержимое DataFrame в таблице интерфейса."""
    table.delete(*table.get_children())

    column_names = [str(column) for column in dataframe.columns]
    table.configure(columns=column_names)

    for column in column_names:
        table.heading(column, text=column)
        table.column(column, width=150, minwidth=90, anchor="w", stretch=True)

    preview = dataframe.head(MAX_PREVIEW_ROWS)
    for row in preview.itertuples(index=False, name=None):
        table.insert("", "end", values=[format_cell(value) for value in row])


def main() -> None:
    root = tk.Tk()
    root.title(WINDOW_TITLE)
    root.geometry("1120x700")
    root.minsize(780, 480)

    root.columnconfigure(0, weight=1)
    root.rowconfigure(2, weight=1)

    current_dataframe: pd.DataFrame | None = None
    current_file_name = "Таблица не загружена"

    title_label = ttk.Label(root, text=WINDOW_TITLE, font=("Segoe UI", 17, "bold"))
    title_label.grid(row=0, column=0, sticky="w", padx=18, pady=(16, 4))

    description_label = ttk.Label(
        root,
        text="Просмотр одной таблицы CSV. Исходный файл не изменяется.",
    )
    description_label.grid(row=1, column=0, sticky="w", padx=18, pady=(0, 12))

    content = ttk.Frame(root, padding=(18, 0, 18, 12))
    content.grid(row=2, column=0, sticky="nsew")
    content.columnconfigure(0, weight=1)
    content.rowconfigure(1, weight=1)

    toolbar = ttk.Frame(content)
    toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 10))

    table_info_var = tk.StringVar(value=current_file_name)
    table_info = ttk.Label(toolbar, textvariable=table_info_var)
    table_info.pack(side="left", padx=(0, 12))

    table_frame = ttk.Frame(content)
    table_frame.grid(row=1, column=0, sticky="nsew")
    table_frame.columnconfigure(0, weight=1)
    table_frame.rowconfigure(0, weight=1)

    table = ttk.Treeview(table_frame, show="headings")
    vertical_scroll = ttk.Scrollbar(table_frame, orient="vertical", command=table.yview)
    horizontal_scroll = ttk.Scrollbar(table_frame, orient="horizontal", command=table.xview)
    table.configure(yscrollcommand=vertical_scroll.set, xscrollcommand=horizontal_scroll.set)

    table.grid(row=0, column=0, sticky="nsew")
    vertical_scroll.grid(row=0, column=1, sticky="ns")
    horizontal_scroll.grid(row=1, column=0, sticky="ew")

    status_var = tk.StringVar(value="Откройте CSV-файл или просмотрите подготовленный пример.")
    status_bar = ttk.Label(root, textvariable=status_var, relief="sunken", anchor="w", padding=7)
    status_bar.grid(row=3, column=0, sticky="ew")

    def show_dataframe(dataframe: pd.DataFrame, file_name: str) -> None:
        nonlocal current_dataframe, current_file_name
        current_dataframe = dataframe
        current_file_name = file_name
        populate_table(table, dataframe)

        row_count, column_count = dataframe.shape
        table_info_var.set(f"{file_name}  |  {row_count} строк × {column_count} столбцов")

        if row_count > MAX_PREVIEW_ROWS:
            status_var.set(
                f"Показаны первые {MAX_PREVIEW_ROWS} строк из {row_count}. "
                "Исходный набор данных загружен полностью."
            )
        else:
            status_var.set("Таблица успешно загружена. Исходный файл не изменён.")

    def open_csv() -> None:
        selected_file = filedialog.askopenfilename(
            title="Открыть таблицу CSV",
            filetypes=(("CSV-файлы", "*.csv"), ("Все файлы", "*.*")),
        )
        if not selected_file:
            return

        try:
            dataframe = read_csv_file(selected_file)
            show_dataframe(dataframe, Path(selected_file).name)
        except (OSError, ValueError, pd.errors.ParserError) as error:
            messagebox.showerror("Ошибка открытия файла", str(error))
            status_var.set("Не удалось загрузить выбранный файл.")

    def open_example() -> None:
        project_root = Path(__file__).resolve().parents[2]
        example_path = project_root / "data" / "synthetic" / "initial_dataset.csv"

        try:
            dataframe = read_csv_file(example_path)
            show_dataframe(dataframe, example_path.name)
        except (OSError, ValueError, pd.errors.ParserError) as error:
            messagebox.showerror("Ошибка открытия примера", str(error))

    ttk.Button(toolbar, text="Открыть CSV", command=open_csv).pack(side="left", padx=(0, 7))
    ttk.Button(toolbar, text="Открыть пример", command=open_example).pack(side="left", padx=(0, 7))

    # Будущие функции интерфейса. Пока намеренно неактивны.
    ttk.Button(toolbar, text="Анонимизировать", state="disabled").pack(side="left", padx=(10, 7))
    ttk.Button(toolbar, text="Оценить результат", state="disabled").pack(side="left")

    # При запуске сразу показываем демонстрационный набор данных.
    open_example()

    root.mainloop()


if __name__ == "__main__":
    main()
