import tkinter as tk


class SettingsWindow(tk.Toplevel):
    def __init__(self, parent: tk.Misc):
        super().__init__(parent)
        self.title("Настройки")
        self.geometry("640x420")
        self.minsize(480, 320)
        self.transient(parent)
