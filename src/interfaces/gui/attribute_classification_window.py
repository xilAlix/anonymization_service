from collections.abc import Callable
import tkinter as tk
from tkinter import messagebox, ttk

import pandas as pd

from data_processing.attribute_classifier import (
    ROLE_LABELS,
    AttributeClassificationResult,
    RoleSuggestion,
    classify_attributes,
    role_labels,
)


APP_BACKGROUND = "#F4F5F7"


class AttributeRoleEditor(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Misc,
        attribute: str,
        current_roles: tuple[str, ...],
        suggestions: tuple[RoleSuggestion, ...],
        on_save: Callable[[list[str]], bool],
        on_reset: Callable[[], bool],
    ):
        super().__init__(parent)
        self.title(f"Роли атрибута: {attribute}")
        self.geometry("510x390")
        self.minsize(450, 340)
        self.transient(parent)
        self.configure(background=APP_BACKGROUND)

        self._on_save = on_save
        self._on_reset = on_reset
        self._role_vars = {
            role: tk.BooleanVar(value=role in current_roles)
            for role in ROLE_LABELS
        }

        style = ttk.Style(self)
        style.configure("RoleEditor.TFrame", background=APP_BACKGROUND)
        style.configure(
            "RoleEditor.TLabel",
            background=APP_BACKGROUND,
            foreground="#202938",
        )
        style.configure(
            "RoleEditor.TCheckbutton",
            background=APP_BACKGROUND,
            foreground="#202938",
        )

        content = ttk.Frame(self, padding=16, style="RoleEditor.TFrame")
        content.pack(fill="both", expand=True)
        content.columnconfigure(0, weight=1)

        ttk.Label(
            content,
            text="Назначенные роли могут сочетаться.",
            style="RoleEditor.TLabel",
            font=("Segoe UI", 10, "bold"),
        ).grid(row=0, column=0, sticky="w", pady=(0, 12))

        for index, (role, label) in enumerate(ROLE_LABELS.items(), start=1):
            ttk.Checkbutton(
                content,
                text=label,
                variable=self._role_vars[role],
                style="RoleEditor.TCheckbutton",
            ).grid(row=index, column=0, sticky="w", pady=3)

        reasons = self._format_suggestions(suggestions)
        ttk.Label(
            content,
            text=reasons,
            style="RoleEditor.TLabel",
            wraplength=460,
            justify="left",
        ).grid(row=5, column=0, sticky="w", pady=(16, 8))

        ttk.Label(
            content,
            text=(
                "Аналитическая роль зависит от конкретной задачи и автоматически "
                "не назначается. Автоматические предложения являются эвристикой, "
                "а не гарантированной классификацией."
            ),
            style="RoleEditor.TLabel",
            wraplength=460,
            justify="left",
        ).grid(row=6, column=0, sticky="w", pady=(4, 0))

        buttons = ttk.Frame(content, style="RoleEditor.TFrame")
        buttons.grid(row=7, column=0, sticky="ew", pady=(18, 0))
        ttk.Button(buttons, text="Сбросить к автоматическим", command=self._reset).pack(
            side="left"
        )
        ttk.Button(buttons, text="Отмена", command=self.destroy).pack(
            side="right", padx=(8, 0)
        )
        ttk.Button(buttons, text="Сохранить", command=self._save).pack(side="right")
        self.grab_set()

    @staticmethod
    def _format_suggestions(suggestions: tuple[RoleSuggestion, ...]) -> str:
        if not suggestions:
            return "Автоматических предложений нет. Роли можно назначить вручную."
        lines = ["Автоматические основания:"]
        for suggestion in suggestions:
            lines.append(
                f"• {ROLE_LABELS[suggestion.role]} — эвристическая уверенность: {suggestion.confidence}"
            )
            lines.extend(f"  {reason}" for reason in suggestion.reasons)
        return "\n".join(lines)

    def _save(self) -> None:
        roles = [role for role, variable in self._role_vars.items() if variable.get()]
        if self._on_save(roles):
            self.destroy()

    def _reset(self) -> None:
        if messagebox.askyesno(
            "Сброс назначения",
            "Удалить ручное назначение и вернуться к автоматическим предложениям?",
            parent=self,
        ):
            if self._on_reset():
                self.destroy()


