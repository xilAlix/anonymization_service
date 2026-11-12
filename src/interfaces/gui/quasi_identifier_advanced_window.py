import json
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
from uuid import uuid4

from infrastructure.attribute_profile_store import (
    load_quasi_identifier_correlation_blocks,
    load_quasi_identifier_hierarchies,
    save_quasi_identifier_correlation_blocks,
    save_quasi_identifier_hierarchy,
    delete_quasi_identifier_hierarchy,
)
from interfaces.gui.tooltip import ToolTip


class QuasiIdentifierAdvancedWindow(tk.Toplevel):
    def __init__(self, parent: tk.Misc, csv_path, columns: list[str]):
        super().__init__(parent)
        self.parent = parent
        self.csv_path = csv_path
        self.columns = list(columns)
        self.title("Иерархии и аналитические связи QI")
        self.geometry("820x600")
        self.minsize(720, 500)
        self.transient(parent)

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=12, pady=12)

        hierarchy_tab = ttk.Frame(notebook, padding=12)
        hierarchy_tab.columnconfigure(0, weight=1)
        hierarchy_tab.rowconfigure(2, weight=1)
        notebook.add(hierarchy_tab, text="Иерархии категорий")

        ttk.Label(hierarchy_tab, text="Столбец:").grid(row=0, column=0, sticky="w")
        self.column_var = tk.StringVar(value=self.columns[0] if self.columns else "")
        self.column_select = ttk.Combobox(
            hierarchy_tab,
            state="readonly",
            values=self.columns,
            textvariable=self.column_var,
        )
        self.column_select.grid(row=1, column=0, sticky="ew", pady=(4, 10))
        self.column_select.bind("<<ComboboxSelected>>", self._load_hierarchy)
        ToolTip(self.column_select, "Выбери категориальный QI, для которого задаётся обобщение к общим категориям.")

        self.hierarchy_text = tk.Text(hierarchy_tab, wrap="none", height=18, font=("Consolas", 10))
        self.hierarchy_text.grid(row=2, column=0, sticky="nsew")
        hierarchy_scroll = ttk.Scrollbar(hierarchy_tab, orient="vertical", command=self.hierarchy_text.yview)
        hierarchy_scroll.grid(row=2, column=1, sticky="ns")
        self.hierarchy_text.configure(yscrollcommand=hierarchy_scroll.set)
        hierarchy_buttons = ttk.Frame(hierarchy_tab)
        hierarchy_buttons.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        ttk.Button(hierarchy_buttons, text="Сохранить иерархию", command=self._save_hierarchy).pack(side="left")
        ttk.Button(hierarchy_buttons, text="Удалить иерархию", command=self._delete_hierarchy).pack(side="left", padx=(8, 0))
        ToolTip(self.hierarchy_text, "JSON-массив уровней. Каждый следующий уровень переводит дочерние категории в более общий класс.")

        correlation_tab = ttk.Frame(notebook, padding=12)
        correlation_tab.columnconfigure(0, weight=1)
        correlation_tab.columnconfigure(1, weight=2)
        correlation_tab.rowconfigure(1, weight=1)
        notebook.add(correlation_tab, text="Связанные признаки")

        ttk.Label(correlation_tab, text="Сохранённые блоки").grid(row=0, column=0, sticky="w")
        ttk.Label(correlation_tab, text="Столбцы нового блока").grid(row=0, column=1, sticky="w")
        self.block_list = tk.Listbox(correlation_tab, exportselection=False)
        self.block_list.grid(row=1, column=0, sticky="nsew", padx=(0, 10), pady=(5, 0))
        self.block_list.bind("<<ListboxSelect>>", self._block_selected)
        self.attribute_list = tk.Listbox(correlation_tab, selectmode="extended", exportselection=False)
        self.attribute_list.grid(row=1, column=1, sticky="nsew", pady=(5, 0))
        for column in self.columns:
            self.attribute_list.insert("end", column)
        block_buttons = ttk.Frame(correlation_tab)
        block_buttons.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        ttk.Button(block_buttons, text="Создать блок из выбранных", command=self._add_correlation_block).pack(side="left")
        ttk.Button(block_buttons, text="Удалить выбранный блок", command=self._delete_correlation_block).pack(side="left", padx=(8, 0))
        ToolTip(self.attribute_list, "Выбери два или более связанных признака. Их профили будут кластеризоваться совместно.")

        self.hierarchies = {}
        self.blocks = []
        self._load_all()

    def _load_all(self) -> None:
        try:
            self.hierarchies = load_quasi_identifier_hierarchies(self.csv_path)
            self.blocks = load_quasi_identifier_correlation_blocks(self.csv_path)
        except (OSError, ValueError) as error:
            messagebox.showerror("Ошибка профиля", str(error), parent=self)
            self.destroy()
            return
        if self.columns:
            self._load_hierarchy()
        self._render_blocks()

    def _load_hierarchy(self, _event=None) -> None:
        column = self.column_var.get()
        levels = self.hierarchies.get(column, [])
        self.hierarchy_text.delete("1.0", "end")
        self.hierarchy_text.insert(
            "1.0",
            json.dumps(levels, ensure_ascii=False, indent=2) if levels else "[\n  {}\n]",
        )

    def _save_hierarchy(self) -> None:
        column = self.column_var.get()
        try:
            levels = json.loads(self.hierarchy_text.get("1.0", "end-1c"))
            save_quasi_identifier_hierarchy(
                self.csv_path,
                column,
                levels,
                self.columns,
            )
            self.hierarchies[column] = levels
        except (OSError, ValueError, json.JSONDecodeError) as error:
            messagebox.showerror("Некорректная иерархия", str(error), parent=self)
            return
        messagebox.showinfo("Иерархия сохранена", f"Иерархия для «{column}» сохранена.", parent=self)

    def _delete_hierarchy(self) -> None:
        column = self.column_var.get()
        if column not in self.hierarchies:
            messagebox.showinfo("Нет иерархии", "Для выбранного столбца иерархия не задана.", parent=self)
            return
        if not messagebox.askyesno("Удаление иерархии", f"Удалить иерархию для «{column}»?", parent=self):
            return
        try:
            delete_quasi_identifier_hierarchy(self.csv_path, column)
        except (OSError, ValueError) as error:
            messagebox.showerror("Ошибка удаления", str(error), parent=self)
            return
        self.hierarchies.pop(column, None)
        self._load_hierarchy()

    def _render_blocks(self) -> None:
        self.block_list.delete(0, "end")
        for block in self.blocks:
            self.block_list.insert("end", f"{block['name']} [{len(block['attributes'])}]")

    def _block_selected(self, _event=None) -> None:
        selection = self.block_list.curselection()
        if not selection:
            return
        block = self.blocks[selection[0]]
        selected = set(block["attributes"])
        self.attribute_list.selection_clear(0, "end")
        for index, column in enumerate(self.columns):
            if column in selected:
                self.attribute_list.selection_set(index)

    def _add_correlation_block(self) -> None:
        indices = self.attribute_list.curselection()
        if len(indices) < 2:
            messagebox.showwarning("Недостаточно признаков", "Выбери минимум два столбца.", parent=self)
            return
        name = simpledialog.askstring("Новый блок", "Название блока связанных признаков:", parent=self)
        if not name or not name.strip():
            return
        block = {
            "id": uuid4().hex[:10],
            "name": name.strip(),
            "attributes": [self.columns[index] for index in indices],
        }
        updated = [*self.blocks, block]
        try:
            save_quasi_identifier_correlation_blocks(self.csv_path, updated, self.columns)
        except (OSError, ValueError) as error:
            messagebox.showerror("Ошибка сохранения", str(error), parent=self)
            return
        self.blocks = updated
        self._render_blocks()

    def _delete_correlation_block(self) -> None:
        selection = self.block_list.curselection()
        if not selection:
            return
        self.blocks.pop(selection[0])
        try:
            save_quasi_identifier_correlation_blocks(self.csv_path, self.blocks, self.columns)
        except (OSError, ValueError) as error:
            messagebox.showerror("Ошибка сохранения", str(error), parent=self)
            return
        self._render_blocks()
