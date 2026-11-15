from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import pandas as pd

from data_analysis.descriptive_statistics import DATE_FORMATS
from application.analysis_workflow import AnalysisResults


class DataFrameTable(ttk.Frame):
    def __init__(self, parent: tk.Misc, dataframe: pd.DataFrame, include_index: bool = True):
        super().__init__(parent)
        self.dataframe = dataframe
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        display = dataframe.copy()
        if include_index:
            display.insert(0, dataframe.index.name or "Показатель", dataframe.index.astype(str))
        columns = [str(column) for column in display.columns]

        self.tree = ttk.Treeview(self, columns=columns, show="headings")
        self.tree.tag_configure("row_even", background="#FFFFFF")
        self.tree.tag_configure("row_odd", background="#F1F5F9")
        for column in columns:
            self.tree.heading(column, text=column)
            width = 320 if column == "Показатель" else 220
            self.tree.column(column, width=width, minwidth=100, anchor="w", stretch=True)

        vertical = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        horizontal = ttk.Scrollbar(self, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")

        for row_index, row in enumerate(display.itertuples(index=False, name=None)):
            values = [self._format_value(value) for value in row]
            tag = "row_even" if row_index % 2 == 0 else "row_odd"
            self.tree.insert("", "end", values=values, tags=(tag,))

    @staticmethod
    def _format_value(value) -> str:
        if value is None or value is pd.NA:
            return "—"
        try:
            if pd.isna(value):
                return "—"
        except (TypeError, ValueError):
            pass
        if isinstance(value, float):
            return f"{value:.6f}".rstrip("0").rstrip(".")
        return str(value)


class AnalysisResultsView(ttk.Frame):
    def __init__(self, parent: tk.Misc, results: AnalysisResults, source_name: str):
        super().__init__(parent, padding=8)
        self.results = results
        summary = (
            f"Источник: {source_name}  |  {results.source_rows} строк  |  "
            f"Анализируются: {len(results.included_columns)} атриб."
        )
        if results.excluded_columns:
            summary += "  |  Исключены direct_identifier: " + ", ".join(results.excluded_columns)
        ttk.Label(self, text=summary, wraplength=1100).pack(anchor="w", pady=(0, 6))

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True)
        self._add_table_tab("Статистика", results.statistics)
        self._add_matrix_tab("Pearson", results.pearson, "Нет числовых атрибутов для корреляции Pearson.")
        self._add_matrix_tab("Spearman", results.spearman, "Нет числовых атрибутов для корреляции Spearman.")

    def _add_table_tab(self, title: str, dataframe: pd.DataFrame) -> None:
        frame = ttk.Frame(self.notebook)
        self.notebook.add(frame, text=title)
        DataFrameTable(frame, dataframe).pack(fill="both", expand=True)

    def _add_matrix_tab(self, title: str, dataframe: pd.DataFrame, empty_text: str) -> None:
        frame = ttk.Frame(self.notebook)
        self.notebook.add(frame, text=title)
        if dataframe.empty:
            ttk.Label(frame, text=empty_text, padding=20).pack(anchor="center", expand=True)
            return
        DataFrameTable(frame, dataframe).pack(fill="both", expand=True)


