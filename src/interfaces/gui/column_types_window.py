from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable

from data_processing.schema_inspector import ColumnTypeResult
from data_processing.semantic_types import SEMANTIC_TYPE_LABELS
from interfaces.gui.tooltip import ToolTip


APP_BACKGROUND = "#F4F5F7"
LABEL_TO_TYPE = {label: key for key, label in SEMANTIC_TYPE_LABELS.items()}


class ColumnTypesWindow(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Misc,
        results: list[ColumnTypeResult],
        nominal_detection_enabled: bool,
        semantic_types: dict[str, str] | None = None,
        save_semantic_type: Callable[[str, str], bool] | None = None,
    ):
        super().__init__(parent)
        self.title("Типы данных и семантика атрибутов")
        self.geometry("1120x580")
        self.minsize(840, 440)
        self.transient(parent)
        self.configure(background=APP_BACKGROUND)

        self.results = results
        self.nominal_detection_enabled = nominal_detection_enabled
        self.semantic_types = dict(semantic_types or {})
        self._save_semantic_type = save_semantic_type or (lambda _column, _kind: False)
        self._selected_column: str | None = None
        self.selected_type = tk.StringVar(value=SEMANTIC_TYPE_LABELS["auto"])

        style = ttk.Style(self)
        style.configure("ColumnTypes.TFrame", background=APP_BACKGROUND)
        style.configure("ColumnTypes.TLabel", background=APP_BACKGROUND, foreground="#202938")
        style.configure(
            "ColumnTypes.Treeview",
            rowheight=29,
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

        columns = ("attribute", "dtype", "suggested", "applied", "nominal", "unique")
        self.table = ttk.Treeview(
            container,
            columns=columns,
            show="headings",
            style="ColumnTypes.Treeview",
            selectmode="browse",
        )
        headings = {
            "attribute": ("Атрибут", 170),
            "dtype": ("Тип Pandas", 105),
            "suggested": ("Предложение", 145),
            "applied": ("Используемый тип", 180),
            "nominal": ("Номинальный", 110),
            "unique": ("Уникальные значения", 175),
        }
        for column, (heading, width) in headings.items():
            self.table.heading(column, text=heading)
            self.table.column(column, width=width, minwidth=90, anchor="w")
        self.table.tag_configure("row_even", background="#FFFFFF")
        self.table.tag_configure("row_odd", background="#F1F5F9")
        vertical = ttk.Scrollbar(container, orient="vertical", command=self.table.yview)
        horizontal = ttk.Scrollbar(container, orient="horizontal", command=self.table.xview)
        self.table.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.table.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        self.table.bind("<<TreeviewSelect>>", self._selection_changed)

        controls = ttk.Frame(container, style="ColumnTypes.TFrame")
        controls.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        controls.columnconfigure(1, weight=1)
        ttk.Label(
            controls,
            text="Смысл выбранного атрибута:",
            style="ColumnTypes.TLabel",
        ).grid(row=0, column=0, sticky="w")
        self.type_select = ttk.Combobox(
            controls,
            textvariable=self.selected_type,
            values=tuple(SEMANTIC_TYPE_LABELS.values()),
            state="readonly",
            width=27,
        )
        self.type_select.grid(row=0, column=1, sticky="w", padx=(10, 0))
        self.apply_button = ttk.Button(
            controls,
            text="Применить к полю",
            command=self._apply_to_selected,
            state="disabled",
        )
        self.apply_button.grid(row=0, column=2, sticky="e", padx=(10, 0))
        ToolTip(
            self.type_select,
            "Числовой — количественные значения; категориальный — коды групп и названия; "
            "дата/время — временные значения; идентификатороподобный — номера и коды, "
            "которые нельзя усреднять. Автоматически возвращает стандартное определение.",
        )
        ToolTip(
            self.apply_button,
            "Сохраняет семантический тип в профиле текущего CSV. Тип влияет на анализ, "
            "корреляции и обработку квази-идентификаторов, но не назначает роль приватности.",
        )

        self.hint = ttk.Label(
            controls,
            text="Выберите столбец, задайте его смысл и нажмите «Применить к полю».",
            style="ColumnTypes.TLabel",
            foreground="#667085",
        )
        self.hint.grid(row=1, column=0, columnspan=3, sticky="w", pady=(8, 0))
        ToolTip(
            self.hint,
            "Технический тип Pandas описывает способ хранения значений. Семантический тип "
            "описывает их смысл. Например, почтовый индекс может храниться как integer, "
            "но должен обрабатываться как идентификатороподобное значение.",
        )
        self._render_rows()

    def _render_rows(self) -> None:
        self.table.delete(*self.table.get_children())
        for index, result in enumerate(self.results):
            if result.is_nominal is None:
                nominal = "не проверялось" if not self.nominal_detection_enabled else "нет данных"
            else:
                nominal = "да" if result.is_nominal else "нет"
            if result.unique_count is None:
                unique = "не рассчитывалось"
            elif result.unique_percent is None:
                unique = f"{result.unique_count}/{result.non_null_count} (нет данных)"
            else:
                unique = f"{result.unique_count}/{result.non_null_count} ({result.unique_percent:.2f}%)"
            assigned = self.semantic_types.get(result.attribute)
            applied_type = assigned or result.suggested_semantic_type
            applied_label = SEMANTIC_TYPE_LABELS[applied_type]
            applied_label += " (вручную)" if assigned else " (авто)"
            self.table.insert(
                "",
                "end",
                iid=str(index),
                values=(
                    result.attribute,
                    result.pandas_type,
                    SEMANTIC_TYPE_LABELS[result.suggested_semantic_type],
                    applied_label,
                    nominal,
                    unique,
                ),
                tags=("row_even" if index % 2 == 0 else "row_odd",),
            )

    def _selection_changed(self, _event=None) -> None:
        selected = self.table.selection()
        if not selected:
            self._selected_column = None
            self.apply_button.configure(state="disabled")
            return
        item = self.table.item(selected[0], "values")
        self._selected_column = str(item[0])
        current = self.semantic_types.get(self._selected_column, "auto")
        self.selected_type.set(SEMANTIC_TYPE_LABELS[current])
        self.apply_button.configure(state="normal")

    def _apply_to_selected(self) -> None:
        if self._selected_column is None:
            return
        semantic_type = LABEL_TO_TYPE.get(self.selected_type.get(), "auto")
        try:
            saved = self._save_semantic_type(self._selected_column, semantic_type)
        except (OSError, ValueError) as error:
            messagebox.showerror("Ошибка сохранения типа", str(error), parent=self)
            return
        if not saved:
            return
        if semantic_type == "auto":
            self.semantic_types.pop(self._selected_column, None)
        else:
            self.semantic_types[self._selected_column] = semantic_type
        self._render_rows()
        self.hint.configure(
            text=f"Для «{self._selected_column}» применён тип «{SEMANTIC_TYPE_LABELS[semantic_type]}»."
        )
        self.table.selection_set(self.table.get_children()[int(next(
            index for index, result in enumerate(self.results)
            if result.attribute == self._selected_column
        ))])
