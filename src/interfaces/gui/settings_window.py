import tkinter as tk
from collections.abc import Callable
from tkinter import messagebox, ttk

from infrastructure.settings_manager import (
    AnonymizationSettings,
    AppSettings,
    DataTypeAnalysisSettings,
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
        self.resizable(False, False)
        self.geometry("620x430")
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

        container = ttk.Frame(self, padding=18, style="Settings.TFrame")
        container.pack(fill="both", expand=True)

        ttk.Label(
            container,
            text="Анализ типов данных",
            font=("Segoe UI", 12, "bold"),
            style="Settings.TLabel",
        ).pack(anchor="w", pady=(0, 12))

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
        qi_groups_check.pack(anchor="w", pady=(9, 0))
        ToolTip(
            qi_groups_check,
            "При классификации таблицы формирует несколько предполагаемых профилей "
            "внешней фоновой информации, например демографический или географический. "
            "Названия и состав групп можно редактировать. Это эвристические предложения, "
            "а не доказательство доступности внешних источников.",
        )

        self.threshold_frame = ttk.Frame(container, style="Settings.TFrame")
        threshold_label = ttk.Label(
            self.threshold_frame,
            text="Порог уникальных непустых значений, %:",
            style="Settings.TLabel",
        )
        threshold_label.pack(side="left")
        self.threshold_input = ttk.Spinbox(
            self.threshold_frame,
            from_=0,
            to=100,
            increment=0.5,
            textvariable=self.threshold,
            width=8,
        )
        self.threshold_input.pack(side="left", padx=(10, 0))
        threshold_help = (
            "Максимальная доля уникальных непустых значений, при которой "
            "столбец считается номинальным."
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
            padx=12,
            pady=10,
        )
        anonymization_frame.pack(fill="x", anchor="w", pady=(18, 0))

        anonymization_title = tk.Label(
            anonymization_frame,
            text="Операции суммарной анонимизации",
            background=ANONYMIZATION_BACKGROUND,
            foreground="#20384D",
            font=("Segoe UI", 11, "bold"),
            anchor="w",
        )
        anonymization_title.pack(fill="x", pady=(0, 6))
        ToolTip(
            anonymization_title,
            "Отмеченные операции запускаются кнопкой «Анонимизировать» "
            "на главном окне. Отдельные операции доступны в меню «Операции».",
        )

        tokenize_check = tk.Checkbutton(
            anonymization_frame,
            text="Токенизация прямых идентификаторов",
            variable=self.tokenize_direct_identifiers,
            command=self._on_tokenization_selected,
            background=ANONYMIZATION_BACKGROUND,
            foreground="#20384D",
            activebackground=ANONYMIZATION_BACKGROUND,
            activeforeground="#20384D",
            selectcolor="#FFFFFF",
            anchor="w",
            justify="left",
            padx=2,
            pady=3,
            font=("Segoe UI", 10),
        )
        tokenize_check.pack(fill="x")
        ToolTip(
            tokenize_check,
            "Заменяет значения вручную назначенных прямых идентификаторов "
            "токенами. Повторяющиеся значения в одном столбце получают один токен.",
        )

        remove_check = tk.Checkbutton(
            anonymization_frame,
            text="Удаление столбцов с прямыми идентификаторами",
            variable=self.remove_direct_identifiers,
            command=self._on_removal_selected,
            background=ANONYMIZATION_BACKGROUND,
            foreground="#20384D",
            activebackground=ANONYMIZATION_BACKGROUND,
            activeforeground="#20384D",
            selectcolor="#FFFFFF",
            anchor="w",
            justify="left",
            padx=2,
            pady=3,
            font=("Segoe UI", 10),
        )
        remove_check.pack(fill="x")
        ToolTip(
            remove_check,
            "Удаляет целые столбцы с вручную назначенной ролью прямого "
            "идентификатора. Если столбец также аналитический, удаление "
            "будет отменено.",
        )
        buttons = ttk.Frame(container, style="Settings.TFrame")
        buttons.pack(side="bottom", fill="x", pady=(18, 0))
        ttk.Button(buttons, text="Сохранить", command=self._save).pack(side="right")
        ttk.Button(buttons, text="Отмена", command=self.destroy).pack(
            side="right", padx=(0, 8)
        )

        self._toggle_threshold()
        self.grab_set()
        self.update_idletasks()
        self._center_on_parent(parent)

    def _center_on_parent(self, parent: tk.Misc) -> None:
        x = parent.winfo_rootx() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{max(0, x)}+{max(0, y)}")

    def _on_tokenization_selected(self) -> None:
        if self.tokenize_direct_identifiers.get():
            self.remove_direct_identifiers.set(False)

    def _on_removal_selected(self) -> None:
        if self.remove_direct_identifiers.get():
            self.tokenize_direct_identifiers.set(False)

    def _toggle_threshold(self) -> None:
        if self.detect_nominal.get():
            self.threshold_frame.pack(fill="x", anchor="w", pady=(10, 0))
        else:
            self.threshold_frame.pack_forget()

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

        settings = AppSettings(
            data_type_analysis=DataTypeAnalysisSettings(
                detect_nominal_attributes=self.detect_nominal.get(),
                nominal_unique_threshold_percent=threshold,
                enable_multiple_quasi_identifier_groups=self.enable_multiple_qi_groups.get(),
            ),
            anonymization=AnonymizationSettings(
                tokenize_direct_identifiers=self.tokenize_direct_identifiers.get(),
                remove_direct_identifiers=self.remove_direct_identifiers.get(),
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
