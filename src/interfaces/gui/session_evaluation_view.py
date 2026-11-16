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

        checks_frame = ttk.Frame(notebook)
        notebook.add(checks_frame, text="Приватность")
        checks = release.get("checks", [])
        checks_frame.columnconfigure(0, weight=1)
        checks_frame.rowconfigure(0, weight=1)
        checks_df = pd.DataFrame(
            [
                {
                    "Проверка": item.get("check", "—"),
                    "Статус": self._status_label(item.get("status")),
                    "Результат": item.get("details", "—"),
                }
                for item in checks
            ],
            columns=["Проверка", "Статус", "Результат"],
        )
        DataFrameTable(checks_frame, checks_df, include_index=False).pack(fill="both", expand=True)
        limitation = ttk.Label(
            checks_frame,
            text="Проверка не анализирует внешние источники и не гарантирует невозможность повторной идентификации.",
            wraplength=1050,
            foreground="#667085",
        )
        limitation.pack(anchor="w", pady=(6, 0))

        attributes_frame = ttk.Frame(notebook)
        notebook.add(attributes_frame, text="Изменения атрибутов")
        attributes = utility.attributes if utility is not None else pd.DataFrame()
        if attributes.empty:
            ttk.Label(attributes_frame, text="Нет общих атрибутов для сравнения.", padding=16).pack(anchor="center", expand=True)
        else:
            DataFrameTable(attributes_frame, attributes, include_index=False).pack(fill="both", expand=True)

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
            DataFrameTable(correlations_frame, correlations, include_index=False).pack(fill="both", expand=True)

        if utility is not None and utility.excluded_columns:
            excluded = ttk.Label(
                self,
                text="Из сравнения исключены прямые идентификаторы: " + ", ".join(utility.excluded_columns),
                foreground="#667085",
            )
            excluded.pack(anchor="w", pady=(6, 0))

    @staticmethod
    def _status_label(status: str | None) -> str:
        return {
            "passed": "Пройдена",
            "warning": "Предупреждение",
            "blocked": "Блокировка",
        }.get(status or "", "Не проверено")
