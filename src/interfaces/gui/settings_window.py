import tkinter as tk
from collections.abc import Callable
from tkinter import messagebox, ttk

from infrastructure.settings_manager import (
    AppSettings,
    DataTypeAnalysisSettings,
    save_settings,
)


APP_BACKGROUND = "#F4F5F7"


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
        self.geometry("540x300")
        self.minsize(460, 260)
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

        container = ttk.Frame(self, padding=18, style="Settings.TFrame")
        container.pack(fill="both", expand=True)

        ttk.Label(
            container,
            text="Анализ типов данных",
            font=("Segoe UI", 12, "bold"),
            style="Settings.TLabel",
        ).pack(anchor="w", pady=(0, 16))

        ttk.Checkbutton(
            container,
            text="Определение номинальных атрибутов",
            variable=self.detect_nominal,
            command=self._toggle_threshold,
            style="Settings.TCheckbutton",
        ).pack(anchor="w")

        self.threshold_frame = ttk.Frame(container, style="Settings.TFrame")
        ttk.Label(
            self.threshold_frame,
            text="Порог уникальных непустых значений, %:",
            style="Settings.TLabel",
        ).pack(side="left")
        self.threshold_input = ttk.Spinbox(
            self.threshold_frame,
            from_=0,
            to=100,
            increment=0.5,
            textvariable=self.threshold,
            width=8,
        )
        self.threshold_input.pack(side="left", padx=(10, 0))

        ttk.Label(
            container,
            text=(
                "Столбец считается номинальным, если доля "
                "уникальных непустых значений не превышает "
                "заданный процент."
            ),
            wraplength=490,
            style="Settings.TLabel",
        ).pack(anchor="w", pady=(12, 0))

        buttons = ttk.Frame(container, style="Settings.TFrame")
        buttons.pack(side="bottom", fill="x", pady=(20, 0))
        ttk.Button(buttons, text="Сохранить", command=self._save).pack(side="right")
        ttk.Button(buttons, text="Отмена", command=self.destroy).pack(
            side="right", padx=(0, 8)
        )

        self._toggle_threshold()
        self.grab_set()

    def _toggle_threshold(self) -> None:
        if self.detect_nominal.get():
            self.threshold_frame.pack(fill="x", anchor="w", pady=(12, 0))
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
            )
        )
        try:
            save_settings(settings)
        except OSError as error:
            messagebox.showerror("Ошибка сохранения", str(error), parent=self)
            return

        self.on_save(settings)
        self.destroy()
