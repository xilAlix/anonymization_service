from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from application.anonymization_workflow import (
    K_ANONYMITY,
    REMOVE_DIRECT_IDENTIFIERS,
    TOKENIZE_DIRECT_IDENTIFIERS,
)
from infrastructure.attribute_profile_store import (
    DEFAULT_PROFILE_PATH,
    load_manual_role_overrides,
)


PASS = "passed"
WARNING = "warning"
BLOCKED = "blocked"


def evaluate_release_readiness(
    original: pd.DataFrame,
    transformed: pd.DataFrame,
    source_path: str | Path,
    operations: list[str],
    k_report: dict[str, Any] | None = None,
    l_diversity_enabled: bool = False,
    profile_path: str | Path = DEFAULT_PROFILE_PATH,
) -> dict[str, Any]:
    """Проверяет выбранные ограничения перед использованием результата вне исходной среды."""
    roles = load_manual_role_overrides(source_path, profile_path)
    source_columns = set(map(str, original.columns))
    result_columns = set(map(str, transformed.columns))
    direct_columns = [
        column for column, assigned in roles.items()
        if "direct_identifier" in assigned and column in source_columns
    ]
    sensitive_columns = [
        column for column, assigned in roles.items()
        if "sensitive_attribute" in assigned
        and "direct_identifier" not in assigned
        and column in source_columns
    ]
    classified_columns = {
        column for column, assigned in roles.items()
        if assigned and column in source_columns
    }
    unclassified_columns = sorted(source_columns - classified_columns)

    checks: list[dict[str, str]] = []

    added_columns = sorted(result_columns - source_columns)
    if added_columns:
        checks.append({
            "check": "Новые атрибуты",
            "status": WARNING,
            "details": (
                "В результате появились поля, для которых исходные роли и проверки не заданы: "
                + ", ".join(added_columns) + "."
            ),
        })
    if len(original) != len(transformed):
        checks.append({
            "check": "Количество записей",
            "status": WARNING,
            "details": (
                f"Количество строк изменилось: {len(original)} → {len(transformed)}. "
                "Проверьте, является ли это ожидаемым результатом."
            ),
        })

    remaining_direct = [column for column in direct_columns if column in result_columns]
    if not direct_columns:
        checks.append({
            "check": "Прямые идентификаторы",
            "status": WARNING,
            "details": "Роли прямых идентификаторов не назначены. Проверьте классификацию вручную.",
        })
    elif not remaining_direct:
        checks.append({
            "check": "Прямые идентификаторы",
            "status": PASS,
            "details": "Все вручную назначенные прямые идентификаторы отсутствуют в результате.",
        })
    elif TOKENIZE_DIRECT_IDENTIFIERS in operations:
        tokenized: list[str] = []
        unchanged: list[str] = []
        for column in remaining_direct:
            source_values = original[column].reset_index(drop=True)
            result_values = transformed[column].reset_index(drop=True)
            prefix_match = result_values.dropna().astype(str).str.startswith("ID_").all()
            changed = len(source_values) == len(result_values) and not source_values.equals(result_values)
            if prefix_match and changed:
                tokenized.append(column)
            else:
                unchanged.append(column)
        if unchanged:
            checks.append({
                "check": "Прямые идентификаторы",
                "status": BLOCKED,
                "details": "Не подтверждена токенизация: " + ", ".join(unchanged) + ".",
            })
        else:
            checks.append({
                "check": "Прямые идентификаторы",
                "status": WARNING,
                "details": (
                    "Значения заменены токенами: " + ", ".join(tokenized)
                    + ". Это псевдонимизация, а не гарантия анонимности."
                ),
            })
    elif REMOVE_DIRECT_IDENTIFIERS in operations:
        checks.append({
            "check": "Прямые идентификаторы",
            "status": BLOCKED,
            "details": "Некоторые назначенные прямые идентификаторы остались в результате.",
        })
    else:
        checks.append({
            "check": "Прямые идентификаторы",
            "status": BLOCKED,
            "details": "Прямые идентификаторы остались без обработки.",
        })

    if K_ANONYMITY in operations and k_report is not None:
        profiles = k_report.get("profiles", [])
        if profiles and all(item.get("satisfied") for item in profiles):
            checks.append({
                "check": "k-анонимность",
                "status": PASS,
                "details": f"Подтверждены все {len(profiles)} активных QI-профилей.",
            })
        else:
            checks.append({
                "check": "k-анонимность",
                "status": BLOCKED,
                "details": "В отчёте нет успешного подтверждения всех активных QI-профилей.",
            })
    else:
        checks.append({
            "check": "k-анонимность",
            "status": WARNING,
            "details": "k-анонимизация не выполнялась в этом запуске.",
        })

    l_report = (k_report or {}).get("l_diversity", {})
    if l_diversity_enabled:
        if l_report.get("status") == "satisfied":
            checks.append({
                "check": "l-разнообразие",
                "status": PASS,
                "details": (
                    f"Проверка пройдена: l={l_report.get('l')}, "
                    f"вариант={l_report.get('variant')}."
                ),
            })
        else:
            checks.append({
                "check": "l-разнообразие",
                "status": BLOCKED,
                "details": (
                    "Проверка не пройдена или не может быть выполнена: "
                    + str(l_report.get("reason", l_report.get("status", "нет отчёта")))
                ),
            })
    elif sensitive_columns:
        checks.append({
            "check": "l-разнообразие",
            "status": WARNING,
            "details": (
                "Назначены конфиденциальные атрибуты, но l-разнообразие не проверялось: "
                + ", ".join(sensitive_columns) + "."
            ),
        })
    else:
        checks.append({
            "check": "l-разнообразие",
            "status": WARNING,
            "details": "Нет проверяемых конфиденциальных атрибутов или l-проверка выключена.",
        })

    if unclassified_columns:
        checks.append({
            "check": "Классификация остальных полей",
            "status": WARNING,
            "details": (
                "Роли не назначены следующим полям: "
                + ", ".join(unclassified_columns) + ". Проверьте их назначение."
            ),
        })
    else:
        checks.append({
            "check": "Классификация остальных полей",
            "status": PASS,
            "details": "Для всех исходных столбцов сохранено ручное назначение роли.",
        })

    statuses = {item["status"] for item in checks}
    if BLOCKED in statuses:
        overall = "blocked"
    elif WARNING in statuses:
        overall = "warning"
    else:
        overall = "ready"

    return {
        "status": overall,
        "status_label": {
            "ready": "Проверки пройдены",
            "warning": "Требуется внимание",
            "blocked": "Передача заблокирована",
        }[overall],
        "checks": checks,
        "operations": list(operations),
        "direct_identifier_columns": direct_columns,
        "sensitive_attributes": sensitive_columns,
        "unclassified_columns": unclassified_columns,
        "added_columns": added_columns,
        "original_rows": len(original),
        "result_rows": len(transformed),
        "limitations": [
            "Статус отражает только выполненные проверки и не гарантирует абсолютную анонимность.",
            "Оценка не проверяет внешние источники и возможность связывания с другими наборами данных.",
            "Токенизация рассматривается как псевдонимизация.",
        ],
    }
