import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
from collections.abc import Callable

from infrastructure.attribute_profile_store import new_manual_quasi_identifier_group
from interfaces.gui.tooltip import ToolTip


APP_BACKGROUND = "#F4F5F7"


class QuasiIdentifierGroupsWindow(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Misc,
        columns: list[str],
        groups: list[dict],
        on_save: Callable[[list[dict]], bool],
        on_refresh_automatic: Callable[[], list[dict]],
    ):
        super().__init__(parent)
        self.title("Группы квази-идентификаторов")
        self.geometry("900x590")
        self.minsize(780, 500)
        self.transient(parent)
        self.configure(background=APP_BACKGROUND)

        self.columns = list(columns)
        self.groups = [dict(group) for group in groups]
        self._on_save = on_save
        self._on_refresh_automatic = on_refresh_automatic
        self._selected_group_id: str | None = None

        style = ttk.Style(self)
        style.configure("QIGroup.TFrame", background=APP_BACKGROUND)
        style.configure("QIGroup.TLabel", background=APP_BACKGROUND, foreground="#202938")

        content = ttk.Frame(self, padding=14, style="QIGroup.TFrame")
        content.pack(fill="both", expand=True)
        content.columnconfigure(0, weight=1)
        content.columnconfigure(1, weight=2)
        content.rowconfigure(1, weight=1)

        heading = ttk.Label(
            content,
            text="Профили возможной фоновой информации",
            style="QIGroup.TLabel",
            font=("Segoe UI", 12, "bold"),
        )
        heading.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))
        ToolTip(
            heading,
            "Каждая группа представляет отдельную гипотезу о наборе сведений, "
            "которыми может располагать внешний источник. Один атрибут может "
            "входить в несколько групп. Автоматические группы нужно проверять вручную.",
        )

        groups_frame = ttk.LabelFrame(content, text="Группы", padding=8)
        groups_frame.grid(row=1, column=0, sticky="nsew", padx=(0, 8))
        groups_frame.columnconfigure(0, weight=1)
        groups_frame.rowconfigure(0, weight=1)

        self.group_list = tk.Listbox(
            groups_frame,
            exportselection=False,
            activestyle="none",
            selectmode="browse",
            font=("Segoe UI", 10),
        )
        group_scroll = ttk.Scrollbar(groups_frame, orient="vertical", command=self.group_list.yview)
        self.group_list.configure(yscrollcommand=group_scroll.set)
        self.group_list.grid(row=0, column=0, sticky="nsew")
        group_scroll.grid(row=0, column=1, sticky="ns")
        self.group_list.bind("<<ListboxSelect>>", self._group_selected)

        group_actions = ttk.Frame(groups_frame)
        group_actions.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        create_button = ttk.Button(group_actions, text="Создать", command=self._create_group)
        create_button.pack(side="left")
        ToolTip(create_button, "Создать пользовательский набор квази-идентификаторов.")
        rename_button = ttk.Button(group_actions, text="Переименовать", command=self._rename_group)
        rename_button.pack(side="left", padx=5)
        ToolTip(rename_button, "Изменить название выбранной группы.")
        delete_button = ttk.Button(group_actions, text="Удалить", command=self._delete_group)
        delete_button.pack(side="left")
        ToolTip(delete_button, "Удалить выбранную группу из профиля набора данных.")

        attributes_frame = ttk.LabelFrame(content, text="Атрибуты выбранной группы", padding=8)
        attributes_frame.grid(row=1, column=1, sticky="nsew")
        attributes_frame.columnconfigure(0, weight=1)
        attributes_frame.rowconfigure(0, weight=1)
        self.attribute_list = tk.Listbox(
            attributes_frame,
            selectmode="extended",
            exportselection=False,
            activestyle="none",
            font=("Segoe UI", 10),
        )
        attribute_scroll = ttk.Scrollbar(
            attributes_frame,
            orient="vertical",
            command=self.attribute_list.yview,
        )
        self.attribute_list.configure(yscrollcommand=attribute_scroll.set)
        self.attribute_list.grid(row=0, column=0, sticky="nsew")
        attribute_scroll.grid(row=0, column=1, sticky="ns")
        for column in self.columns:
            self.attribute_list.insert("end", column)
        ToolTip(
            self.attribute_list,
            "Выбери столбцы, которые предполагаемый внешний источник может содержать. "
            "Состав группы можно менять независимо от других групп.",
        )

        attribute_action = ttk.Frame(attributes_frame)
        attribute_action.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        apply_button = ttk.Button(
            attribute_action,
            text="Применить выбор к группе",
            command=self._apply_selected_attributes,
        )
        apply_button.pack(side="left")
        ToolTip(apply_button, "Сохранить текущий набор выбранных столбцов в выбранной группе.")
        refresh_button = ttk.Button(
            attribute_action,
            text="Обновить автопредложения",
            command=self._refresh_automatic,
        )
        refresh_button.pack(side="right")
        ToolTip(
            refresh_button,
            "Повторно сформировать автоматические группы. Пользовательские группы и изменения сохраняются.",
        )

        self.group_details = tk.StringVar(value="Выбери группу, чтобы просмотреть её состав.")
        details = ttk.Label(
            content,
            textvariable=self.group_details,
            style="QIGroup.TLabel",
            wraplength=850,
            justify="left",
        )
        details.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        self.details_tooltip = ToolTip(
            details,
            "Уровень уверенности показывает силу эвристических признаков, "
            "а не вероятность реальной повторной идентификации.",
        )

        actions = ttk.Frame(content, style="QIGroup.TFrame")
        actions.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        save_button = ttk.Button(actions, text="Сохранить", command=self._save)
        save_button.pack(side="right")
        ToolTip(save_button, "Сохранить все созданные и изменённые группы в профиль CSV.")
        ttk.Button(actions, text="Закрыть", command=self.destroy).pack(side="right", padx=(0, 8))

        self._render_groups()
        if self.groups:
            self.group_list.selection_set(0)
            self._group_selected()

    def _render_groups(self) -> None:
        self.group_list.delete(0, "end")
        for group in self.groups:
            source_label = "авто" if group.get("source") == "automatic" else "вручную"
            self.group_list.insert(
                "end",
                f"{group['name']} [{len(group.get('attributes', []))}] · {source_label}",
            )

    def _current_group(self) -> dict | None:
        selection = self.group_list.curselection()
        if not selection:
            return None
        index = selection[0]
        if index >= len(self.groups):
            return None
        return self.groups[index]

    def _group_selected(self, _event=None) -> None:
        group = self._current_group()
        self.attribute_list.selection_clear(0, "end")
        if group is None:
            self._selected_group_id = None
            self.group_details.set("Группа не выбрана.")
            self.details_tooltip.set_text("Выбери группу, чтобы посмотреть её состав и основания автоматического предложения.")
            return

        self._selected_group_id = group["id"]
        selected = set(group.get("attributes", []))
        for index, column in enumerate(self.columns):
            if column in selected:
                self.attribute_list.selection_set(index)

        source = "Автоматически предложена" if group.get("source") == "automatic" else "Создана или изменена вручную"
        confidence = group.get("confidence", "не указана")
        self.group_details.set(f"{source}. Уверенность: {confidence}.")
        tooltip_parts = [group.get("description", "")]
        sources = group.get("external_source_families", [])
        if sources:
            tooltip_parts.append("Возможные внешние источники: " + ", ".join(sources) + ".")
        reasons = group.get("reasons", [])
        if reasons:
            tooltip_parts.append("Основания: " + " ".join(reasons))
        self.details_tooltip.set_text("\n\n".join(part for part in tooltip_parts if part))

    def _create_group(self) -> None:
        name = simpledialog.askstring(
            "Новая группа",
            "Название группы квази-идентификаторов:",
            parent=self,
        )
        if name is None:
            return
        if not name.strip():
            messagebox.showwarning("Пустое название", "Укажи название группы.", parent=self)
            return
        if any(group["name"].casefold() == name.strip().casefold() for group in self.groups):
            messagebox.showwarning("Группа существует", "Такое название уже используется.", parent=self)
            return

        self.groups.append(new_manual_quasi_identifier_group(name, []))
        self._render_groups()
        self.group_list.selection_clear(0, "end")
        self.group_list.selection_set(len(self.groups) - 1)
        self._group_selected()

    def _rename_group(self) -> None:
        group = self._current_group()
        if group is None:
            return
        name = simpledialog.askstring(
            "Переименовать группу",
            "Новое название группы:",
            initialvalue=group["name"],
            parent=self,
        )
        if name is None:
            return
        normalized = name.strip().casefold()
        if not normalized:
            messagebox.showwarning("Пустое название", "Укажи название группы.", parent=self)
            return
        if any(
            other["id"] != group["id"] and other["name"].casefold() == normalized
            for other in self.groups
        ):
            messagebox.showwarning("Группа существует", "Такое название уже используется.", parent=self)
            return
        group["name"] = name.strip()
        group["source"] = "manual"
        group["confidence"] = "ручная"
        self._render_groups()
        index = self.groups.index(group)
        self.group_list.selection_set(index)
        self._group_selected()

    def _delete_group(self) -> None:
        group = self._current_group()
        if group is None:
            return
        if not messagebox.askyesno(
            "Удаление группы",
            f"Удалить группу «{group['name']}»?",
            parent=self,
        ):
            return
        index = self.group_list.curselection()[0]
        self.groups.remove(group)
        self._render_groups()
        if self.groups:
            index = min(index, len(self.groups) - 1)
            self.group_list.selection_set(index)
        self._group_selected()

    def _apply_selected_attributes(self) -> None:
        group = self._current_group()
        if group is None:
            messagebox.showinfo("Группа не выбрана", "Сначала выбери группу.", parent=self)
            return
        selected_indices = self.attribute_list.curselection()
        group["attributes"] = [self.columns[index] for index in selected_indices]
        group["source"] = "manual"
        group["confidence"] = "ручная"
        group["reasons"] = ["Состав группы подтверждён пользователем."]
        self._render_groups()
        self.group_list.selection_set(self.groups.index(group))
        self._group_selected()
        self.group_details.set(
            f"Состав группы «{group['name']}» обновлён. Не забудь сохранить изменения."
        )

    def _refresh_automatic(self) -> None:
        try:
            suggested = self._on_refresh_automatic()
        except (OSError, ValueError) as error:
            messagebox.showerror("Ошибка анализа QI", str(error), parent=self)
            return
        manual_groups = [group for group in self.groups if group.get("source") != "automatic"]
        manual_ids = {group["id"] for group in manual_groups}
        self.groups = manual_groups + [
            group for group in suggested if group["id"] not in manual_ids
        ]
        self._render_groups()
        if self.groups:
            self.group_list.selection_set(0)
        self._group_selected()
        self.group_details.set(
            "Автоматические предложения обновлены. Пользовательские группы сохранены."
        )

    def _save(self) -> None:
        try:
            if self._on_save(self.groups):
                messagebox.showinfo("Группы сохранены", "Группы квази-идентификаторов сохранены.", parent=self)
                self.destroy()
        except (OSError, ValueError) as error:
            messagebox.showerror("Ошибка сохранения", str(error), parent=self)
