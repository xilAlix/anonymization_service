from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

import pandas as pd

from infrastructure.attribute_profile_store import dataset_profile_key


@dataclass
class DatasetSession:
    """Состояние одной рабочей сессии с исходной и обработанной таблицами."""

    source_path: Path
    source_dataframe: pd.DataFrame
    session_id: str = field(default_factory=lambda: uuid4().hex)
    result_path: Path | None = None
    result_dataframe: pd.DataFrame | None = None
    operations: list[str] = field(default_factory=list)
    k_report: dict | None = None
    release_check: dict | None = None
    utility_evaluation: object | None = None

    @property
    def dataset_id(self) -> str:
        return dataset_profile_key(self.source_path)

    @classmethod
    def start(cls, source_path: str | Path, dataframe: pd.DataFrame) -> "DatasetSession":
        return cls(
            source_path=Path(source_path).resolve(),
            source_dataframe=dataframe.copy(deep=True),
        )

    def set_result(
        self,
        result_path: str | Path,
        dataframe: pd.DataFrame,
        operations: list[str],
        k_report: dict | None = None,
    ) -> None:
        self.result_path = Path(result_path).resolve()
        self.result_dataframe = dataframe.copy(deep=True)
        self.operations = list(operations)
        self.k_report = k_report
        self.release_check = None
        self.utility_evaluation = None
