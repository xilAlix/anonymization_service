from pathlib import Path
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

import pandas as pd

from application.k_anonymization_workflow import (
    LDiversityViolationError,
    save_k_anonymity_report,
)
from application.anonymization_workflow import (
    K_ANONYMITY,
    REMOVE_DIRECT_IDENTIFIERS,
    TOKENIZE_DIRECT_IDENTIFIERS,
)
from data_processing.csv_handler import load_csv
from data_processing.quasi_identifier_analyzer import suggest_quasi_identifier_groups
from infrastructure.attribute_profile_store import (
    load_manual_role_overrides,
    save_manual_role_overrides,
    load_semantic_types,
    save_semantic_types,
    load_quasi_identifier_groups,
    save_quasi_identifier_groups,
)
from data_processing.schema_inspector import analyze_column_types
from infrastructure.settings_manager import AppSettings, load_settings
from application.analysis_workflow import export_analysis_results
from application.service import analyze_session_source, execute_anonymization_for_session
from application.session_workflow import DatasetSession
from interfaces.gui.analysis_results_view import AnalysisResultsView, DataFrameTable, DateColumnDialog
from interfaces.gui.session_evaluation_view import SessionEvaluationView
from interfaces.gui.l_diversity_results_view import LDiversityResultsWindow
from data_analysis.descriptive_statistics import inspect_date_columns
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
        self.project_data_root = Path(__file__).resolve().parents[3] / "data" / "synthetic"
        self.short_example_path = self.project_data_root / "analysis_example_30.csv"
        self.demo_datasets = {
            "retail": self.project_data_root / "retail_customers_orders_60.csv",
            "finance": self.project_data_root / "financial_transactions_90.csv",
            "hr": self.project_data_root / "employee_training_50.csv",
        }
        self.manual_date_formats: dict[str, str] = {}
        self.result_tab: ttk.Frame | None = None
        self.analysis_tab: ttk.Frame | None = None
        self.analysis_results = None
        self.evaluation_tab: ttk.Frame | None = None
        self.dataset_session: DatasetSession | None = None
        self.current_dataframe: pd.DataFrame | None = None
        self.current_file_path: Path | None = None
        self.preview_limit = 500
        self.settings = load_settings()
        self.settings_window: SettingsWindow | None = None
        self.column_types_window: ColumnTypesWindow | None = None
        self.attribute_classification_window: AttributeClassificationWindow | None = None
        self.quasi_identifier_groups_window: QuasiIdentifierGroupsWindow | None = None
        self.l_diversity_window: LDiversityResultsWindow | None = None

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
        operations_menu.add_command(label="Загрузить пример (100 строк)", command=self.open_example)
        operations_menu.add_command(
            label="Загрузить короткий пример (30 строк)",
            command=self.open_short_example,
        )
        operations_menu.add_separator()
        operations_menu.add_command(
            label="Анализ текущей таблицы",
            command=self.analyze_current_table,
            state="disabled",
        )
        self.analysis_menu_index = 4
        operations_menu.add_command(
            label="Назначить столбцы дат...",
            command=self.configure_date_columns,
            state="disabled",
        )
        self.date_menu_index = 5
        operations_menu.add_separator()
        operations_menu.add_command(
            label="Типы данных и семантика атрибутов...",
            command=self.show_column_types,
            state="disabled",
        )
        self.types_menu_index = 7
        operations_menu.add_command(
            label="Классифицировать атрибуты",
            command=self.show_attribute_classification,
            state="disabled",
        )
        self.classification_menu_index = 8
        operations_menu.add_command(
            label="Группы квази-идентификаторов...",
            command=self.show_quasi_identifier_groups,
            state="disabled",
        )
        self.quasi_identifier_groups_menu_index = 9
        operations_menu.add_separator()
        operations_menu.add_command(
            label="Токенизировать прямые идентификаторы...",
            command=self.tokenize_direct_identifiers,
            state="disabled",
        )
        self.tokenization_menu_index = 11
        operations_menu.add_command(
            label="Удалить столбцы с прямыми идентификаторами...",
            command=self.remove_direct_identifiers,
            state="disabled",
        )
        self.removal_menu_index = 12
        operations_menu.add_separator()
        operations_menu.add_command(
            label="Выполнить k-анонимизацию...",
            command=self.run_k_anonymization,
            state="disabled",
        )
        self.k_anonymization_menu_index = 14
        examples_menu = tk.Menu(operations_menu, tearoff=False)
        examples_menu.add_command(
            label="Клиенты и заказы (60 строк)",
            command=lambda: self.open_demo_dataset("retail"),
        )
        examples_menu.add_command(
            label="Финансовые операции (90 строк)",
            command=lambda: self.open_demo_dataset("finance"),
        )
        examples_menu.add_command(
            label="Сотрудники и обучение (50 строк)",
            command=lambda: self.open_demo_dataset("hr"),
        )
        operations_menu.add_cascade(label="Дополнительные примеры", menu=examples_menu)
        menu_bar.add_cascade(label="Операции", menu=operations_menu)
        self.operations_menu = operations_menu
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
        self.analyze_button = ttk.Button(
            toolbar,
            text="Анализ",
            command=self.analyze_current_table,
            state="disabled",
        )
        self.analyze_button.pack(side="right", padx=(0, 8))
        ToolTip(
            self.analyze_button,
            "Рассчитывает описательную статистику и корреляции исходной таблицы. Данные не изменяются.",
        )
        ToolTip(
            self.anonymize_button,
            "Создаёт новый CSV по выбранным операциям. Исходный файл не изменяется.",
        )

        info_frame = ttk.Frame(content, style="App.TFrame")
        info_frame.grid(row=1, column=0, sticky="ew", pady=(0, 4))
        self.table_info = tk.StringVar(value="Таблица не загружена")
        ttk.Label(
            info_frame,
            textvariable=self.table_info,
            style="App.TLabel",
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor="w")
        self.plan_info = tk.StringVar(value="Работа с таблицей доступна через меню «Операции».")
        ttk.Label(
            info_frame,
            textvariable=self.plan_info,
            style="App.TLabel",
            foreground="#526174",
            wraplength=1100,
        ).pack(anchor="w", pady=(3, 0))

        guide = ttk.Label(
            content,
            text="Откройте таблицу, затем выберите «Анализ» или «Анонимизировать». Просмотр результатов открывается в отдельных вкладках.",
            style="App.TLabel",
            foreground="#667085",
            wraplength=1100,
        )
        guide.grid(row=2, column=0, sticky="ew", pady=(2, 8))

        self.workspace = ttk.Notebook(content)
        self.workspace.grid(row=3, column=0, sticky="nsew")
        self.source_tab = ttk.Frame(self.workspace)
        self.workspace.add(self.source_tab, text="Исходная таблица")
        table_frame = ttk.Frame(self.source_tab, style="App.TFrame", padding=4)
        table_frame.pack(fill="both", expand=True)
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)

        self.table = ttk.Treeview(table_frame, show="headings")
        self.table.tag_configure("row_even", background="#FFFFFF")
        self.table.tag_configure("row_odd", background="#F1F5F9")
        vertical_scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.table.yview)
        horizontal_scroll = ttk.Scrollbar(table_frame, orient="horizontal", command=self.table.xview)
        self.table.configure(yscrollcommand=vertical_scroll.set, xscrollcommand=horizontal_scroll.set)
        self.table.grid(row=0, column=0, sticky="nsew")
        vertical_scroll.grid(row=0, column=1, sticky="ns")
        horizontal_scroll.grid(row=1, column=0, sticky="ew")

        self.status = tk.StringVar(value="Откройте CSV-файл или загрузите пример.")
        ttk.Label(
            self,
            textvariable=self.status,
            style="App.TLabel",
            anchor="w",
            padding=(8, 4),
        ).grid(row=1, column=0, sticky="ew")

    def _populate_dataframe_table(self, tree: ttk.Treeview, dataframe: pd.DataFrame) -> None:
        columns = [str(column) for column in dataframe.columns]
        tree.delete(*tree.get_children())
        tree.configure(columns=columns)
        for column in columns:
            tree.heading(column, text=column)
            tree.column(column, width=150, minwidth=90, anchor="w", stretch=True)
        for row_number, row in enumerate(dataframe.head(self.preview_limit).itertuples(index=False, name=None)):
            values = ["" if pd.isna(value) else str(value) for value in row]
            row_style = "row_even" if row_number % 2 == 0 else "row_odd"
            tree.insert("", "end", values=values, tags=(row_style,))

    def _clear_derived_tabs(self) -> None:
        for attribute in ("result_tab", "analysis_tab", "evaluation_tab"):
            tab = getattr(self, attribute, None)
            if tab is not None:
                try:
                    self.workspace.forget(tab)
                    tab.destroy()
                except tk.TclError:
                    pass
                setattr(self, attribute, None)
        self.analysis_results = None

    def _show_anonymized_result(self, dataframe: pd.DataFrame, destination: Path) -> None:
        if self.result_tab is None or not self.result_tab.winfo_exists():
            self.result_tab = ttk.Frame(self.workspace)
            self.workspace.add(self.result_tab, text="Результат анонимизации")
        else:
            for child in self.result_tab.winfo_children():
                child.destroy()
        ttk.Label(
            self.result_tab,
            text=f"{destination.name}  |  {len(dataframe)} строк × {len(dataframe.columns)} столбцов",
            padding=(6, 6),
        ).pack(anchor="w")
        DataFrameTable(self.result_tab, dataframe, include_index=False).pack(fill="both", expand=True)
        self.workspace.tab(self.result_tab, text="Результат анонимизации")

        if self.dataset_session is not None:
            self._show_session_evaluation()

    def _show_session_evaluation(self) -> None:
        if self.dataset_session is None or self.dataset_session.result_dataframe is None:
            return
        if self.evaluation_tab is None or not self.evaluation_tab.winfo_exists():
            self.evaluation_tab = ttk.Frame(self.workspace)
            self.workspace.add(self.evaluation_tab, text="Оценка результата")
        else:
            for child in self.evaluation_tab.winfo_children():
                child.destroy()
        SessionEvaluationView(self.evaluation_tab, self.dataset_session).pack(fill="both", expand=True)
        self.workspace.tab(self.evaluation_tab, text="Оценка результата")
        self.workspace.select(self.evaluation_tab)

    def _show_analysis_results(self, results, source_path: Path) -> None:
        if self.analysis_tab is None or not self.analysis_tab.winfo_exists():
            self.analysis_tab = ttk.Frame(self.workspace)
            self.workspace.add(self.analysis_tab, text="Анализ")
        else:
            for child in self.analysis_tab.winfo_children():
                child.destroy()
        AnalysisResultsView(self.analysis_tab, results, source_path.name).pack(fill="both", expand=True)
        self.workspace.tab(self.analysis_tab, text="Анализ")
        self.workspace.select(self.analysis_tab)

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

        self._clear_derived_tabs()
        self.manual_date_formats = {}
        self.current_file_path = source_path.resolve()
        self.dataset_session = DatasetSession.start(self.current_file_path, dataframe)
        self.current_dataframe = self.dataset_session.source_dataframe
        self._populate_dataframe_table(self.table, self.current_dataframe)

        self.operations_menu.entryconfig(self.types_menu_index, state="normal")
        self.operations_menu.entryconfig(self.classification_menu_index, state="normal")
        self.operations_menu.entryconfig(self.analysis_menu_index, state="normal")
        self.operations_menu.entryconfig(self.date_menu_index, state="normal")
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

    def open_short_example(self) -> None:
        try:
            dataframe = load_csv(self.short_example_path)
            self._show_dataframe(dataframe, self.short_example_path)
        except (OSError, ValueError, pd.errors.ParserError) as error:
            messagebox.showerror("Ошибка открытия короткого примера", str(error), parent=self)

    def open_demo_dataset(self, dataset_key: str) -> None:
        path = self.demo_datasets.get(dataset_key)
        if path is None:
            self.status.set("Неизвестный демонстрационный набор.")
            return
        try:
            dataframe = load_csv(path)
            self._show_dataframe(dataframe, path)
            self.status.set(f"Загружен демонстрационный набор: {path.name}.")
        except (OSError, ValueError, pd.errors.ParserError) as error:
            messagebox.showerror("Ошибка открытия демонстрационного набора", str(error), parent=self)

    def configure_date_columns(self) -> None:
        if self.current_dataframe is None:
            self.status.set("Сначала загрузите CSV-файл.")
            return
        dialog = DateColumnDialog(self, self.current_dataframe, self.manual_date_formats)
        self.wait_window(dialog)
        if dialog.result is not None:
            self.manual_date_formats = dialog.result
            if self.manual_date_formats:
                self.status.set(
                    "Ручные форматы дат сохранены для текущей таблицы: "
                    + ", ".join(self.manual_date_formats)
                )
            else:
                self.status.set("Ручные назначения дат очищены; будет использовано автоопределение.")

    def analyze_current_table(self) -> None:
        if self.current_dataframe is None or self.current_file_path is None:
            self.status.set("Сначала загрузите CSV-файл.")
            return

        diagnostics = inspect_date_columns(self.current_dataframe)
        ambiguous = [
            column for column, info in diagnostics.items()
            if info.get("ambiguous") and column not in self.manual_date_formats
        ]
        if ambiguous:
            self.status.set(
                "Неоднозначные даты обработаны как категории: "
                + ", ".join(ambiguous)
                + ". Для распознавания откройте «Операции» → «Назначить столбцы дат...»."
            )

        try:
            if self.dataset_session is None:
                raise RuntimeError("Рабочая сессия таблицы не создана. Откройте CSV повторно.")
            results = analyze_session_source(
                self.dataset_session,
                date_formats=self.manual_date_formats,
            )
        except (OSError, ValueError, RuntimeError) as error:
            messagebox.showerror("Не удалось выполнить анализ", str(error), parent=self)
            return

        self.analysis_results = results
        self._show_analysis_results(results, self.current_file_path)
        self.status.set(
            f"Анализ выполнен: {len(results.included_columns)} атрибутов; "
            f"исключено прямых идентификаторов: {len(results.excluded_columns)}."
        )

        should_save = messagebox.askyesno(
            "Сохранить результаты анализа?",
            "Результаты показаны во вкладке «Анализ». Сохранить доступные таблицы CSV?",
            parent=self,
            default=messagebox.NO,
        )
        if not should_save:
            return
        output_directory = filedialog.askdirectory(
            parent=self,
            title="Выберите папку для таблиц анализа",
            mustexist=True,
        )
        if not output_directory:
            return
        output_directory_path = Path(output_directory)
        expected_outputs = [
            output_directory_path / f"{self.current_file_path.stem}_statistics.csv",
            output_directory_path / f"{self.current_file_path.stem}_pearson.csv",
            output_directory_path / f"{self.current_file_path.stem}_spearman.csv",
        ]
        existing_outputs = [path for path in expected_outputs if path.exists()]
        if existing_outputs and not messagebox.askyesno(
            "Перезапись таблиц анализа",
            "Следующие файлы уже существуют:\n"
            + "\n".join(str(path) for path in existing_outputs)
            + "\n\nПерезаписать их?",
            parent=self,
        ):
            return
        try:
            outputs = export_analysis_results(
                results,
                self.current_file_path,
                output_directory,
            )
        except (OSError, ValueError) as error:
            messagebox.showerror("Ошибка экспорта анализа", str(error), parent=self)
            return
        self.status.set(
            "Результаты анализа сохранены: "
            + ", ".join(path.name for path in outputs)
        )

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
        if self.current_dataframe is None or self.current_file_path is None:
            self.status.set("Сначала загрузите CSV-файл.")
            return

        if self.column_types_window is not None and self.column_types_window.winfo_exists():
            self.column_types_window.lift()
            return

        analysis_settings = self.settings.data_type_analysis
        results = analyze_column_types(
            self.current_dataframe,
            detect_nominal_attributes=analysis_settings.detect_nominal_attributes,
            nominal_unique_threshold_percent=(
                analysis_settings.nominal_unique_threshold_percent
            ),
        )
        try:
            semantic_types = load_semantic_types(self.current_file_path)
        except (OSError, ValueError) as error:
            messagebox.showerror("Ошибка чтения типов атрибутов", str(error), parent=self)
            return

        def persist_semantic_type(column: str, semantic_type: str) -> bool:
            updated = dict(semantic_types)
            if semantic_type == "auto":
                updated.pop(column, None)
            else:
                updated[column] = semantic_type
            try:
                save_semantic_types(
                    self.current_file_path,
                    updated,
                    available_columns=list(self.current_dataframe.columns),
                )
            except (OSError, ValueError) as error:
                messagebox.showerror("Ошибка сохранения семантического типа", str(error), parent=self)
                return False
            semantic_types.clear()
            semantic_types.update(updated)
            type_label = {
                "auto": "автоматический",
                "numeric": "числовой",
                "categorical": "категориальный",
                "datetime": "дата и время",
                "identifier": "идентификатороподобный",
            }[semantic_type]
            self.status.set(f"Для «{column}» сохранён семантический тип: {type_label}.")
            return True

        self.column_types_window = ColumnTypesWindow(
            self,
            results,
            analysis_settings.detect_nominal_attributes,
            semantic_types=semantic_types,
            save_semantic_type=persist_semantic_type,
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
        self.operations_menu.entryconfig(self.analysis_menu_index, state=individual_state)
        self.operations_menu.entryconfig(self.date_menu_index, state=individual_state)
        self.operations_menu.entryconfig(self.types_menu_index, state=individual_state)
        self.operations_menu.entryconfig(self.classification_menu_index, state=individual_state)
        self.operations_menu.entryconfig(self.tokenization_menu_index, state=individual_state)
        self.operations_menu.entryconfig(self.removal_menu_index, state=individual_state)
        self.analyze_button.configure(state=individual_state)

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
            excluded_from_l = []
            if self.current_file_path is not None:
                try:
                    roles = load_manual_role_overrides(self.current_file_path)
                    for name, assigned in roles.items():
                        if (
                            self.current_dataframe is None
                            or name not in self.current_dataframe.columns
                            or "sensitive_attribute" not in assigned
                        ):
                            continue
                        if "direct_identifier" in assigned:
                            excluded_from_l.append(name)
                        else:
                            sensitive.append(name)
                except (OSError, ValueError):
                    sensitive = []
                    excluded_from_l = []
            sensitive_text = ", ".join(sensitive) if sensitive else "не назначены"
            details += f"  |  Конфиденциальные поля для l: {sensitive_text}"
            if excluded_from_l:
                details += (
                    "  |  Не входят в l как прямые идентификаторы: "
                    + ", ".join(excluded_from_l)
                )
        self.plan_info.set(details)

    def run_k_anonymization(self) -> None:
        if self.current_dataframe is None or self.current_file_path is None:
            self.status.set("Сначала загрузите CSV-файл.")
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
            if self.dataset_session is None:
                raise RuntimeError("Рабочая сессия таблицы не создана. Откройте CSV повторно.")
            outcome = execute_anonymization_for_session(
                self.dataset_session,
                destination,
                [K_ANONYMITY],
                default_k=k_value,
                representative=self.settings.k_anonymization.numeric_representative,
                enable_l_diversity=self.settings.k_anonymization.enable_l_diversity,
                default_l=self.settings.k_anonymization.default_l,
                l_variant=self.settings.k_anonymization.l_diversity_variant,
                overwrite=destination.exists(),
            )
            result = outcome.execution.dataframe
            report = outcome.execution.k_report or {}
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
            self._show_l_diversity_diagnostics(error.report.get("l_diversity", {}))
            return
        except (OSError, ValueError, RuntimeError) as error:
            messagebox.showerror("k-анонимизация не выполнена", str(error), parent=self)
            return

        self._show_anonymized_result(result, destination)
        self._offer_k_report(report, destination)
        l_status = report.get("l_diversity", {}).get("status", "not_checked")
        self.status.set(
            f"k-анонимизация завершена: {len(report.get('profiles', []))} QI-профилей; "
            f"l-проверка: {l_status}. Результат: {destination.name}"
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
            self.status.set(
                "Не выбраны операции для суммарной анонимизации. "
                "Отдельные операции доступны в меню «Операции»."
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
            self.status.set("Сначала загрузите CSV-файл.")
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
            if self.dataset_session is None:
                raise RuntimeError("Рабочая сессия таблицы не создана. Откройте CSV повторно.")
            outcome = execute_anonymization_for_session(
                self.dataset_session,
                destination,
                operations,
                default_k=self.settings.k_anonymization.default_k,
                representative=self.settings.k_anonymization.numeric_representative,
                enable_l_diversity=self.settings.k_anonymization.enable_l_diversity,
                default_l=self.settings.k_anonymization.default_l,
                l_variant=self.settings.k_anonymization.l_diversity_variant,
                overwrite=destination.exists(),
            )
            execution = outcome.execution
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
            self._show_l_diversity_diagnostics(error.report.get("l_diversity", {}))
            return
        except (OSError, ValueError, RuntimeError) as error:
            messagebox.showerror(
                "Невозможно выполнить операцию", str(error), parent=self
            )
            return

        self._show_anonymized_result(execution.dataframe, destination)
        if execution.k_report is not None:
            self._offer_k_report(execution.k_report, destination)

        operation_labels = {
            TOKENIZE_DIRECT_IDENTIFIERS: "токенизация прямых идентификаторов",
            REMOVE_DIRECT_IDENTIFIERS: "удаление прямых идентификаторов",
            K_ANONYMITY: "k-анонимизация",
        }
        operations_text = ", ".join(operation_labels[item] for item in execution.operations)
        completion_title = "Суммарная анонимизация завершена" if aggregate else "Операция завершена"
        status_detail = ""
        if execution.k_report is not None:
            l_status = execution.k_report.get("l_diversity", {}).get("status", "not_checked")
            status_detail = f" Л-проверка: {l_status}."
        if TOKENIZE_DIRECT_IDENTIFIERS in execution.operations:
            status_detail += " Токенизация является псевдонимизацией."
        self.status.set(
            f"{completion_title}: {operations_text}.{status_detail} Результат: {destination.name}"
        )

    def _show_l_diversity_diagnostics(self, report: dict) -> None:
        if report.get("status") not in {"satisfied", "failed", "not_evaluable"}:
            return
        if self.l_diversity_window is not None and self.l_diversity_window.winfo_exists():
            self.l_diversity_window.destroy()
        self.l_diversity_window = LDiversityResultsWindow(self, report)

    def show_attribute_classification(self) -> None:
        if self.current_dataframe is None or self.current_file_path is None:
            self.status.set("Сначала загрузите CSV-файл.")
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
            self.status.set("Сначала загрузите CSV-файл.")
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
