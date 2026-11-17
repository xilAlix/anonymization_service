from __future__ import annotations

import os
import tempfile
from pathlib import Path


MAX_CSV_FILE_BYTES = 100 * 1024 * 1024
MAX_CSV_ROWS = 500_000
MAX_CSV_COLUMNS = 250
MAX_CSV_CELLS = 5_000_000
MAX_JSON_FILE_BYTES = 10 * 1024 * 1024


def _is_link(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
        is_junction = getattr(path, "is_junction", None)
        return bool(is_junction and is_junction())
    except OSError:
        return True


def contains_link_component(path: str | Path) -> bool:
    absolute = Path(path).expanduser().absolute()
    return any(_is_link(component) for component in (absolute, *absolute.parents))


def validate_input_file(file_path: str | Path) -> Path:
    path = Path(file_path).expanduser().absolute()
    if contains_link_component(path):
        raise ValueError("Символические ссылки и junction в пути входного файла запрещены.")
    if not path.exists():
        raise FileNotFoundError(f"Файл не найден: {path}")
    if not path.is_file():
        raise ValueError(f"Входной путь не является обычным файлом: {path}")
    try:
        file_size = path.stat().st_size
    except OSError as error:
        raise OSError(f"Не удалось проверить входной файл: {error}") from error
    if file_size > MAX_CSV_FILE_BYTES:
        raise ValueError(
            f"CSV превышает ограничение размера {MAX_CSV_FILE_BYTES // (1024 * 1024)} МБ. "
            "Разделите файл на несколько частей."
        )
    return path.resolve(strict=True)


def validate_output_file(file_path: str | Path) -> Path:
    path = Path(file_path).expanduser().absolute()
    if not path.name or path.name in {".", ".."}:
        raise ValueError("Необходимо указать имя выходного файла.")
    if contains_link_component(path):
        raise ValueError("Символические ссылки и junction в пути результата запрещены.")
    parent = path.parent
    if not parent.exists():
        raise FileNotFoundError(f"Папка для сохранения не существует: {parent}")
    if not parent.is_dir():
        raise ValueError(f"Путь для сохранения не является папкой: {parent}")
    if path.exists() and not path.is_file():
        raise ValueError(f"Выходной путь не является обычным файлом: {path}")
    return parent.resolve(strict=True) / path.name


def atomic_write_text(
    file_path: str | Path,
    content: str,
    *,
    create_parents: bool = False,
    private: bool = True,
) -> Path:
    raw_path = Path(file_path).expanduser().absolute()
    if contains_link_component(raw_path.parent):
        raise ValueError("Символические ссылки и junction в пути результата запрещены.")
    if create_parents:
        raw_path.parent.mkdir(parents=True, exist_ok=True)
    path = validate_output_file(raw_path)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            prefix=".anonymization-",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(content)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        if private and os.name != "nt":
            os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, path)
        temporary_path = None
        if os.name != "nt":
            try:
                directory_fd = os.open(path.parent, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            except OSError:
                pass
        return path
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