class AttributeClassificationWindow(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Misc,
        dataframe: pd.DataFrame,
        manual_overrides: dict[str, list[str]],
        save_overrides: Callable[[dict[str, list[str]]], bool],
    ):
        super().__init__(parent)
        self.title("Классификация атрибутов")
        self.geometry("1120x600")
        self.minsize(850, 430)
        self.transient(parent)
        self.configure(background=APP_BACKGROUND)

        self.dataframe = dataframe
        self.manual_overrides = {
            attribute: list(roles) for attribute, roles in manual_overrides.items()
        }
        self._save_overrides = save_overrides
        self.results = classify_attributes(dataframe, self.manual_overrides)
        self._result_by_id: dict[str, AttributeClassificationResult] = {}

        style = ttk.Style(self)
        style.configure("Classification.TFrame", background=APP_BACKGROUND)
        style.configure(
            "Classification.TLabel",
            background=APP_BACKGROUND,
            foreground="#202938",
        )
        style.configure(
            "Classification.Treeview",
            rowheight=28,
            background="#FFFFFF",
            fieldbackground="#FFFFFF",
            foreground="#202938",
        )
        style.configure(
            "Classification.Treeview.Heading",
            background="#DCE6F1",
            foreground="#64748B",
            font=("Segoe UI", 10, "bold"),
            padding=(8, 7),
            relief="flat",
        )

        content = ttk.Frame(self, padding=14, style="Classification.TFrame")
        content.pack(fill="both", expand=True)
        content.columnconfigure(0, weight=1)
        content.rowconfigure(1, weight=1)

        ttk.Label(
            content,
            text=(
                "Автоматические предложения предварительные. Роли могут сочетаться; "
                "аналитическая роль зависит от задачи и назначается вручную."
            ),
            style="Classification.TLabel",
            wraplength=1050,
        ).grid(row=0, column=0, sticky="w", pady=(0, 10))

        table_frame = ttk.Frame(content, style="Classification.TFrame")
        table_frame.grid(row=1, column=0, sticky="nsew")
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)

        columns = ("attribute", "dtype", "suggested", "assigned", "source")
        self.table = ttk.Treeview(
            table_frame,
            columns=columns,
            show="headings",
            style="Classification.Treeview",
        )
        headings = {
            "attribute": ("Атрибут", 190),
            "dtype": ("Тип Pandas", 115),
            "suggested": ("Автоматическое предложение", 260),
            "assigned": ("Применяемые роли", 330),
            "source": ("Источник", 120),
        }
        for column, (heading, width) in headings.items():
            self.table.heading(column, text=heading)
            self.table.column(column, width=width, minwidth=85, anchor="w")
        self.table.tag_configure("row_even", background="#FFFFFF")
        self.table.tag_configure("row_odd", background="#F1F5F9")

        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.table.yview)
        self.table.configure(yscrollcommand=scrollbar.set)
        self.table.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.table.bind("<<TreeviewSelect>>", self._selection_changed)
        self.table.bind("<Double-1>", self._edit_selected)

        self.details = tk.StringVar(value="Выбери атрибут, чтобы увидеть основания классификации.")
        ttk.Label(
            content,
            textvariable=self.details,
            style="Classification.TLabel",
            wraplength=1050,
            justify="left",
        ).grid(row=2, column=0, sticky="ew", pady=(10, 8))

        actions = ttk.Frame(content, style="Classification.TFrame")
        actions.grid(row=3, column=0, sticky="ew")
        self.edit_button = ttk.Button(
            actions,
            text="Изменить роли выбранного атрибута",
            command=self._edit_selected,
            state="disabled",
        )
        self.edit_button.pack(side="left")
        ttk.Button(actions, text="Закрыть", command=self.destroy).pack(side="right")

        self._render_rows()

    def _render_rows(self) -> None:
        self.table.delete(*self.table.get_children())
        self._result_by_id.clear()

        for index, result in enumerate(self.results):
            item_id = str(index)
            suggested = (
                role_labels(item.role for item in result.suggestions)
                if result.suggestions
                else "Нет предложения"
            )
            tag = "row_even" if index % 2 == 0 else "row_odd"
            self.table.insert(
                "",
                "end",
                iid=item_id,
                values=(
                    result.attribute,
                    result.pandas_type,
                    suggested,
                    role_labels(result.assigned_roles),
                    result.assignment_source,
                ),
                tags=(tag,),
            )
            self._result_by_id[item_id] = result

    def _selection_changed(self, _event=None) -> None:
        selected = self.table.selection()
        self.edit_button.configure(state="normal" if selected else "disabled")
        if not selected:
            return
        result = self._result_by_id[selected[0]]
        if result.suggestions:
            reasons = [
                f"{ROLE_LABELS[item.role]} ({item.confidence}): " + " ".join(item.reasons)
                for item in result.suggestions
            ]
            self.details.set("\n".join(reasons))
        else:
            self.details.set(
                "Автоматические предложения отсутствуют. Это не означает, "
                "что атрибут безопасен или неважен для аналитики."
            )

    def _edit_selected(self, _event=None) -> None:
        selected = self.table.selection()
        if not selected:
            return
        result = self._result_by_id[selected[0]]

        def save_roles(roles: list[str]) -> bool:
            previous = self.manual_overrides.get(result.attribute)
            self.manual_overrides[result.attribute] = roles
            if self._persist_and_refresh():
                return True
            if previous is None:
                self.manual_overrides.pop(result.attribute, None)
            else:
                self.manual_overrides[result.attribute] = previous
            return False

        def reset_roles() -> bool:
            previous = self.manual_overrides.pop(result.attribute, None)
            if self._persist_and_refresh():
                return True
            if previous is not None:
                self.manual_overrides[result.attribute] = previous
            return False

        AttributeRoleEditor(
            self,
            result.attribute,
            result.assigned_roles,
            result.suggestions,
            save_roles,
            reset_roles,
        )

    def _persist_and_refresh(self) -> bool:
        if not self._save_overrides(self.manual_overrides):
            return False
        self.results = classify_attributes(self.dataframe, self.manual_overrides)
        self._render_rows()
        self.details.set("Назначения сохранены. Выбери атрибут, чтобы посмотреть основания.")
        return True
