from pathlib import Path
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

import pandas as pd

from application.k_anonymization_workflow import (
    LDiversityViolationError,
    execute_k_anonymization,
    save_k_anonymity_report,
)
from application.anonymization_workflow import (
    K_ANONYMITY,
    REMOVE_DIRECT_IDENTIFIERS,
    TOKENIZE_DIRECT_IDENTIFIERS,
    apply_anonymization_operations,
)
from data_processing.csv_handler import load_csv, save_csv
from data_processing.quasi_identifier_analyzer import suggest_quasi_identifier_groups
from infrastructure.attribute_profile_store import (
    load_manual_role_overrides,
    save_manual_role_overrides,
    load_quasi_identifier_groups,
    save_quasi_identifier_groups,
)
from data_processing.schema_inspector import analyze_column_types
from infrastructure.settings_manager import AppSettings, load_settings
from interfaces.gui.attribute_classification_window import AttributeClassificationWindow
from interfaces.gui.column_types_window import ColumnTypesWindow
from interfaces.gui.settings_window import SettingsWindow
from interfaces.gui.tooltip import ToolTip
from interfaces.gui.quasi_identifier_groups_window import QuasiIdentifierGroupsWindow


APP_BACKGROUND = "#F4F5F7"


def enable_windows_dpi_awareness() -> None:
    if sys.platform != "win32":
        return

    import ctypes

    try:
        configured = ctypes.windll.user32.SetProcessDpiAwarenessContext(
            ctypes.c_void_p(-4)
        )
        if configured:
            return
    except (AttributeError, OSError):
        pass

    try:
        result = ctypes.windll.shcore.SetProcessDpiAwareness(2)
        if result == 0:
            return
    except (AttributeError, OSError):
        pass

    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except (AttributeError, OSError):
        pass


