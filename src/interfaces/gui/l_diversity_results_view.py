from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any


SCOPE_LABELS = {
    "individual": "Отдельный атрибут",
    "joint_tuple": "Совместные комбинации",
    "conditional_on_other_sensitive_attributes": "С учётом других конфиденциальных полей",
}


class LDiversityResultsWindow(tk.Toplevel):
    def __init__(self, parent: tk.Misc, report: dict[str, Any]):
        super().__init__(parent)
        self.title("Диагностика l-разнообразия")
        self.geometry("1120x590")
        self.minsize(820, 420)
        self.transient(parent)
        self.configure(background="#F4F5F7")

        status = report.get("status", "unknown")
        if status == "satisfied":
            status_text = "Проверка l-разнообразия пройдена"
            status_color = "#18794E"
        elif status == "not_evaluable":
            status_text = "Проверку l-разнообразия невозможно выполнить"
            status_color = "#9A6700"
        else:
            status_text = "Проверка l-разнообразия не пройдена"
            status_color = "#B42318"

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

        summary_parts = []
        if report.get("l") is not None:
            summary_parts.append(f"l = {report['l']}")
        if report.get("variant"):
            summary_parts.append(f"критерий: {report['variant']}")
        summary_parts.append(f"проверок: {report.get('check_count', 0)}")
        summary_parts.append(f"нарушений: {report.get('failed_check_count', 0)}")
        ttk.Label(
            content,
            text="  |  ".join(summary_parts),
            foreground="#475467",
        ).grid(row=1, column=0, sticky="w", pady=(4, 8))

        table_frame = ttk.Frame(content)
        table_frame.grid(row=2, column=0, sticky="nsew")
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)

        columns = (
            "profile", "scope", "attribute", "context", "class", "rows",
            "distinct", "entropy", "required", "status",
        )
        self.table = ttk.Treeview(
            table_frame,
            columns=columns,
            show="headings",
            height=14,
        )
        headings = {
            "profile": ("QI-профиль", 150),
            "scope": ("Вид проверки", 190),
            "attribute": ("Конфиденциальный атрибут", 170),
            "context": ("Дополнительный контекст", 150),
            "class": ("Класс", 55),
            "rows": ("Строк", 60),
            "distinct": ("Разных значений / l", 110),
            "entropy": ("H, нат", 85),
            "required": ("Порог H, нат", 95),
            "status": ("Результат", 95),
        }
        for column, (label, width) in headings.items():
            self.table.heading(column, text=label)
            self.table.column(column, width=width, minwidth=55, anchor="w")
        self.table.tag_configure("passed", foreground="#18794E")
        self.table.tag_configure("failed", foreground="#B42318")
        vertical = ttk.Scrollbar(table_frame, orient="vertical", command=self.table.yview)
        horizontal = ttk.Scrollbar(table_frame, orient="horizontal", command=self.table.xview)
        self.table.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.table.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")

        checks = report.get("checks", [])
        for check in checks:
            targets = ", ".join(check.get("target_attributes", [])) or "—"
            context = ", ".join(check.get("context_attributes", [])) or "—"
            entropy = self._format_number(check.get("entropy_nats"))
            required = self._format_number(check.get("required_entropy_nats"))
            result_text = "Пройдена" if check.get("satisfied") else "Нарушена"
            self.table.insert(
                "",
                "end",
                values=(
                    check.get("profile_name", "—"),
                    SCOPE_LABELS.get(check.get("scope"), check.get("scope", "—")),
                    targets,
                    context,
                    check.get("class_number", "—"),
                    check.get("row_count", "—"),
                    f"{check.get('distinct_value_count', '—')} / {check.get('l', '—')}",
                    entropy,
                    required,
                    result_text,
                ),
                tags=("passed" if check.get("satisfied") else "failed",),
            )

        notes = []
        reason = report.get("reason")
        if reason:
            notes.append(reason)
        for warning in report.get("warnings", []):
            if warning not in notes:
                notes.append(warning)
        for note in report.get("notes", []):
            if note not in notes:
                notes.append(note)
        if not checks and not notes:
            notes.append("Подробные данные проверки отсутствуют в отчёте.")

        note_frame = ttk.Frame(content)
        note_frame.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        note_frame.columnconfigure(0, weight=1)
        ttk.Label(
            note_frame,
            text="\n".join(notes),
            foreground="#667085",
            wraplength=1040,
            justify="left",
        ).grid(row=0, column=0, sticky="w")
        ttk.Button(note_frame, text="Закрыть", command=self.destroy).grid(
            row=1, column=0, sticky="e", pady=(8, 0)
        )

    @staticmethod
    def _format_number(value: Any) -> str:
        if value is None:
            return "—"
        try:
            return f"{float(value):.6f}"
        except (TypeError, ValueError):
            return str(value)
