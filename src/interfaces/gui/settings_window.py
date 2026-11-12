import tkinter as tk
from collections.abc import Callable
from tkinter import messagebox, ttk

from infrastructure.settings_manager import (
    AnonymizationSettings,
    AppSettings,
    DataTypeAnalysisSettings,
    KAnonymizationSettings,
    save_settings,
)
from interfaces.gui.tooltip import ToolTip


APP_BACKGROUND = "#F4F5F7"
ANONYMIZATION_BACKGROUND = "#EAF2F8"
ANONYMIZATION_BORDER = "#9DB7CE"


class SettingsWindow(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Misc,
        settings: AppSettings,
        on_save: Callable[[AppSettings], None],
    ):
        super().__init__(parent)
        self.on_save = on_save
        self.title("Настройки")
        self.geometry("780x640")
        self.minsize(700, 560)
        self.resizable(True, True)
        self.transient(parent)
        self.configure(background=APP_BACKGROUND)

        style = ttk.Style(self)
        style.configure("Settings.TFrame", background=APP_BACKGROUND)
        style.configure(
            "Settings.TLabel",
            background=APP_BACKGROUND,
            foreground="#202938",
        )
        style.configure(
            "Settings.TCheckbutton",
            background=APP_BACKGROUND,
            foreground="#202938",
        )

        self.detect_nominal = tk.BooleanVar(
            value=settings.data_type_analysis.detect_nominal_attributes
        )
        self.threshold = tk.StringVar(
            value=f"{settings.data_type_analysis.nominal_unique_threshold_percent:g}"
        )
        self.enable_multiple_qi_groups = tk.BooleanVar(
            value=settings.data_type_analysis.enable_multiple_quasi_identifier_groups
        )
        self.tokenize_direct_identifiers = tk.BooleanVar(
            value=settings.anonymization.tokenize_direct_identifiers
        )
        self.remove_direct_identifiers = tk.BooleanVar(
            value=settings.anonymization.remove_direct_identifiers
        )
        self.enable_k_anonymity = tk.BooleanVar(
            value=settings.anonymization.enable_k_anonymity
        )
        self.default_k = tk.StringVar(value=str(settings.k_anonymization.default_k))
        self.numeric_representative = tk.StringVar(
            value=settings.k_anonymization.numeric_representative
        )

        shell = ttk.Frame(self, style="Settings.TFrame")
        shell.pack(fill="both", expand=True)
        shell.rowconfigure(0, weight=1)
        shell.columnconfigure(0, weight=1)

        canvas = tk.Canvas(
            shell,
            background=APP_BACKGROUND,
            highlightthickness=0,
            borderwidth=0,
        )
        scrollbar = ttk.Scrollbar(shell, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        container = ttk.Frame(canvas, padding=22, style="Settings.TFrame")
        content_window = canvas.create_window(
            (0, 0),
            window=container,
            anchor="nw",
        )
        container.bind(
            "<Configure>",
            lambda _event: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.bind(
            "<Configure>",
            lambda event: canvas.itemconfigure(content_window, width=event.width),
        )

        ttk.Label(
            container,
            text="Анализ типов данных",
            font=("Segoe UI", 13, "bold"),
            style="Settings.TLabel",
        ).pack(anchor="w", pady=(0, 14))

        nominal_check = ttk.Checkbutton(
            container,
            text="Определение номинальных атрибутов",
            variable=self.detect_nominal,
            command=self._toggle_threshold,
            style="Settings.TCheckbutton",
        )
        nominal_check.pack(anchor="w")
        ToolTip(
            nominal_check,
            "Эвристически отмечает столбцы по доле уникальных непустых значений. "
            "Это не семантическая классификация атрибутов.",
        )

        qi_groups_check = ttk.Checkbutton(
            container,
            text="Автоматически формировать несколько групп квази-идентификаторов",
            variable=self.enable_multiple_qi_groups,
            style="Settings.TCheckbutton",
        )
        qi_groups_check.pack(anchor="w", pady=(10, 0))
        ToolTip(
            qi_groups_check,
            "При классификации таблицы формирует предполагаемые профили внешней "
            "фоновой информации, например демографический или географический. "
            "Названия и состав групп можно редактировать. Это эвристические "
            "предложения, а не доказательство доступности внешних источников.",
        )

        self.threshold_frame = ttk.Frame(container, style="Settings.TFrame")
        self.threshold_frame.pack(fill="x", anchor="w", pady=(12, 0))
        threshold_label = ttk.Label(
            self.threshold_frame,
            text="Порог уникальности для номинальных атрибутов, %:",
            style="Settings.TLabel",
        )
        threshold_label.pack(side="left")
        self.threshold_input = ttk.Spinbox(
            self.threshold_frame,
            from_=0,
            to=100,
            increment=0.5,
            textvariable=self.threshold,
            width=14,
            justify="right",
        )
        self.threshold_input.pack(side="left", padx=(14, 0))
        threshold_help = (
            "Максимальная доля уникальных непустых значений, при которой "
            "столбец считается номинальным. Поле остаётся видимым, но становится "
            "неактивным, если автоматическое определение номинальности выключено."
        )
        ToolTip(threshold_label, threshold_help)
        ToolTip(self.threshold_input, threshold_help)

        anonymization_frame = tk.Frame(
            container,
            background=ANONYMIZATION_BACKGROUND,
            highlightthickness=1,
            highlightbackground=ANONYMIZATION_BORDER,
            highlightcolor=ANONYMIZATION_BORDER,
            bd=0,
            padx=14,
            pady=12,
        )
        anonymization_frame.pack(fill="x", anchor="w", pady=(22, 0))

        anonymization_title = tk.Label(
            anonymization_frame,
            text="Операции суммарной анонимизации",
            background=ANONYMIZATION_BACKGROUND,
            foreground="#20384D",
            font=("Segoe UI", 12, "bold"),
            anchor="w",
        )
        anonymization_title.pack(fill="x", pady=(0, 8))
        ToolTip(
            anonymization_title,
            "Отмеченные операции запускаются кнопкой «Анонимизировать» "
            "на главном окне. Отдельные операции доступны в меню «Операции».",
        )

        tokenize_check = self._create_anonymization_check(
            anonymization_frame,
            "Токенизация прямых идентификаторов",
            self.tokenize_direct_identifiers,
            self._on_tokenization_selected,
        )
        ToolTip(
            tokenize_check,
            "Заменяет значения вручную назначенных прямых идентификаторов "
            "токенами. Повторяющиеся значения в одном столбце получают один токен.",
        )

        remove_check = self._create_anonymization_check(
            anonymization_frame,
            "Удаление столбцов с прямыми идентификаторами",
            self.remove_direct_identifiers,
            self._on_removal_selected,
        )
        ToolTip(
            remove_check,
            "Удаляет целые столбцы с вручную назначенной ролью прямого "
            "идентификатора. Если столбец также аналитический, удаление "
            "будет отменено.",
        )

        k_operation_check = self._create_anonymization_check(
            anonymization_frame,
            "k-анонимизация по активным QI-профилям",
            self.enable_k_anonymity,
        )
        ToolTip(
            k_operation_check,
            "Включает k-анонимизацию в общий запуск кнопкой «Анонимизировать». "
            "Для отдельного запуска используйте меню «Операции».",
        )

        k_frame = tk.Frame(
            container,
            background="#F0F3F7",
            highlightthickness=1,
            highlightbackground="#C7D0DA",
            bd=0,
            padx=14,
            pady=12,
        )
        k_frame.pack(fill="x", anchor="w", pady=(16, 0))
        k_frame.columnconfigure(1, weight=1)
        tk.Label(
            k_frame,
            text="Параметры k-анонимизации",
            background="#F0F3F7",
            foreground="#20384D",
            font=("Segoe UI", 11, "bold"),
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))
        tk.Label(
            k_frame,
            text="Значение k по умолчанию:",
            background="#F0F3F7",
            foreground="#20384D",
        ).grid(row=1, column=0, sticky="w")
        self.default_k_input = ttk.Spinbox(
            k_frame,
            from_=2,
            to=1000000,
            textvariable=self.default_k,
            width=12,
            justify="right",
        )
        self.default_k_input.grid(row=1, column=1, sticky="w", padx=(16, 0))
        ToolTip(
            self.default_k_input,
            "Минимальный размер каждой группы по умолчанию. "
            "Отдельный QI-профиль может переопределить это значение.",
        )
        tk.Label(
            k_frame,
            text="Представитель числовой группы:",
            background="#F0F3F7",
            foreground="#20384D",
        ).grid(row=2, column=0, sticky="w", pady=(10, 0))
        self.representative_select = ttk.Combobox(
            k_frame,
            state="readonly",
            values=("mean", "median", "medoid"),
            textvariable=self.numeric_representative,
            width=14,
        )
        self.representative_select.grid(
            row=2,
            column=1,
            sticky="w",
            padx=(16, 0),
            pady=(10, 0),
        )
        ToolTip(
            self.representative_select,
            "Среднее, медиана или существующая запись-медоид как замена "
            "числовых значений кластера.",
        )

        buttons = ttk.Frame(shell, style="Settings.TFrame", padding=(18, 10, 18, 16))
        buttons.grid(row=1, column=0, columnspan=2, sticky="ew")
        buttons.columnconfigure(0, weight=1)
        ttk.Button(buttons, text="Сохранить", command=self._save).pack(side="right")
        ttk.Button(buttons, text="Отмена", command=self.destroy).pack(
            side="right", padx=(0, 10)
        )

        self._toggle_threshold()
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.grab_set()
        self.update_idletasks()
        self._center_on_parent(parent)

    @staticmethod
    def _create_anonymization_check(
        parent: tk.Misc,
        label: str,
        variable: tk.BooleanVar,
        command: Callable[[], None] | None = None,
    ) -> tk.Checkbutton:
        checkbox = tk.Checkbutton(
            parent,
            text=label,
            variable=variable,
            command=command,
            background=ANONYMIZATION_BACKGROUND,
            foreground="#20384D",
            activebackground=ANONYMIZATION_BACKGROUND,
            activeforeground="#20384D",
            selectcolor="#FFFFFF",
            anchor="w",
            justify="left",
            padx=2,
            pady=4,
            font=("Segoe UI", 10),
        )
        checkbox.pack(fill="x")
        return checkbox

    def _center_on_parent(self, parent: tk.Misc) -> None:
        self.update_idletasks()
        width = min(self.winfo_width(), self.winfo_screenwidth() - 40)
        height = min(self.winfo_height(), self.winfo_screenheight() - 60)
        x = parent.winfo_rootx() + (parent.winfo_width() - width) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - height) // 2
        x = max(20, min(x, self.winfo_screenwidth() - width - 20))
        y = max(20, min(y, self.winfo_screenheight() - height - 40))
        self.geometry(f"{width}x{height}+{x}+{y}")

    def _on_tokenization_selected(self) -> None:
        if self.tokenize_direct_identifiers.get():
            self.remove_direct_identifiers.set(False)

    def _on_removal_selected(self) -> None:
        if self.remove_direct_identifiers.get():
            self.tokenize_direct_identifiers.set(False)

    def _toggle_threshold(self) -> None:
        self.threshold_input.configure(
            state="normal" if self.detect_nominal.get() else "disabled"
        )

    def _save(self) -> None:
        try:
            threshold = float(self.threshold.get().replace(",", "."))
        except ValueError:
            messagebox.showerror(
                "Некорректное значение",
                "Укажи числовой порог от 0 до 100.",
                parent=self,
            )
            return

        if not 0 <= threshold <= 100:
            messagebox.showerror(
                "Некорректное значение",
                "Порог должен быть от 0 до 100.",
                parent=self,
            )
            return

        try:
            default_k = int(self.default_k.get())
        except ValueError:
            messagebox.showerror(
                "Некорректное значение",
                "Значение k должно быть целым числом не меньше 2.",
                parent=self,
            )
            return
        if default_k < 2:
            messagebox.showerror(
                "Некорректное значение",
                "Значение k должно быть не меньше 2.",
                parent=self,
            )
            return

        settings = AppSettings(
            data_type_analysis=DataTypeAnalysisSettings(
                detect_nominal_attributes=self.detect_nominal.get(),
                nominal_unique_threshold_percent=threshold,
                enable_multiple_quasi_identifier_groups=self.enable_multiple_qi_groups.get(),
            ),
            anonymization=AnonymizationSettings(
                tokenize_direct_identifiers=self.tokenize_direct_identifiers.get(),
                remove_direct_identifiers=self.remove_direct_identifiers.get(),
                enable_k_anonymity=self.enable_k_anonymity.get(),
            ),
            k_anonymization=KAnonymizationSettings(
                default_k=default_k,
                max_row_suppression_percent=5.0,
                numeric_representative=self.numeric_representative.get(),
            ),
        )
        try:
            save_settings(settings)
        except OSError as error:
            messagebox.showerror("Ошибка сохранения", str(error), parent=self)
            return
        except ValueError as error:
            messagebox.showerror("Некорректные настройки", str(error), parent=self)
            return

        self.on_save(settings)
        self.destroy()
