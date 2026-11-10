import json
from pathlib import Path

import pandas as pd

from data_processing.algorithms.quasi_identifier_detection import (
    detect_quasi_identifier_groups,
)


KNOWLEDGE_CATALOG_PATH = (
    Path(__file__).resolve().parent
    / "algorithms"
    / "quasi_identifier_knowledge.json"
)


def _date_like_ratio(series: pd.Series, sample: pd.Series) -> float:
    if sample.empty:
        return 0.0
    if pd.api.types.is_datetime64_any_dtype(series.dtype):
        return 1.0
    text = sample.astype(str).str.strip()
    patterns = (
        r"^\d{4}-\d{1,2}-\d{1,2}(?:[T ].*)?$",
        r"^\d{1,2}[./-]\d{1,2}[./-]\d{2,4}$",
        r"^\d{4}/\d{1,2}/\d{1,2}$",
    )
    matches = text.str.match("|".join(f"(?:{pattern})" for pattern in patterns))
    return float(matches.mean()) if len(matches) else 0.0


def build_column_profiles(dataframe: pd.DataFrame, sample_size: int = 2000) -> list[dict]:
    profiles: list[dict] = []
    for attribute, series in dataframe.items():
        non_null = series.dropna()
        if len(non_null) > sample_size:
            sample = non_null.sample(n=sample_size, random_state=0)
        else:
            sample = non_null
        count = int(non_null.shape[0])
        unique_count = int(non_null.nunique(dropna=True))
        sample_text = sample.astype(str).str.strip().str.casefold()
        gender_values = {
            "m", "f", "male", "female", "man", "woman", "м", "ж",
            "муж", "жен", "мужской", "женский", "мужчина", "женщина",
        }
        gender_like_ratio = (
            float(sample_text.isin(gender_values).mean()) if len(sample_text) else 0.0
        )
        postal_patterns = (
            r"[0-9]{5}(?:-[0-9]{4})?",  # США: ZIP и ZIP+4
            r"[0-9]{6}",  # Индия: PIN code
            r"[a-z][0-9][a-z][ -]?[0-9][a-z][0-9]",  # Канада: postal code
        )
        postal_pattern = "|".join(f"(?:{pattern})" for pattern in postal_patterns)
        postal_like_ratio = (
            float(sample_text.str.fullmatch(postal_pattern).mean())
            if len(sample_text) else 0.0
        )
        numeric = pd.to_numeric(sample, errors="coerce").dropna()
        if len(numeric):
            integer_ratio = float((numeric % 1 == 0).mean())
            age_like_ratio = (
                float(((numeric >= 0) & (numeric <= 110) & (numeric % 1 == 0)).mean())
                if integer_ratio >= 0.8 else 0.0
            )
        else:
            age_like_ratio = 0.0
        profiles.append({
            "attribute": str(attribute),
            "pandas_type": str(series.dtype),
            "row_count": int(series.shape[0]),
            "non_null_count": count,
            "sample_count": int(len(sample)),
            "missing_ratio": (
                float(series.isna().mean()) if len(series) else 0.0
            ),
            "unique_count": unique_count,
            "unique_ratio": unique_count / count if count else 0.0,
            "date_like_ratio": _date_like_ratio(series, sample),
            "gender_like_ratio": gender_like_ratio,
            "postal_code_like_ratio": postal_like_ratio,
            "age_like_ratio": age_like_ratio,
            "sample_values": [str(value)[:120] for value in sample.head(12).tolist()],
        })
    return profiles


def load_quasi_identifier_knowledge(
    catalog_path: str | Path = KNOWLEDGE_CATALOG_PATH,
) -> dict:
    path = Path(catalog_path)
    try:
        catalog = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Не удалось прочитать каталог QI {path}: {error}") from error
    if not isinstance(catalog, dict) or not isinstance(catalog.get("families"), list):
        raise ValueError("Каталог QI имеет некорректную структуру.")
    return catalog


def suggest_quasi_identifier_groups(
    dataframe: pd.DataFrame,
    catalog_path: str | Path = KNOWLEDGE_CATALOG_PATH,
) -> list[dict]:
    profiles = build_column_profiles(dataframe)
    catalog = load_quasi_identifier_knowledge(catalog_path)
    groups = detect_quasi_identifier_groups(profiles, catalog)

    for group in groups:
        group["row_count"] = len(dataframe)
        attributes = group["attributes"]
        if not attributes or dataframe.empty:
            group["unique_tuple_count"] = 0
            group["unique_tuple_ratio"] = 0.0
            continue
        unique_rows = int(dataframe[attributes].drop_duplicates().shape[0])
        group["unique_tuple_count"] = unique_rows
        group["unique_tuple_ratio"] = unique_rows / len(dataframe)
        group["reasons"].append(
            f"Уникальные комбинации в этой таблице: {unique_rows} из {len(dataframe)} строк "
            f"({group['unique_tuple_ratio']:.1%}). Показатель помогает оценить различимость внутри файла, "
            "но не подтверждает возможность сопоставления с внешней базой."
        )
    return groups
