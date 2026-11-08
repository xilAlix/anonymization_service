from pathlib import Path
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import pandas as pd

from data_processing.csv_handler import load_csv


def enable_windows_dpi_awareness() -> None:
    if sys.platform != "win32":
        return

    try:
        import ctypes

        # Per-Monitor V2 помогает Windows не растягивать окно bitmap-ом на мониторах с разным DPI.
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except (AttributeError, OSError):
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except (AttributeError, OSError):
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except (AttributeError, OSError):
                pass


class TableViewer(tk.Tk):
    def __init__(self, example_path: Path):
        super().__init__()
        self.example_path = example_path
        self.current_dataframe: pd.DataFrame | None = None
        self.preview_limit = 500

        self.title("Сервис анонимизации")
        self.geometry("1120x700")
        self.minsize(780, 480)
        self._build_widgets()
        self.open_example()

    def _build_widgets(self) -> None:
        style = ttk.Style(self)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure(
            "Treeview",
            background="#FFFFFF",
            fieldbackground="#FFFFFF",
            foreground="#202938",
            rowheight=27,
            borderwidth=0,
        )
        style.configure(
            "Treeview.Heading",
            background="#DCE6F1",
            foreground="#20334A",
            font=("Segoe UI", 10, "bold"),
            padding=(8, 7),
            relief="flat",
        )
        style.map(
            "Treeview.Heading",
            background=[("active", "#C9D8E8")],
        )

        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        ttk.Label(
            self,
            text="Сервис анонимизации",
            font=("Segoe UI", 17, "bold"),
        ).grid(row=0, column=0, sticky="w", padx=18, pady=(16, 4))

        ttk.Label(
            self,
            text="Просмотр одной CSV-таблицы. Исходный файл не изменяется.",
        ).grid(row=1, column=0, sticky="w", padx=18, pady=(0, 12))

        content = ttk.Frame(self, padding=(18, 0, 18, 12))
        content.grid(row=2, column=0, sticky="nsew")
        content.columnconfigure(0, weight=1)
        content.rowconfigure(1, weight=1)

        toolbar = ttk.Frame(content)
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 10))

        self.table_info = tk.StringVar(value="Таблица не загружена")
        ttk.Label(toolbar, textvariable=self.table_info).pack(side="left", padx=(0, 12))
        ttk.Button(toolbar, text="Открыть CSV", command=self.open_csv).pack(side="left", padx=(0, 7))
        ttk.Button(toolbar, text="Открыть пример", command=self.open_example).pack(side="left", padx=(0, 7))
        ttk.Button(toolbar, text="Анонимизировать", state="disabled").pack(side="left", padx=(10, 7))
        ttk.Button(toolbar, text="Оценить результат", state="disabled").pack(side="left")

        table_frame = ttk.Frame(content)
        table_frame.grid(row=1, column=0, sticky="nsew")
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)

        self.table = ttk.Treeview(table_frame, show="headings")
        self.table.tag_configure("row_even", background="#FFFFFF")
        self.table.tag_configure("row_odd", background="#F1F5F9")
        vertical_scroll = ttk.Scrollbar(
            table_frame, orient="vertical", command=self.table.yview
        )
        horizontal_scroll = ttk.Scrollbar(
            table_frame, orient="horizontal", command=self.table.xview
        )
        self.table.configure(
            yscrollcommand=vertical_scroll.set,
            xscrollcommand=horizontal_scroll.set,
        )

        self.table.grid(row=0, column=0, sticky="nsew")
        vertical_scroll.grid(row=0, column=1, sticky="ns")
        horizontal_scroll.grid(row=1, column=0, sticky="ew")

        self.status = tk.StringVar(value="Откройте CSV-файл или просмотрите подготовленный пример.")
        ttk.Label(
            self,
            textvariable=self.status,
            relief="sunken",
            anchor="w",
            padding=7,
        ).grid(row=3, column=0, sticky="ew")

    def _show_dataframe(self, dataframe: pd.DataFrame, file_name: str) -> None:
        self.current_dataframe = dataframe
        columns = [str(column) for column in dataframe.columns]
        self.table.delete(*self.table.get_children())
        self.table.configure(columns=columns)

        for column in columns:
            self.table.heading(column, text=column)
            self.table.column(column, width=150, minwidth=90, anchor="w", stretch=True)

        # GUI показывает ограниченное число строк, но DataFrame загружается целиком.
        preview = dataframe.head(self.preview_limit)
        for row_number, row in enumerate(preview.itertuples(index=False, name=None)):
            values = ["" if pd.isna(value) else str(value) for value in row]
            row_style = "row_even" if row_number % 2 == 0 else "row_odd"
            self.table.insert("", "end", values=values, tags=(row_style,))

        row_count, column_count = dataframe.shape
        self.table_info.set(f"{file_name}  |  {row_count} строк × {column_count} столбцов")
        if row_count > self.preview_limit:
            self.status.set(
                f"Показаны первые {self.preview_limit} строк из {row_count}. "
                "Исходный набор загружен полностью."
            )
        else:
            self.status.set("Таблица успешно загружена. Исходный файл не изменён.")

    def open_csv(self) -> None:
        selected_file = filedialog.askopenfilename(
            title="Открыть таблицу CSV",
            filetypes=(("CSV-файлы", "*.csv"), ("Все файлы", "*.*")),
        )
        if not selected_file:
            return

        try:
            dataframe = load_csv(selected_file)
            self._show_dataframe(dataframe, Path(selected_file).name)
        except (OSError, ValueError, pd.errors.ParserError) as error:
            messagebox.showerror("Ошибка открытия файла", str(error))
            self.status.set("Не удалось загрузить выбранный файл.")

    def open_example(self) -> None:
        try:
            dataframe = load_csv(self.example_path)
            self._show_dataframe(dataframe, self.example_path.name)
        except (OSError, ValueError, pd.errors.ParserError) as error:
            messagebox.showerror("Ошибка открытия примера", str(error))

