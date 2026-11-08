from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIRECTORY = PROJECT_ROOT / "src"
if str(SRC_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SRC_DIRECTORY))


def main() -> int:
    if len(sys.argv) > 1:
        from application.cli import run_cli

        return run_cli(sys.argv[1:])

    from interfaces.gui.window import TableViewer, enable_windows_dpi_awareness

    enable_windows_dpi_awareness()
    example_path = PROJECT_ROOT / "data" / "synthetic" / "initial_dataset.csv"
    app = TableViewer(example_path)
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