class DateColumnDialog(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Misc,
        dataframe: pd.DataFrame,
        current_formats: dict[str, str] | None = None,
    ):
        super().__init__(parent)
        self.title("Назначение столбцов дат")
        self.geometry("620x480")
        self.minsize(540, 400)
        self.transient(parent)
        self.grab_set()
        self.result: dict[str, str] | None = None
        self.dataframe = dataframe
        self.formats = dict(current_formats or {})
        self.format_labels = {label: value for label, value in DATE_FORMATS.items()}
        self.label_formats = {value: label for label, value in DATE_FORMATS.items()}

        outer = ttk.Frame(self, padding=12)
        outer.pack(fill="both", expand=True)
        ttk.Label(
            outer,
            text=(
                "Обычно даты определяются автоматически, если формат однозначен. "
                "Для неоднозначных или нестандартных столбцов выберите формат вручную."
            ),
            wraplength=570,
        ).pack(anchor="w", pady=(0, 10))

        controls = ttk.Frame(outer)
        controls.pack(fill="x")
        ttk.Label(controls, text="Столбец").grid(row=0, column=0, sticky="w")
        self.column_var = tk.StringVar()
        self.column_combo = ttk.Combobox(
            controls,
            textvariable=self.column_var,
            values=[str(column) for column in dataframe.columns],
            state="readonly",
            width=28,
        )
        self.column_combo.grid(row=1, column=0, sticky="ew", padx=(0, 8))
        if len(dataframe.columns):
            self.column_combo.current(0)
        ttk.Label(controls, text="Формат").grid(row=0, column=1, sticky="w")
        self.format_var = tk.StringVar(value=next(iter(self.format_labels.values())))
        self.format_combo = ttk.Combobox(
            controls,
            textvariable=self.format_var,
            values=list(self.format_labels.values()),
            state="readonly",
            width=27,
        )
        self.format_combo.grid(row=1, column=1, sticky="ew")
        controls.columnconfigure(0, weight=1)
        controls.columnconfigure(1, weight=1)

        self.sample_var = tk.StringVar(value="Примеры значений: —")
        ttk.Label(outer, textvariable=self.sample_var, foreground="#667085").pack(
            anchor="w", pady=(6, 8)
        )
        self.column_combo.bind("<<ComboboxSelected>>", self._update_sample)
        self._update_sample()

        ttk.Label(outer, text="Столбцы, назначенные датами вручную:").pack(anchor="w")
        list_frame = ttk.Frame(outer)
        list_frame.pack(fill="both", expand=True, pady=(4, 8))
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(list_frame, columns=("column", "format"), show="headings", height=8)
        self.tree.heading("column", text="Атрибут")
        self.tree.heading("format", text="Формат")
        self.tree.column("column", width=220)
        self.tree.column("format", width=280)
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.tree.bind("<<TreeviewSelect>>", self._select_assigned)
        self._refresh_tree()

        action_row = ttk.Frame(outer)
        action_row.pack(fill="x")
        ttk.Button(action_row, text="Назначить / изменить", command=self._assign).pack(side="left")
        ttk.Button(action_row, text="Убрать назначение", command=self._remove).pack(side="left", padx=(6, 0))
        ttk.Button(action_row, text="Отмена", command=self._cancel).pack(side="right")
        ttk.Button(action_row, text="Применить", command=self._apply).pack(side="right", padx=(0, 6))

    def _update_sample(self, _event=None) -> None:
        column = self.column_var.get()
        if column not in self.dataframe.columns:
            return
        values = self.dataframe[column].dropna().astype(str).head(3).tolist()
        self.sample_var.set("Примеры значений: " + ("; ".join(values) if values else "нет значений"))

    def _refresh_tree(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for column, date_format in self.formats.items():
            self.tree.insert("", "end", iid=column, values=(column, self.label_formats.get(date_format, date_format)))

    def _select_assigned(self, _event=None) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        column = selection[0]
        self.column_var.set(column)
        date_format = self.formats[column]
        self.format_var.set(self.label_formats.get(date_format, date_format))
        self._update_sample()

    def _assign(self) -> None:
        column = self.column_var.get()
        label = self.format_var.get()
        date_format = self.format_labels.get(label)
        if not column or date_format is None:
            return
        self.formats[column] = date_format
        self._refresh_tree()

    def _remove(self) -> None:
        selection = self.tree.selection()
        if selection:
            self.formats.pop(selection[0], None)
            self._refresh_tree()

    def _apply(self) -> None:
        self.result = dict(self.formats)
        self.destroy()

    def _cancel(self) -> None:
        self.result = None
        self.destroy()
