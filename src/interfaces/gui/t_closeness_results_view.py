from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any


class TClosenessResultsWindow(tk.Toplevel):
    def __init__(self, parent: tk.Misc, report: dict[str, Any]):
        super().__init__(parent)
        self.title("Диагностика t-близости")
        self.geometry("980x540")
        self.minsize(760, 400)
        self.transient(parent)
        self.configure(background="#F4F5F7")

        status = report.get("status", "unknown")
        if status == "satisfied":
            status_text, status_color = "Проверка t-близости пройдена", "#18794E"
        elif status == "not_evaluable":
            status_text, status_color = "Проверку t-близости невозможно выполнить", "#9A6700"
        else:
            status_text, status_color = "Проверка t-близости не пройдена", "#B42318"

        content = ttk.Frame(self, padding=14)
        content.pack(fill="both", expand=True)
        content.columnconfigure(0, weight=1)
        content.rowconfigure(2, weight=1)
        ttk.Label(
            content,
            text=status_text,
            foreground=status_color,
            font=("Segoe UI", 12, "bold"),
        ).grid(row=0, column=0, sticky="w")

        summary = [
            f"t = {self._number(report.get('t'))}",
            f"проверок: {report.get('check_count', 0)}",
            f"нарушений: {report.get('failed_check_count', 0)}",
            f"не рассчитано: {report.get('not_evaluable_check_count', 0)}",
            f"максимальное расстояние: {self._number(report.get('maximum_distance'))}",
        ]
        ttk.Label(content, text="  |  ".join(summary), foreground="#475467").grid(
            row=1, column=0, sticky="w", pady=(4, 8)
        )

        table_frame = ttk.Frame(content)
        table_frame.grid(row=2, column=0, sticky="nsew")
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)
        columns = ("profile", "attributes", "sensitive", "class", "rows", "metric", "distance", "threshold", "status")
        self.table = ttk.Treeview(table_frame, columns=columns, show="headings", height=14)
        headings = {
            "profile": ("QI-профиль", 150),
            "attributes": ("QI-атрибуты", 160),
            "sensitive": ("Конфиденциальное поле", 150),
            "class": ("Класс", 55),
            "rows": ("Строк", 55),
            "metric": ("Метрика", 175),
            "distance": ("Расстояние", 90),
            "threshold": ("Порог t", 75),
            "status": ("Результат", 90),
        }
        for column, (label, width) in headings.items():
            self.table.heading(column, text=label)
            self.table.column(column, width=width, minwidth=50, anchor="w")
        self.table.tag_configure("passed", foreground="#18794E")
        self.table.tag_configure("failed", foreground="#B42318")
        self.table.tag_configure("unknown", foreground="#9A6700")
        vertical = ttk.Scrollbar(table_frame, orient="vertical", command=self.table.yview)
        horizontal = ttk.Scrollbar(table_frame, orient="horizontal", command=self.table.xview)
        self.table.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.table.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")

        for check in report.get("checks", []):
            evaluated = check.get("evaluated", True)
            satisfied = check.get("satisfied")
            result_text = "Пройдена" if satisfied is True else "Нарушена" if satisfied is False else "Не рассчитано"
            tag = "passed" if satisfied is True else "failed" if satisfied is False else "unknown"
            profile_attributes = check.get("profile_attributes", [])
            self.table.insert(
                "", "end",
                values=(
                    check.get("profile_name", "—"),
                    ", ".join(profile_attributes) or "—",
                    check.get("sensitive_attribute", "—"),
                    check.get("class_number", "—"),
                    check.get("class_size", "—"),
                    check.get("metric", "—"),
                    self._number(check.get("distance")),
                    self._number(check.get("t", report.get("t"))),
                    result_text,
                ),
                tags=(tag,),
            )

        notes = []
        if report.get("reason"):
            notes.append(str(report["reason"]))
        notes.extend(str(item) for item in report.get("notes", []))
        if not notes:
            notes.append(
                "Числовые/временные поля: нормализованная EMD; номинальные категории: TVD. "
                "Для категорий без естественного порядка TVD используется как выбранная "
                "экспериментальная политика расстояния."
            )
        note_frame = ttk.Frame(content)
        note_frame.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        note_frame.columnconfigure(0, weight=1)
        ttk.Label(
            note_frame, text="\n".join(notes), foreground="#667085",
            wraplength=920, justify="left",
        ).grid(row=0, column=0, sticky="w")
        ttk.Button(note_frame, text="Закрыть", command=self.destroy).grid(
            row=1, column=0, sticky="e", pady=(8, 0)
        )

    @staticmethod
    def _number(value: Any) -> str:
        if value is None:
            return "—"
        try:
            return f"{float(value):.6f}"
        except (TypeError, ValueError):
            return str(value)
