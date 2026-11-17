from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from secrets import token_hex
from threading import RLock

from application.session_workflow import DatasetSession
from data_processing.csv_handler import load_csv
from infrastructure.file_safety import contains_link_component


@dataclass(frozen=True)
class DatasetFileRef:
    dataset_id: str
    path: Path
    size_bytes: int
    modified_ns: int
    changed_ns: int
    inode: int

    @property
    def modified_at(self) -> str:
        return datetime.fromtimestamp(
            self.modified_ns / 1_000_000_000, tz=timezone.utc
        ).isoformat(timespec="seconds")


class DatasetRegistry:
    """Ограниченный реестр CSV и одной активной DatasetSession для MCP-процесса."""

    def __init__(self, workspace: str | Path) -> None:
        self.workspace = self._validate_workspace(workspace)
        self._files_by_id: dict[str, DatasetFileRef] = {}
        self._ids_by_relative_path: dict[str, str] = {}
        self._active_dataset_id: str | None = None
        self._active_session: DatasetSession | None = None
        self._lock = RLock()

    @staticmethod
    def _validate_workspace(workspace: str | Path) -> Path:
        raw_path = Path(workspace).expanduser().absolute()
        if contains_link_component(raw_path):
            raise ValueError(
                "Рабочая папка не должна содержать символические ссылки или junction."
            )
        if not raw_path.exists():
            raise FileNotFoundError("Рабочая папка не найдена.")
        if not raw_path.is_dir():
            raise ValueError("Рабочий путь не является папкой.")
        return raw_path.resolve(strict=True)

    def _safe_csv_file(self, candidate: Path) -> os.stat_result | None:
        try:
            if candidate.suffix.casefold() != ".csv":
                return None
            if contains_link_component(candidate):
                return None
            resolved_parent = candidate.parent.resolve(strict=True)
            if resolved_parent != self.workspace:
                return None
            file_stat = candidate.lstat()
            if not stat.S_ISREG(file_stat.st_mode):
                return None
            return file_stat
        except (OSError, RuntimeError):
            return None

    def list_datasets(self) -> list[dict[str, object]]:
        """Возвращает CSV только из корня рабочей папки, без абсолютных путей."""
        with self._lock:
            current: dict[str, DatasetFileRef] = {}
            new_ids_by_path: dict[str, str] = {}
            results: list[dict[str, object]] = []

            try:
                candidates = sorted(
                    self.workspace.iterdir(), key=lambda item: item.name.casefold()
                )
            except OSError as error:
                raise ValueError("Не удалось просмотреть рабочую папку.") from error

            for candidate in candidates:
                file_stat = self._safe_csv_file(candidate)
                if file_stat is None:
                    continue
                relative_name = candidate.name
                previous_id = self._ids_by_relative_path.get(relative_name)
                previous_ref = self._files_by_id.get(previous_id or "")
                unchanged = bool(
                    previous_ref
                    and previous_ref.size_bytes == file_stat.st_size
                    and previous_ref.modified_ns == file_stat.st_mtime_ns
                    and previous_ref.changed_ns == file_stat.st_ctime_ns
                    and previous_ref.inode == getattr(file_stat, "st_ino", 0)
                )
                dataset_id = previous_id if unchanged else f"dataset_{token_hex(8)}"
                file_ref = DatasetFileRef(
                    dataset_id=dataset_id,
                    path=candidate,
                    size_bytes=file_stat.st_size,
                    modified_ns=file_stat.st_mtime_ns,
                    changed_ns=file_stat.st_ctime_ns,
                    inode=getattr(file_stat, "st_ino", 0),
                )
                current[dataset_id] = file_ref
                new_ids_by_path[relative_name] = dataset_id
                results.append({
                    "dataset_id": dataset_id,
                    "name": candidate.name,
                    "size_bytes": file_stat.st_size,
                    "modified_at": file_ref.modified_at,
                })

            self._files_by_id = current
            self._ids_by_relative_path = new_ids_by_path

            if self._active_dataset_id not in self._files_by_id:
                self._active_dataset_id = None
                self._active_session = None

            return results

    def open_dataset(self, dataset_id: str) -> dict[str, object]:
        """Открывает только ранее выданный dataset_id; исходный CSV не изменяется."""
        if not isinstance(dataset_id, str) or not dataset_id:
            raise ValueError("Необходимо указать dataset_id из списка доступных CSV.")

        with self._lock:
            file_ref = self._files_by_id.get(dataset_id)
            if file_ref is None:
                raise KeyError("Набор не найден. Обновите список CSV и выберите dataset_id.")

            current_stat = self._safe_csv_file(file_ref.path)
            if current_stat is None:
                self._invalidate_dataset(dataset_id, file_ref.path.name)
                raise ValueError("Файл больше не доступен как обычный CSV в рабочей папке.")
            if not self._matches_signature(file_ref, current_stat):
                self._invalidate_dataset(dataset_id, file_ref.path.name)
                raise RuntimeError(
                    "CSV изменился после построения списка. Обновите список и откройте файл заново."
                )

            try:
                dataframe = load_csv(file_ref.path)
            except (OSError, ValueError, UnicodeError) as error:
                raise ValueError("Не удалось безопасно прочитать выбранный CSV.") from error

            after_load = self._safe_csv_file(file_ref.path)
            if after_load is None or not self._matches_signature(file_ref, after_load):
                raise RuntimeError(
                    "CSV изменился во время загрузки. Обновите список и повторите открытие."
                )

            session = DatasetSession.start(file_ref.path, dataframe)
            self._active_dataset_id = dataset_id
            self._active_session = session
            return {
                "ok": True,
                "dataset_id": dataset_id,
                "name": file_ref.path.name,
                "rows": int(len(dataframe)),
                "columns": int(len(dataframe.columns)),
                "session_id": session.session_id,
            }

    @staticmethod
    def _matches_signature(file_ref: DatasetFileRef, current_stat: os.stat_result) -> bool:
        return (
            current_stat.st_size == file_ref.size_bytes
            and current_stat.st_mtime_ns == file_ref.modified_ns
            and current_stat.st_ctime_ns == file_ref.changed_ns
            and getattr(current_stat, "st_ino", 0) == file_ref.inode
        )

    def _invalidate_dataset(self, dataset_id: str, file_name: str) -> None:
        self._files_by_id.pop(dataset_id, None)
        self._ids_by_relative_path.pop(file_name, None)
        if self._active_dataset_id == dataset_id:
            self._active_dataset_id = None
            self._active_session = None

    def get_active_session(self, dataset_id: str | None = None) -> DatasetSession:
        with self._lock:
            if self._active_session is None or self._active_dataset_id is None:
                raise LookupError("Сначала откройте CSV через open_dataset.")
            if dataset_id is not None and dataset_id != self._active_dataset_id:
                raise LookupError(
                    "Указанный набор не является текущим активным набором этой MCP-сессии."
                )
            file_ref = self._files_by_id.get(self._active_dataset_id)
            current_stat = self._safe_csv_file(file_ref.path) if file_ref else None
            if file_ref is None or current_stat is None or not self._matches_signature(file_ref, current_stat):
                if file_ref is not None:
                    self._invalidate_dataset(file_ref.dataset_id, file_ref.path.name)
                else:
                    self._active_dataset_id = None
                    self._active_session = None
                raise LookupError(
                    "Исходный CSV изменился или стал недоступен после открытия. Откройте его заново."
                )
            return self._active_session

    @property
    def active_dataset_id(self) -> str | None:
        return self._active_dataset_id

    def resolve_output_path(self, relative_path: str, *, create_parent: bool = False) -> Path:
        """Разрешает только относительный путь внутри workspace, без ссылок и обхода каталогов."""
        if not isinstance(relative_path, str) or not relative_path.strip():
            raise ValueError("Необходимо указать относительный путь выходного CSV.")
        raw = Path(relative_path)
        if raw.is_absolute() or raw.drive or any(part in {"..", ""} for part in raw.parts):
            raise ValueError("Выходной путь должен быть относительным и находиться внутри рабочей папки.")
        if raw.suffix.casefold() != ".csv":
            raise ValueError("Результат должен иметь расширение .csv.")
        target = self.workspace / raw
        if contains_link_component(target):
            raise ValueError("Символические ссылки и junction в выходном пути запрещены.")
        parent = target.parent
        if create_parent:
            parent.mkdir(parents=True, exist_ok=True)
        if not parent.exists() or not parent.is_dir():
            raise ValueError("Папка назначения не существует внутри рабочей директории.")
        resolved_parent = parent.resolve(strict=True)
        try:
            resolved_parent.relative_to(self.workspace)
        except ValueError as error:
            raise ValueError("Выходной путь выходит за пределы рабочей директории.") from error
        if contains_link_component(resolved_parent):
            raise ValueError("Символические ссылки и junction в выходном пути запрещены.")
        return resolved_parent / target.name
