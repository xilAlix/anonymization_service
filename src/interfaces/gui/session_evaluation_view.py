from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import pandas as pd

from application.session_workflow import DatasetSession
from interfaces.gui.analysis_results_view import DataFrameTable


STATUS_PRESENTATION = {
    "ready": ("Проверки пройдены", "#166534", "#DCFCE7"),
    "warning": ("Требуется внимание", "#92400E", "#FEF3C7"),
    "blocked": ("Передачу не рекомендуется выполнять", "#991B1B", "#FEE2E2"),
}

CHECK_STATUS_PRESENTATION = {
    "passed": ("Пройдена", "#166534", "#DCFCE7"),
    "warning": ("Предупреждение", "#92400E", "#FEF3C7"),
    "blocked": ("Блокировка", "#991B1B", "#FEE2E2"),
}


def orient_attribute_changes(attributes: pd.DataFrame) -> pd.DataFrame:
    """Возвращает показатели строками, а атрибуты — столбцами."""
    if attributes.empty or "Атрибут" not in attributes.columns:
        return pd.DataFrame()
    display = attributes.set_index("Атрибут").transpose()
    display.index.name = "Показатель"
    return display


def _format_correlation_value(value) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"{float(value):.3f}"


def _format_observation_count(value) -> str:
    if value is None or pd.isna(value):
        return "—"
    return str(int(value))


def build_correlation_matrix(correlations: pd.DataFrame, method: str) -> pd.DataFrame:
    """Строит симметричную матрицу сравнения корреляций до и после обработки."""
    required = {
        "Атрибут 1", "Атрибут 2", "Метод", "Коэффициент до", "Коэффициент после",
        "Абсолютное изменение", "Парных наблюдений до", "Парных наблюдений после",
    }
    if correlations.empty or not required.issubset(correlations.columns):
        return pd.DataFrame()

    selected = correlations[
        correlations["Метод"].astype(str).str.casefold() == method.casefold()
    ]
    if selected.empty:
        return pd.DataFrame()

    attributes: list[str] = []
    for column in ("Атрибут 1", "Атрибут 2"):
        for value in selected[column].astype(str):
            if value not in attributes:
                attributes.append(value)

    matrix = pd.DataFrame("—", index=attributes, columns=attributes, dtype=object)
    matrix.index.name = "Атрибут"

    for item in selected.to_dict(orient="records"):
        first = str(item["Атрибут 1"])
        second = str(item["Атрибут 2"])
        before = _format_correlation_value(item["Коэффициент до"])
        after = _format_correlation_value(item["Коэффициент после"])
        change = _format_correlation_value(item["Абсолютное изменение"])
        before_n = _format_observation_count(item["Парных наблюдений до"])
        after_n = _format_observation_count(item["Парных наблюдений после"])
        cell = f"{before} → {after} | Δ {change} | n {before_n}→{after_n}"
        matrix.at[first, second] = cell
        matrix.at[second, first] = cell

    return matrix


