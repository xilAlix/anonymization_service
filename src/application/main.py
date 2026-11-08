from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIRECTORY = PROJECT_ROOT / "src"

if str(SRC_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SRC_DIRECTORY))

from interfaces.gui.window import TableViewer, enable_windows_dpi_awareness


def main() -> None:
    enable_windows_dpi_awareness()
    example_path = PROJECT_ROOT / "data" / "synthetic" / "initial_dataset.csv"
    app = TableViewer(example_path)
    app.mainloop()


if __name__ == "__main__":
    main()
