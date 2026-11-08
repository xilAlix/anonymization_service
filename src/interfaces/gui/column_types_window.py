import tkinter as tk
from tkinter import ttk


class ColumnTypesWindow(tk.Toplevel):
    def __init__(self, parent: tk.Misc, column_types: list[tuple[str, str]]):
        super().__init__(parent)
        self.title("Типы данных столбцов")
        self.geometry("620x440")
        self.minsize(460, 300)
        self.transient(parent)

        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        table_frame = ttk.Frame(self, padding=14)
        table_frame.grid(row=0, column=0, sticky="nsew")
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)

        style = ttk.Style(self)
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

        self.table = ttk.Treeview(
            table_frame,
            columns=("attribute", "dtype"),
            show="headings",
            style="ColumnTypes.Treeview",
        )
        self.table.heading("attribute", text="Атрибут")
        self.table.heading("dtype", text="Тип данных (Pandas)")
        self.table.column("attribute", width=260, minwidth=150, anchor="w")
        self.table.column("dtype", width=220, minwidth=140, anchor="w")
        self.table.tag_configure("row_even", background="#FFFFFF")
        self.table.tag_configure("row_odd", background="#F1F5F9")

        scrollbar = ttk.Scrollbar(
            table_frame, orient="vertical", command=self.table.yview
        )
        self.table.configure(yscrollcommand=scrollbar.set)
        self.table.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        for index, (attribute, dtype) in enumerate(column_types):
            tag = "row_even" if index % 2 == 0 else "row_odd"
            self.table.insert(
                "", "end", values=(attribute, dtype), tags=(tag,)
            )

        ttk.Label(
            self,
            text=(
                "Показаны технические типы, определённые Pandas. "
                "Семантическая роль атрибута здесь не определяется."
            ),
            wraplength=580,
            padding=(14, 0, 14, 12),
        ).grid(row=1, column=0, sticky="w")