class SessionEvaluationView(ttk.Frame):
    def __init__(self, parent: tk.Misc, session: DatasetSession):
        super().__init__(parent, padding=10)
        self.session = session
        release = session.release_check or {}
        utility = session.utility_evaluation
        status = release.get("status", "warning")
        label, foreground, background = STATUS_PRESENTATION.get(
            status, STATUS_PRESENTATION["warning"]
        )

        banner = tk.Frame(self, background=background, padx=12, pady=9)
        banner.pack(fill="x", pady=(0, 8))
        tk.Label(
            banner,
            text=f"Проверка приватности: {label}",
            background=background,
            foreground=foreground,
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor="w")
        tk.Label(
            banner,
            text=(
                "Результат сохранён локально. Этот статус отражает выбранные проверки "
                "и не является гарантией абсолютной анонимности."
            ),
            background=background,
            foreground=foreground,
            justify="left",
            wraplength=1050,
        ).pack(anchor="w", pady=(3, 0))

        if utility is not None:
            summary = utility.summary
            summary_text = (
                f"Сравниваются {summary['common_columns']} общих атрибутов; "
                f"числовых: {summary['numeric_columns']}; "
                f"категориальных/прочих: {summary['categorical_columns']}; "
                f"строк: {summary['original_rows']} → {summary['transformed_rows']}."
            )
        else:
            summary_text = "Сравнение аналитической полезности недоступно."
        ttk.Label(self, text=summary_text, wraplength=1080).pack(anchor="w", pady=(0, 8))

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True)

        checks_frame = ttk.Frame(notebook, padding=6)
        notebook.add(checks_frame, text="Приватность")
        self._build_check_cards(checks_frame, release.get("checks", []))
        limitation = ttk.Label(
            checks_frame,
            text="Проверка не анализирует внешние источники и не гарантирует невозможность повторной идентификации.",
            wraplength=1050,
            foreground="#667085",
        )
        limitation.pack(anchor="w", pady=(7, 0))

        attributes_frame = ttk.Frame(notebook)
        notebook.add(attributes_frame, text="Изменения атрибутов")
        attributes = utility.attributes if utility is not None else pd.DataFrame()
        if attributes.empty:
            ttk.Label(attributes_frame, text="Нет общих атрибутов для сравнения.", padding=16).pack(anchor="center", expand=True)
        else:
            ttk.Label(
                attributes_frame,
                text="Атрибуты расположены в столбцах, показатели — в строках.",
                padding=(6, 6),
            ).pack(anchor="w")
            attribute_matrix = orient_attribute_changes(attributes)
            DataFrameTable(attributes_frame, attribute_matrix, include_index=True).pack(fill="both", expand=True)

        correlations_frame = ttk.Frame(notebook)
        notebook.add(correlations_frame, text="Изменения корреляций")
        correlations = utility.correlations if utility is not None else pd.DataFrame()
        if correlations.empty:
            ttk.Label(
                correlations_frame,
                text="Для сравнения корреляций нужно не менее двух общих числовых атрибутов.",
                padding=16,
            ).pack(anchor="center", expand=True)
        else:
            ttk.Label(
                correlations_frame,
                text=(
                    "Строки и столбцы — атрибуты. В ячейке: корреляция до → после, "
                    "абсолютное изменение и число парных наблюдений до/после."
                ),
                padding=(6, 6),
                wraplength=1050,
            ).pack(anchor="w")
            correlation_notebook = ttk.Notebook(correlations_frame)
            correlation_notebook.pack(fill="both", expand=True)
            for method in ("Pearson", "Spearman"):
                matrix = build_correlation_matrix(correlations, method)
                if matrix.empty:
                    continue
                method_frame = ttk.Frame(correlation_notebook)
                correlation_notebook.add(method_frame, text=method)
                DataFrameTable(
                    method_frame,
                    matrix,
                    include_index=True,
                    column_width=360,
                    index_column_width=190,
                ).pack(fill="both", expand=True)

        if utility is not None and utility.excluded_columns:
            excluded = ttk.Label(
                self,
                text="Из сравнения исключены прямые идентификаторы: " + ", ".join(utility.excluded_columns),
                foreground="#667085",
            )
            excluded.pack(anchor="w", pady=(6, 0))

    def _build_check_cards(self, parent: ttk.Frame, checks: list[dict]) -> None:
        container = ttk.Frame(parent)
        container.pack(fill="both", expand=True)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(0, weight=1)

        canvas = tk.Canvas(container, highlightthickness=0, background="#F4F5F7")
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        cards = ttk.Frame(canvas)
        window_id = canvas.create_window((0, 0), window=cards, anchor="nw")
        cards.columnconfigure(0, weight=1)

        def update_scroll_region(_event=None) -> None:
            canvas.configure(scrollregion=canvas.bbox("all"))

        def update_width(event) -> None:
            canvas.itemconfigure(window_id, width=event.width)
            wrap = max(280, event.width - 210)
            for label_widget in detail_labels:
                label_widget.configure(wraplength=wrap)

        detail_labels: list[tk.Label] = []
        if not checks:
            ttk.Label(cards, text="Нет данных о проверках приватности.", padding=12).grid(
                row=0, column=0, sticky="w"
            )
        for index, item in enumerate(checks):
            check_name = str(item.get("check", "Проверка"))
            status_text, status_fg, status_bg = CHECK_STATUS_PRESENTATION.get(
                item.get("status"), ("Не проверено", "#475467", "#EAECF0")
            )
            card = tk.Frame(cards, background="#FFFFFF", padx=12, pady=9, highlightthickness=1, highlightbackground="#E4E7EC")
            card.grid(row=index, column=0, sticky="ew", pady=(0, 7))
            card.columnconfigure(0, weight=1)

            tk.Label(
                card,
                text=check_name,
                background="#FFFFFF",
                foreground="#202938",
                font=("Segoe UI", 10, "bold"),
                anchor="w",
            ).grid(row=0, column=0, sticky="ew")
            tk.Label(
                card,
                text=status_text,
                background=status_bg,
                foreground=status_fg,
                padx=7,
                pady=2,
                font=("Segoe UI", 9, "bold"),
            ).grid(row=0, column=1, sticky="e", padx=(10, 0))
            details = tk.Label(
                card,
                text=str(item.get("details", "—")),
                background="#FFFFFF",
                foreground="#475467",
                justify="left",
                anchor="w",
                wraplength=820,
                font=("Segoe UI", 9),
            )
            details.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(5, 0))
            detail_labels.append(details)

        cards.bind("<Configure>", update_scroll_region)
        canvas.bind("<Configure>", update_width)

        def on_mousewheel(event) -> None:
            if getattr(event, "delta", 0):
                canvas.yview_scroll(int(-event.delta / 120), "units")

        canvas.bind_all("<MouseWheel>", on_mousewheel, add="+")

    @staticmethod
    def _status_label(status: str | None) -> str:
        return {
            "passed": "Пройдена",
            "warning": "Предупреждение",
            "blocked": "Блокировка",
        }.get(status or "", "Не проверено")