class TableViewer(tk.Tk):
    def __init__(self, example_path: Path):
        super().__init__()
        self.example_path = example_path
        self.current_dataframe: pd.DataFrame | None = None
        self.current_file_path: Path | None = None
        self.preview_limit = 500
        self.settings = load_settings()
        self.settings_window: SettingsWindow | None = None
        self.column_types_window: ColumnTypesWindow | None = None
        self.attribute_classification_window: AttributeClassificationWindow | None = None
        self.quasi_identifier_groups_window: QuasiIdentifierGroupsWindow | None = None

        self.title("Сервис анонимизации")
        self.geometry("1120x700")
        self.minsize(780, 480)
        self.configure(background=APP_BACKGROUND)
        self._build_menu()
        self._build_widgets()
        self.open_example()

    def _build_menu(self) -> None:
        menu_bar = tk.Menu(self)
        menu_bar.add_command(label="Настройки", command=self.open_settings)

        operations_menu = tk.Menu(menu_bar, tearoff=False)
        operations_menu.add_command(label="Открыть CSV-файл...", command=self.open_csv)
        operations_menu.add_command(
            label="Загрузить пример",
            command=self.open_example,
        )
        operations_menu.add_separator()
        operations_menu.add_command(
            label="Определить типы данных",
            command=self.show_column_types,
            state="disabled",
        )
        self.operations_menu = operations_menu
        self.types_menu_index = 3
        operations_menu.add_command(
            label="Классифицировать атрибуты",
            command=self.show_attribute_classification,
            state="disabled",
        )
        self.classification_menu_index = 4
        operations_menu.add_command(
            label="Группы квази-идентификаторов...",
            command=self.show_quasi_identifier_groups,
            state="disabled",
        )
        self.quasi_identifier_groups_menu_index = 5
        operations_menu.add_separator()
        operations_menu.add_command(
            label="Токенизировать прямые идентификаторы...",
            command=self.tokenize_direct_identifiers,
            state="disabled",
        )
        self.tokenization_menu_index = 7
        operations_menu.add_command(
            label="Удалить столбцы с прямыми идентификаторами...",
            command=self.remove_direct_identifiers,
            state="disabled",
        )
        self.removal_menu_index = 8
        operations_menu.add_separator()
        operations_menu.add_command(
            label="Выполнить k-анонимизацию...",
            command=self.run_k_anonymization,
            state="disabled",
        )
        self.k_anonymization_menu_index = 10
        menu_bar.add_cascade(label="Операции", menu=operations_menu)
        self.config(menu=menu_bar)

    def _build_widgets(self) -> None:
        style = ttk.Style(self)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("App.TFrame", background=APP_BACKGROUND)
        style.configure("App.TLabel", background=APP_BACKGROUND, foreground="#202938")
        style.configure(
            "Treeview",
            background="#FFFFFF",
            fieldbackground="#FFFFFF",
            foreground="#202938",
            rowheight=27,
            borderwidth=0,
        )
        style.configure(
            "Treeview.Heading",
            background="#DCE6F1",
            foreground="#64748B",
            font=("Segoe UI", 10, "bold"),
            padding=(8, 7),
            relief="flat",
        )
        style.map("Treeview.Heading", background=[("active", "#C9D8E8")])

        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        content = ttk.Frame(self, padding=(12, 10), style="App.TFrame")
        content.grid(row=0, column=0, sticky="nsew")
        content.columnconfigure(0, weight=1)
        content.rowconfigure(3, weight=1)

        toolbar = ttk.Frame(content, style="App.TFrame")
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.anonymize_button = ttk.Button(
            toolbar,
            text="Анонимизировать",
            command=self.anonymize_selected_operations,
            state="disabled",
        )
        self.anonymize_button.pack(side="right")
        ToolTip(
            self.anonymize_button,
            "Создаёт новый CSV по выбранным операциям. Исходный файл не изменяется.",
        )

        info_frame = ttk.Frame(content, style="App.TFrame")
        info_frame.grid(row=1, column=0, sticky="ew", pady=(0, 4))
        self.table_info = tk.StringVar(value="Таблица не загружена")
        ttk.Label(
            info_frame, textvariable=self.table_info, style="App.TLabel",
            font=("Segoe UI", 10, "bold")
        ).pack(anchor="w")
        self.plan_info = tk.StringVar(value="План запуска: операции не выбраны")
        plan_label = ttk.Label(
            info_frame, textvariable=self.plan_info, style="App.TLabel", foreground="#526174"
        )
        plan_label.pack(anchor="w", pady=(3, 0))
        ToolTip(
            plan_label,
            "CSV — основная таблица для аналитики. JSON — отдельный технический отчёт, он не нужен аналитическим алгоритмам. l-разнообразие только проверяет результат; при провале CSV не создаётся.",
        )

        guide = ttk.Label(
            content,
            text="Работа с таблицей и настройками доступна в меню сверху. После проверки ролей и QI-групп запустите выбранные операции кнопкой «Анонимизировать».",
            style="App.TLabel",
            foreground="#667085",
            wraplength=1050,
        )
        guide.grid(row=2, column=0, sticky="ew", pady=(2, 8))

        table_frame = ttk.Frame(content, style="App.TFrame")
        table_frame.grid(row=3, column=0, sticky="nsew")
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)

        self.table = ttk.Treeview(table_frame, show="headings")
        self.table.tag_configure("row_even", background="#FFFFFF")
        self.table.tag_configure("row_odd", background="#F1F5F9")
        vertical_scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.table.yview)
        horizontal_scroll = ttk.Scrollbar(
            table_frame,
            orient="horizontal",
            command=self.table.xview,
        )
        self.table.configure(
            yscrollcommand=vertical_scroll.set,
            xscrollcommand=horizontal_scroll.set,
        )
        self.table.grid(row=0, column=0, sticky="nsew")
        vertical_scroll.grid(row=0, column=1, sticky="ns")
        horizontal_scroll.grid(row=1, column=0, sticky="ew")

        self.status = tk.StringVar(
            value="Откройте CSV-файл или загрузите пример."
        )
        ttk.Label(
            self,
            textvariable=self.status,
            style="App.TLabel",
            anchor="w",
            padding=(8, 4),
        ).grid(row=1, column=0, sticky="ew")

    def _show_dataframe(self, dataframe: pd.DataFrame, source_path: Path) -> None:
        if (
            self.column_types_window is not None
            and self.column_types_window.winfo_exists()
        ):
            self.column_types_window.destroy()
        if (
            self.attribute_classification_window is not None
            and self.attribute_classification_window.winfo_exists()
        ):
            self.attribute_classification_window.destroy()
        if (
            self.quasi_identifier_groups_window is not None
            and self.quasi_identifier_groups_window.winfo_exists()
        ):
            self.quasi_identifier_groups_window.destroy()

        self.current_dataframe = dataframe
        self.current_file_path = source_path.resolve()
        columns = [str(column) for column in dataframe.columns]
        self.table.delete(*self.table.get_children())
        self.table.configure(columns=columns)

        for column in columns:
            self.table.heading(column, text=column)
            self.table.column(column, width=150, minwidth=90, anchor="w", stretch=True)

        preview_rows = dataframe.head(self.preview_limit).itertuples(
            index=False,
            name=None,
        )
        for row_number, row in enumerate(preview_rows):
            values = ["" if pd.isna(value) else str(value) for value in row]
            row_style = "row_even" if row_number % 2 == 0 else "row_odd"
            self.table.insert("", "end", values=values, tags=(row_style,))

        self.operations_menu.entryconfig(self.types_menu_index, state="normal")
        self.operations_menu.entryconfig(self.classification_menu_index, state="normal")
        self._update_anonymization_controls()
        row_count, column_count = dataframe.shape
        self.table_info.set(
            f"{source_path.name}  |  {row_count} строк × {column_count} столбцов"
        )
        if row_count > self.preview_limit:
            self.status.set(
                f"Показаны первые {self.preview_limit} строк из {row_count}."
            )
        else:
            self.status.set("Таблица успешно загружена.")

    def open_csv(self) -> None:
        selected_file = filedialog.askopenfilename(
            title="Открыть таблицу CSV",
            filetypes=(("CSV-файлы", "*.csv"), ("Все файлы", "*.*")),
        )
        if not selected_file:
            return

        try:
            source_path = Path(selected_file)
            dataframe = load_csv(source_path)
            self._show_dataframe(dataframe, source_path)
        except (OSError, ValueError, pd.errors.ParserError) as error:
            messagebox.showerror("Ошибка открытия файла", str(error))
            self.status.set("Не удалось загрузить выбранный файл.")

    def open_example(self) -> None:
        try:
            dataframe = load_csv(self.example_path)
            self._show_dataframe(dataframe, self.example_path)
        except (OSError, ValueError, pd.errors.ParserError) as error:
            messagebox.showerror("Ошибка открытия примера", str(error))

    def open_settings(self) -> None:
        if self.settings_window is not None and self.settings_window.winfo_exists():
            self.settings_window.lift()
            return
        self.settings_window = SettingsWindow(
            self,
            self.settings,
            self._settings_saved,
        )

    def _settings_saved(self, settings: AppSettings) -> None:
        self.settings = settings
        if (
            self.column_types_window is not None
            and self.column_types_window.winfo_exists()
        ):
            self.column_types_window.destroy()
        self._update_anonymization_controls()
        self.status.set("Настройки анализа и анонимизации сохранены.")

    def show_column_types(self) -> None:
        if self.current_dataframe is None:
            messagebox.showwarning(
                "Нет таблицы",
                "Сначала загрузите CSV-файл.",
            )
            return

        if (
            self.column_types_window is not None
            and self.column_types_window.winfo_exists()
        ):
            self.column_types_window.destroy()

        analysis_settings = self.settings.data_type_analysis
        results = analyze_column_types(
            self.current_dataframe,
            detect_nominal_attributes=analysis_settings.detect_nominal_attributes,
            nominal_unique_threshold_percent=(
                analysis_settings.nominal_unique_threshold_percent
            ),
        )
        self.column_types_window = ColumnTypesWindow(
            self,
            results,
            analysis_settings.detect_nominal_attributes,
        )


    def _update_anonymization_controls(self) -> None:
        table_loaded = (
            self.current_dataframe is not None
            and self.current_file_path is not None
        )
        aggregate_selected = (
            self.settings.anonymization.tokenize_direct_identifiers
            or self.settings.anonymization.remove_direct_identifiers
            or self.settings.anonymization.enable_k_anonymity
        )

        individual_state = "normal" if table_loaded else "disabled"
        self.operations_menu.entryconfig(self.types_menu_index, state=individual_state)
        self.operations_menu.entryconfig(self.classification_menu_index, state=individual_state)
        self.operations_menu.entryconfig(self.tokenization_menu_index, state=individual_state)
        self.operations_menu.entryconfig(self.removal_menu_index, state=individual_state)

        qi_groups_state = "normal" if table_loaded else "disabled"
        self.operations_menu.entryconfig(self.quasi_identifier_groups_menu_index, state=qi_groups_state)

        active_qi_profiles = False
        if table_loaded:
            try:
                active_qi_profiles = any(
                    group.get("active", group.get("source") != "automatic")
                    for group in load_quasi_identifier_groups(self.current_file_path)
                )
            except (OSError, ValueError):
                active_qi_profiles = False
        k_state = "normal" if table_loaded and active_qi_profiles else "disabled"
        self.operations_menu.entryconfig(self.k_anonymization_menu_index, state=k_state)

        aggregate_ready = table_loaded and aggregate_selected
        if self.settings.anonymization.enable_k_anonymity and not active_qi_profiles:
            aggregate_ready = False
        self.anonymize_button.configure(state="normal" if aggregate_ready else "disabled")
        self._update_plan_summary(active_qi_profiles=active_qi_profiles)

    def _update_plan_summary(self, active_qi_profiles: bool | None = None) -> None:
        operations = []
        anonymization = self.settings.anonymization
        k_settings = self.settings.k_anonymization
        if anonymization.tokenize_direct_identifiers:
            operations.append("токенизация идентификаторов")
        if anonymization.remove_direct_identifiers:
            operations.append("удаление идентификаторов")
        if anonymization.enable_k_anonymity:
            operations.append(f"k-анонимизация (k={k_settings.default_k})")

        if active_qi_profiles is None:
            active_qi_profiles = False
            if self.current_file_path is not None:
                try:
                    active_qi_profiles = any(
                        group.get("active", group.get("source") != "automatic")
                        for group in load_quasi_identifier_groups(self.current_file_path)
                    )
                except (OSError, ValueError):
                    active_qi_profiles = False

        if not operations:
            summary = "План запуска: операции не выбраны"
        else:
            summary = "План запуска: " + " + ".join(operations)

        if not k_settings.enable_l_diversity:
            l_summary = "l-проверка: выключена"
        else:
            variant_label = {
                "distinct": "Distinct",
                "entropy": "Entropy",
                "both": "оба критерия",
            }.get(k_settings.l_diversity_variant, k_settings.l_diversity_variant)
            l_summary = f"l-проверка: включена (l={k_settings.default_l}, {variant_label})"
            if anonymization.enable_k_anonymity:
                l_summary += " и войдёт в суммарный запуск"
            else:
                l_summary += (
                    "; в суммарный запуск не входит, поскольку k-анонимизация не выбрана. "
                    "Применится при отдельном запуске k-анонимизации через меню «Операции»"
                )

        details = f"{summary}  |  {l_summary}"
        if anonymization.enable_k_anonymity and not active_qi_profiles:
            details += (
                "  |  Нет активных QI-групп - откройте «Операции» → «Группы QI» "
                "и подтвердите или создайте группу"
            )
        elif k_settings.enable_l_diversity and not active_qi_profiles:
            details += (
                "  |  Нет активных QI-групп - l нельзя проверить до подтверждения группы"
            )

        if k_settings.enable_l_diversity:
            sensitive = []
            if self.current_file_path is not None:
                try:
                    roles = load_manual_role_overrides(self.current_file_path)
                    sensitive = [
                        name for name, assigned in roles.items()
                        if "sensitive_attribute" in assigned
                        and self.current_dataframe is not None
                        and name in self.current_dataframe.columns
                    ]
                except (OSError, ValueError):
                    sensitive = []
            sensitive_text = ", ".join(sensitive) if sensitive else "не назначены"
            details += f"  |  Конфиденциальные поля: {sensitive_text}"
        self.plan_info.set(details)

    def run_k_anonymization(self) -> None:
        if self.current_dataframe is None or self.current_file_path is None:
            messagebox.showwarning("Нет таблицы", "Сначала загрузите CSV-файл.", parent=self)
            return
        default_k = self.settings.k_anonymization.default_k
        k_value = simpledialog.askinteger(
            "Параметры k-анонимизации",
            "Минимальный размер эквивалентной группы (k):",
            initialvalue=default_k,
            minvalue=2,
            parent=self,
        )
        if k_value is None:
            return
        output_path = filedialog.asksaveasfilename(
            parent=self,
            title="Сохранить результирующую CSV-таблицу",
            defaultextension=".csv",
            initialfile=f"{self.current_file_path.stem}_k_anonymized.csv",
            filetypes=(("CSV-файлы", "*.csv"),),
        )
        if not output_path:
            return
        destination = Path(output_path).resolve()
        if destination == self.current_file_path.resolve():
            messagebox.showerror(
                "Недопустимый путь",
                "Нельзя сохранять результат поверх исходного CSV.",
                parent=self,
            )
            return
        if destination.exists() and not messagebox.askyesno(
            "Перезапись CSV",
            f"Файл уже существует:\n{destination}\n\nПерезаписать?",
            parent=self,
        ):
            return
        try:
            result, report = execute_k_anonymization(
                self.current_dataframe,
                self.current_file_path,
                default_k=k_value,
                representative=self.settings.k_anonymization.numeric_representative,
                enable_l_diversity=self.settings.k_anonymization.enable_l_diversity,
                default_l=self.settings.k_anonymization.default_l,
                l_variant=self.settings.k_anonymization.l_diversity_variant,
            )
        except LDiversityViolationError as error:
            report_path = self._save_l_failure_report(error.report, destination)
            details = str(error)
            if report_path is not None:
                details += f"\n\nДиагностический отчёт сохранён: {report_path}"
            else:
                details += "\n\nCSV не создан. Диагностический отчёт не сохранён."
            messagebox.showerror(
                "Проверка l-разнообразия не пройдена", details, parent=self
            )
            return
        except (OSError, ValueError, RuntimeError) as error:
            messagebox.showerror("k-анонимизация не выполнена", str(error), parent=self)
            return

        try:
            save_csv(result, destination)
        except (OSError, ValueError) as error:
            messagebox.showerror("Ошибка сохранения CSV", str(error), parent=self)
            return

        report_path = self._offer_k_report(report, destination)
        self.status.set(f"k-анонимизация завершена. Результат: {destination.name}")
        profile_lines = [
            f"{item['group_name']}: k={item['required_k']}, минимум в классе={item['minimum_equivalence_class_size']}"
            for item in report["profiles"]
        ]
        l_status = report.get("l_diversity", {}).get("status")
        if l_status == "satisfied":
            l_message = (
                f"\n\nПроверка l-разнообразия пройдена: "
                f"l={report['l_diversity']['l']}, "
                f"критерий={report['l_diversity']['variant']}."
            )
        elif l_status == "not_checked":
            l_message = (
                "\n\nПроверка l-разнообразия не выполнялась: "
                "выключена в настройках."
            )
        else:
            l_message = "\n\nСтатус l-проверки отсутствует в отчёте."
        report_message = (
            f"\n\nТехнический отчёт: {report_path}"
            if report_path
            else "\n\nJSON-отчёт не сохранялся. Он не нужен для загрузки CSV в аналитические алгоритмы."
        )
        messagebox.showinfo(
            "k-анонимизация завершена",
            "CSV-таблица создана.\n\n"
            + "\n".join(profile_lines)
            + l_message
            + f"\n\nРезультат CSV: {destination}"
            + report_message,
            parent=self,
        )

    def _offer_k_report(self, report: dict, csv_path: Path) -> Path | None:
        should_save = messagebox.askyesno(
            "Сохранить технический отчёт?",
            "CSV — основная таблица для аналитики.\n"
            "JSON — дополнительный отчёт с параметрами и метриками проверки; "
            "аналитическим алгоритмам он не нужен.\n\n"
            "Сохранить JSON рядом с CSV?",
            parent=self,
            default=messagebox.NO,
        )
        if not should_save:
            return None
        report_path = csv_path.with_name(csv_path.stem + "_k_report.json")
        if report_path.exists() and not messagebox.askyesno(
            "Перезапись отчёта",
            f"Отчёт уже существует:\n{report_path}\n\nПерезаписать?",
            parent=self,
        ):
            return None
        try:
            save_k_anonymity_report(report, report_path)
        except (OSError, ValueError) as error:
            messagebox.showwarning(
                "CSV сохранён, отчёт не сохранён",
                f"Результирующая CSV-таблица сохранена.\n\nНе удалось сохранить отчёт: {error}",
                parent=self,
            )
            return None
        return report_path

    def _save_l_failure_report(self, report: dict, csv_destination: Path) -> Path | None:
        report_path = csv_destination.with_name(
            csv_destination.stem + "_l_diversity_failed_report.json"
        )
        if report_path.exists() and not messagebox.askyesno(
            "Перезапись диагностического отчёта",
            f"Отчёт уже существует:\n{report_path}\n\nПерезаписать?",
            parent=self,
        ):
            return None
        try:
            save_k_anonymity_report(report, report_path)
        except (OSError, ValueError) as error:
            messagebox.showwarning(
                "Не удалось сохранить отчёт",
                f"CSV не создан. Причину смотри в сообщении об ошибке.\n\n{error}",
                parent=self,
            )
            return None
        return report_path

    def anonymize_selected_operations(self) -> None:
        selected_operations = []
        if self.settings.anonymization.tokenize_direct_identifiers:
            selected_operations.append(TOKENIZE_DIRECT_IDENTIFIERS)
        if self.settings.anonymization.remove_direct_identifiers:
            selected_operations.append(REMOVE_DIRECT_IDENTIFIERS)
        if self.settings.anonymization.enable_k_anonymity:
            selected_operations.append(K_ANONYMITY)

        if not selected_operations:
            messagebox.showwarning(
                "Операции не выбраны",
                "В настройках не выбрана ни одна операция для суммарной "
                "анонимизации. Отдельные операции доступны в меню «Операции».",
                parent=self,
            )
            return

        if (
            self.settings.k_anonymization.enable_l_diversity
            and K_ANONYMITY not in selected_operations
        ):
            proceed = messagebox.askyesno(
                "l-проверка не будет выполнена",
                "l-разнообразие включено в настройках, но k-анонимизация "
                "не выбрана для суммарного запуска. Поэтому l-проверка сейчас "
                "не выполнится. Продолжить выбранные операции без неё?",
                parent=self,
            )
            if not proceed:
                return

        if K_ANONYMITY in selected_operations:
            try:
                active_qi_profiles = [
                    group for group in load_quasi_identifier_groups(self.current_file_path)
                    if group.get("active", group.get("source") != "automatic")
                ]
            except (OSError, ValueError) as error:
                messagebox.showerror("Ошибка QI-профилей", str(error), parent=self)
                return
            if not active_qi_profiles:
                messagebox.showerror(
                    "Нет активных QI-групп",
                    "k-анонимизация и l-проверка не будут выполнены. "
                    "Откройте меню «Операции» → «Группы квази-идентификаторов...», "
                    "подтвердите хотя бы одну группу и повторите запуск.",
                    parent=self,
                )
                return

        self._execute_anonymization(
            selected_operations,
            output_suffix="_anonymized",
            title="Сохранить результат суммарной анонимизации",
            aggregate=True,
        )

    def tokenize_direct_identifiers(self) -> None:
        self._execute_anonymization(
            [TOKENIZE_DIRECT_IDENTIFIERS],
            output_suffix="_tokenized",
            title="Сохранить таблицу с токенизированными идентификаторами",
        )

    def remove_direct_identifiers(self) -> None:
        self._execute_anonymization(
            [REMOVE_DIRECT_IDENTIFIERS],
            output_suffix="_without_identifiers",
            title="Сохранить таблицу без прямых идентификаторов",
        )

    def _execute_anonymization(
        self,
        operations: list[str],
        output_suffix: str,
        title: str,
        aggregate: bool = False,
    ) -> None:
        if self.current_dataframe is None or self.current_file_path is None:
            messagebox.showwarning("Нет таблицы", "Сначала загрузите CSV-файл.", parent=self)
            return

        output_path = filedialog.asksaveasfilename(
            parent=self,
            title=title,
            defaultextension=".csv",
            initialfile=f"{self.current_file_path.stem}{output_suffix}.csv",
            filetypes=(("CSV-файлы", "*.csv"),),
        )
        if not output_path:
            return
        destination = Path(output_path).resolve()
        if destination == self.current_file_path.resolve():
            messagebox.showerror(
                "Недопустимый путь",
                "Нельзя сохранять результат поверх исходной таблицы.",
                parent=self,
            )
            return
        if destination.exists() and not messagebox.askyesno(
            "Перезапись CSV",
            f"Файл уже существует:\n{destination}\n\nПерезаписать?",
            parent=self,
        ):
            return

        try:
            execution = apply_anonymization_operations(
                self.current_dataframe,
                self.current_file_path,
                operations,
                default_k=self.settings.k_anonymization.default_k,
                representative=self.settings.k_anonymization.numeric_representative,
                enable_l_diversity=self.settings.k_anonymization.enable_l_diversity,
                default_l=self.settings.k_anonymization.default_l,
                l_variant=self.settings.k_anonymization.l_diversity_variant,
            )
        except LDiversityViolationError as error:
            report_path = self._save_l_failure_report(error.report, destination)
            details = str(error)
            details += (
                f"\n\nДиагностический JSON: {report_path}"
                if report_path is not None
                else "\n\nCSV не создан. Диагностический отчёт не сохранён."
            )
            messagebox.showerror(
                "Проверка l-разнообразия не пройдена", details, parent=self
            )
            return
        except (OSError, ValueError, RuntimeError) as error:
            messagebox.showerror(
                "Невозможно выполнить операцию", str(error), parent=self
            )
            return

        try:
            save_csv(execution.dataframe, destination)
        except (OSError, ValueError) as error:
            messagebox.showerror("Ошибка сохранения CSV", str(error), parent=self)
            return

        report_path = None
        if execution.k_report is not None:
            report_path = self._offer_k_report(execution.k_report, destination)

        operation_labels = {
            TOKENIZE_DIRECT_IDENTIFIERS: "токенизация прямых идентификаторов",
            REMOVE_DIRECT_IDENTIFIERS: "удаление прямых идентификаторов",
            K_ANONYMITY: "k-анонимизация",
        }
        operations_text = ", ".join(operation_labels[item] for item in execution.operations)
        affected_text = ", ".join(execution.affected_columns) or "нет"
        details = [
            f"Выполненные операции: {operations_text}",
            f"Обработанные столбцы: {affected_text}",
            f"CSV для аналитики сохранён: {destination}",
        ]
        if execution.k_report is not None:
            l_report = execution.k_report.get("l_diversity", {})
            if l_report.get("status") == "satisfied":
                details.append(
                    f"Проверка l-разнообразия пройдена: l={l_report['l']}, "
                    f"критерий={l_report['variant']}"
                )
            elif l_report.get("status") == "not_checked":
                details.append(
                    "Проверка l-разнообразия не выполнялась: выключена в настройках."
                )
            if report_path is not None:
                details.append(f"Технический отчёт JSON: {report_path}")
            else:
                details.append("JSON-отчёт не сохранялся; для работы с CSV он не нужен.")
        else:
            if self.settings.k_anonymization.enable_l_diversity:
                details.append(
                    "Проверка l-разнообразия не выполнялась: k-анонимизация не входила "
                    "в выбранные операции."
                )
            else:
                details.append(
                    "Проверка l-разнообразия не выполнялась: k-анонимизация не запускалась, "
                    "а l-проверка выключена в настройках."
                )
        if TOKENIZE_DIRECT_IDENTIFIERS in execution.operations:
            details.append(
                "Токенизация является псевдонимизацией и сама по себе не гарантирует анонимность данных."
            )
        completion_title = "Суммарная анонимизация завершена" if aggregate else "Операция завершена"
        self.status.set(f"{completion_title}: {operations_text}. Результат: {destination.name}")
        messagebox.showinfo(completion_title, "\n\n".join(details), parent=self)

    def show_attribute_classification(self) -> None:
        if self.current_dataframe is None or self.current_file_path is None:
            messagebox.showwarning("Нет таблицы", "Сначала загрузите CSV-файл.")
            return

        if (
            self.attribute_classification_window is not None
            and self.attribute_classification_window.winfo_exists()
        ):
            self.attribute_classification_window.lift()
            return

        try:
            manual_overrides = load_manual_role_overrides(self.current_file_path)
            if self.settings.data_type_analysis.enable_multiple_quasi_identifier_groups:
                self._refresh_automatic_quasi_identifier_groups()
        except (OSError, ValueError) as error:
            messagebox.showerror("Ошибка профиля атрибутов", str(error))
            return

        def persist_overrides(overrides: dict[str, list[str]]) -> bool:
            try:
                save_manual_role_overrides(self.current_file_path, overrides)
            except (OSError, ValueError) as error:
                messagebox.showerror("Ошибка сохранения ролей", str(error), parent=self)
                return False
            self.status.set("Ручные назначения атрибутов сохранены.")
            self._update_plan_summary()
            return True

        self.attribute_classification_window = AttributeClassificationWindow(
            self,
            self.current_dataframe,
            manual_overrides,
            persist_overrides,
        )

    def _refresh_automatic_quasi_identifier_groups(self) -> list[dict]:
        if self.current_dataframe is None or self.current_file_path is None:
            raise ValueError("Сначала загрузите CSV-файл.")
        existing = load_quasi_identifier_groups(self.current_file_path)
        manual_groups = [group for group in existing if group.get("source") != "automatic"]
        suggested = suggest_quasi_identifier_groups(self.current_dataframe)
        manual_ids = {group["id"] for group in manual_groups}
        merged = manual_groups + [
            group for group in suggested if group["id"] not in manual_ids
        ]
        save_quasi_identifier_groups(
            self.current_file_path,
            merged,
            available_columns=list(self.current_dataframe.columns),
        )
        return suggested

    def show_quasi_identifier_groups(self) -> None:
        if self.current_dataframe is None or self.current_file_path is None:
            messagebox.showwarning("Нет таблицы", "Сначала загрузите CSV-файл.")
            return
        if (
            self.quasi_identifier_groups_window is not None
            and self.quasi_identifier_groups_window.winfo_exists()
        ):
            self.quasi_identifier_groups_window.lift()
            return

        try:
            groups = load_quasi_identifier_groups(self.current_file_path)
            if (
                not groups
                and self.settings.data_type_analysis.enable_multiple_quasi_identifier_groups
            ):
                self._refresh_automatic_quasi_identifier_groups()
                groups = load_quasi_identifier_groups(self.current_file_path)
        except (OSError, ValueError) as error:
            messagebox.showerror("Ошибка анализа QI", str(error), parent=self)
            return

        def persist_groups(updated_groups: list[dict]) -> bool:
            save_quasi_identifier_groups(
                self.current_file_path,
                updated_groups,
                available_columns=list(self.current_dataframe.columns),
            )
            self.status.set("Группы квази-идентификаторов сохранены.")
            self._update_anonymization_controls()
            return True

        self.quasi_identifier_groups_window = QuasiIdentifierGroupsWindow(
            self,
            [str(column) for column in self.current_dataframe.columns],
            groups,
            persist_groups,
            self._refresh_automatic_quasi_identifier_groups,
            self.current_file_path,
        )
