import tkinter as tk
from tkinter import ttk

from data_processing.schema_inspector import ColumnTypeResult
from interfaces.gui.tooltip import ToolTip


APP_BACKGROUND = "#F4F5F7"


class ColumnTypesWindow(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Misc,
        results: list[ColumnTypeResult],
        nominal_detection_enabled: bool,
    ):
        super().__init__(parent)
        self.title("Типы данных столбцов")
        self.geometry("780x460")
        self.minsize(600, 320)
        self.transient(parent)
        self.configure(background=APP_BACKGROUND)

        style = ttk.Style(self)
        style.configure("ColumnTypes.TFrame", background=APP_BACKGROUND)
        style.configure("ColumnTypes.TLabel", background=APP_BACKGROUND, foreground="#202938")
        style.configure(
            "ColumnTypes.Treeview",
            rowheight=28,
            background="#FFFFFF",
            fieldbackground="#FFFFFF",
            foreground="#202938",
        )
        style.configure(
            "ColumnTypes.Treeview.Heading",
            background="#DCE6F1",
            foreground="#64748B",
            font=("Segoe UI", 10, "bold"),
            padding=(8, 7),
            relief="flat",
        )

        container = ttk.Frame(self, padding=14, style="ColumnTypes.TFrame")
        container.pack(fill="both", expand=True)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(0, weight=1)

        columns = ("attribute", "dtype", "nominal", "unique")
        self.table = ttk.Treeview(
            container,
            columns=columns,
            show="headings",
            style="ColumnTypes.Treeview",
        )
        headings = {
            "attribute": ("Атрибут", 210),
            "dtype": ("Тип Pandas", 130),
            "nominal": ("Номинальный", 130),
            "unique": ("Уникальные значения", 190),
        }
        for column, (heading, width) in headings.items():
            self.table.heading(column, text=heading)
            self.table.column(column, width=width, minwidth=90, anchor="w")

        self.table.tag_configure("row_even", background="#FFFFFF")
        self.table.tag_configure("row_odd", background="#F1F5F9")
        scrollbar = ttk.Scrollbar(
            container,
            orient="vertical",
            command=self.table.yview,
        )
        self.table.configure(yscrollcommand=scrollbar.set)
        self.table.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        for index, result in enumerate(results):
            if result.is_nominal is None:
                nominal = (
                    "не проверялось"
                    if not nominal_detection_enabled
                    else "нет данных"
                )
            else:
                nominal = "да" if result.is_nominal else "нет"
            if result.unique_count is None:
                unique = "не рассчитывалось"
            elif result.unique_percent is None:
                unique = f"{result.unique_count}/{result.non_null_count} (нет данных)"
            else:
                unique = (
                    f"{result.unique_count}/{result.non_null_count} "
                    f"({result.unique_percent:.2f}%)"
                )
            tag = "row_even" if index % 2 == 0 else "row_odd"
            self.table.insert(
                "",
                "end",
                values=(result.attribute, result.pandas_type, nominal, unique),
                tags=(tag,),
            )

        info = ttk.Label(
            container,
            text="ⓘ Справка по номинальности",
            style="ColumnTypes.TLabel",
            cursor="question_arrow",
        )
        info.grid(row=1, column=0, columnspan=2, sticky="w", pady=(10, 0))
        explanation = (
            "Номинальность определяется по доле уникальных непустых значений. "
            "Эта эвристика не заменяет смысловую классификацию."
            if nominal_detection_enabled
            else "Определение номинальных атрибутов выключено в настройках."
        )
        ToolTip(info, explanation)
