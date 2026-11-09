import tkinter as tk


class ToolTip:
    """Показывает краткую подсказку при наведении на виджет."""

    def __init__(self, widget: tk.Widget, text: str, delay_ms: int = 450):
        self.widget = widget
        self.text = text
        self.delay_ms = delay_ms
        self._after_id: str | None = None
        self._window: tk.Toplevel | None = None
        self._label: tk.Label | None = None

        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self.hide, add="+")
        widget.bind("<ButtonPress>", self.hide, add="+")

    def set_text(self, text: str) -> None:
        self.text = text
        if self._label is not None:
            self._label.configure(text=text)

    def _schedule(self, _event=None) -> None:
        self._cancel_schedule()
        self._after_id = self.widget.after(self.delay_ms, self.show)

    def _cancel_schedule(self) -> None:
        if self._after_id is not None:
            try:
                self.widget.after_cancel(self._after_id)
            except tk.TclError:
                pass
            self._after_id = None

    def show(self) -> None:
        self._after_id = None
        if self._window is not None or not self.widget.winfo_exists():
            return

        x = self.widget.winfo_rootx() + 12
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        window = tk.Toplevel(self.widget)
        window.wm_overrideredirect(True)
        window.wm_geometry(f"+{x}+{y}")
        window.configure(background="#FFFBEA")
        label = tk.Label(
            window,
            text=self.text,
            justify="left",
            background="#FFFBEA",
            foreground="#273444",
            relief="solid",
            borderwidth=1,
            padx=8,
            pady=5,
            wraplength=360,
            font=("Segoe UI", 9),
        )
        label.pack()
        self._window = window
        self._label = label

    def hide(self, _event=None) -> None:
        self._cancel_schedule()
        if self._window is not None:
            try:
                self._window.destroy()
            except tk.TclError:
                pass
            self._window = None
            self._label = None
