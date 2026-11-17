from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from interfaces.gigachat.approvals import confirm_metadata_sharing
from interfaces.gigachat.function_bridge import sanitize_tool_result


class PrivacyGate:
    """Per-process consent ledger and outbound data minimizer."""

    def __init__(self, workspace: str | Path, input_func=input, print_func=print) -> None:
        self.workspace = Path(workspace).resolve()
        self.input_func = input_func
        self.print_func = print_func
        self.catalog_consent = False
        self.schema_consent: set[str] = set()
        self.aggregate_consent: set[str] = set()
        self.category_consent: set[tuple[str, str]] = set()
        self.blocked_datasets: set[str] = set()

    def _ask(self, prompt: str) -> bool:
        return confirm_metadata_sharing(prompt, self.input_func)

    def _safe_local_summary(self, title: str, value: Any) -> None:
        self.print_func("\n" + title)
        serialized = json.dumps(value, ensure_ascii=False, indent=2, default=str)
        self.print_func(serialized[:12000])
        if len(serialized) > 12000:
            self.print_func("...локальное представление сокращено на экране.")

    def authorize_tool_result(self, tool_name: str, arguments: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        dataset_id = str(arguments.get("dataset_id") or result.get("dataset_id") or "")
        if not result.get("ok", True):
            code = str(result.get("error_code") or "tool_call_failed")
            safe_messages = {
                "sharing_declined": "Передача этих метаданных модели не разрешена.",
                "category_sharing_declined": "Передача названий категорий этого столбца не разрешена.",
                "aggregate_sharing_declined": "Передача агрегированных результатов модели не разрешена.",
                "direct_identifier_blocked": "Категории этого атрибута нельзя передавать модели.",
                "unknown_column": "Указанный атрибут отсутствует в открытом наборе.",
                "invalid_threshold": "Задан недопустимый порог частоты категорий.",
                "dataset_not_open": "Сначала открой CSV в текущей консоли.",
                "unknown_dataset_id": "Набор не найден. Обнови список CSV и открой его заново.",
                "dataset_changed": "Исходный CSV изменился. Открой его заново.",
                "approval_invalid": "Подтверждение действия недействительно или устарело.",
                "approval_not_found": "Нет действующего подтверждённого предпросмотра.",
                "user_declined": "Пользователь отклонил действие.",
                "output_exists": "Файл результата уже существует; выбери другое имя или отдельно подтверди перезапись.",
                "source_overwrite_blocked": "Нельзя перезаписывать исходный CSV.",
                "schema_sharing_required": "Сначала отдельно разреши передачу структуры и имён столбцов этого набора.",
                "invalid_profile_changes": "Изменения профиля не прошли проверку структуры, типов, ролей или QI-групп.",
                "profile_save_failed": "Профиль не сохранён; подготовь предпросмотр изменений заново.",
                "plan_invalid": "Параметры плана анонимизации недопустимы или не согласуются с профилем.",
                "execution_failed": "Локальное выполнение завершилось ошибкой; подробности остались в локальной диагностике.",
            }
            return {
                "ok": False,
                "error_code": code,
                "message": safe_messages.get(code, "Локальный инструмент отклонил запрос. Подробности доступны только в локальной консоли."),
            }

        if tool_name == "list_datasets":
            if not self.catalog_consent:
                self._safe_local_summary("Список локальных CSV (передача пока не разрешена):", result.get("datasets", []))
                allowed = self._ask(
                    "GigaChat получит только имена CSV-файлов, их размеры и время изменения. "
                    "Содержимое файлов не отправляется. Разрешение действует до завершения этой консоли."
                )
                if not allowed:
                    return {"ok": False, "error_code": "sharing_declined", "message": "Пользователь не разрешил передавать список файлов модели."}
                self.catalog_consent = True
            return self._sanitize_paths(result)

        if tool_name == "open_dataset":
            # Only the opaque ID and an opened flag are sent. Filename and shape remain local.
            return {
                "ok": True,
                "dataset_id": dataset_id,
                "opened": True,
                "source_rows_included": False,
                "source_values_included": False,
            }

        if tool_name in {
            "inspect_dataset", "suggest_attribute_roles", "suggest_semantic_types",
            "suggest_qi_groups", "get_dataset_profile", "preview_profile_changes",
        }:
            if dataset_id not in self.schema_consent:
                preview = self._schema_preview(tool_name, result)
                self._safe_local_summary("Состав метаданных, которые будут переданы GigaChat:", preview)
                allowed = self._ask(
                    "Модель получит имена столбцов, типы данных, назначенные/предложенные роли "
                    "и структуру QI-групп. Строки и значения ячеек не передаются. "
                    "Счётчики, частоты и статистические значения будут запрошены отдельно."
                )
                if not allowed:
                    return {"ok": False, "error_code": "sharing_declined", "message": "Передача структуры набора отклонена; локальная таблица не изменена."}
                self.schema_consent.add(dataset_id)
            sanitized = self._sanitize_paths(result)
            if tool_name == "inspect_dataset" and not self.catalog_consent:
                sanitized.pop("name", None)
            return self._strip_small_counts(sanitized)

        if tool_name == "get_category_values":
            if dataset_id not in self.schema_consent:
                return {
                    "ok": False,
                    "error_code": "schema_sharing_required",
                    "message": "Сначала отдельно разреши передачу структуры и имён столбцов этого набора.",
                }
            column = str(arguments.get("column") or "")
            key = (dataset_id, column)
            if key not in self.category_consent:
                self._safe_local_summary(
                    f"Частые категории столбца «{column}» (передача отдельно не разрешена):",
                    result.get("categories", []),
                )
                allowed = self._ask(
                    f"Разрешить передать GigaChat названия категорий столбца «{column}» и их частоты? "
                    "Механизм инструмента исключает прямые идентификаторы и категории с частотой ниже установленного порога."
                )
                if not allowed:
                    return {"ok": False, "error_code": "category_sharing_declined", "message": "Названия категорий этого столбца не переданы."}
                self.category_consent.add(key)
            sanitized = self._sanitize_paths(result)
            if isinstance(sanitized, dict):
                sanitized.pop("suppressed_category_count", None)
            return sanitized

        if tool_name in {"analyze_anonymized_result", "get_utility_result"} and dataset_id in self.blocked_datasets:
            return {
                "ok": True,
                "available": False,
                "details_withheld": True,
                "message": "Подробная оценка полезности анонимизированного результата не передаётся модели, поскольку Privacy Release Check заблокировал выпуск.",
            }

        if tool_name in {"analyze_dataset", "analyze_anonymized_result", "get_utility_result", "get_privacy_result", "prepare_anonymization_plan"}:
            schema_dependent_tools = {"analyze_dataset", "analyze_anonymized_result", "get_utility_result", "prepare_anonymization_plan"}
            if tool_name in schema_dependent_tools and dataset_id not in self.schema_consent:
                return {
                    "ok": False,
                    "error_code": "schema_sharing_required",
                    "message": "Сначала отдельно разреши передачу структуры и имён столбцов этого набора.",
                }
            if tool_name == "get_privacy_result" and result.get("status") == "blocked":
                self.blocked_datasets.add(dataset_id)
            if dataset_id not in self.aggregate_consent:
                preview = self._aggregate_preview(tool_name, result)
                self._safe_local_summary("Агрегированные сведения для GigaChat:", preview)
                allowed = self._ask(
                    "Разрешить передать модели агрегированную статистику/результаты проверки для этого набора? "
                    "Передаются только сводные показатели; исходные строки, min/max, выбросы, мода "
                    "и категории не передаются этим каналом. Разрешение действует для этого набора до выхода из консоли."
                )
                if not allowed:
                    return {"ok": False, "error_code": "aggregate_sharing_declined", "message": "Передача агрегированных результатов GigaChat отклонена. Локальная обработка не блокируется."}
                self.aggregate_consent.add(dataset_id)
            sanitized = self._sanitize_paths(result)
            if tool_name == "prepare_anonymization_plan" and not self.catalog_consent:
                plan = sanitized.get("plan")
                if isinstance(plan, dict):
                    plan.pop("source_name", None)
                # Host stores the true suggested path locally; the model gets a generic name.
                sanitized["suggested_destination"] = "output/anonymized_result.csv"
            return sanitized

        if tool_name == "execute_anonymization":
            # Execution is local and separately confirmed. Detailed evaluation is only shared
            # after aggregate consent and is additionally suppressed for a blocked release.
            sanitized = self._sanitize_paths(result)
            privacy = result.get("privacy", {}) if isinstance(result, dict) else {}
            blocked = isinstance(privacy, dict) and privacy.get("status") == "blocked"
            if blocked:
                self.blocked_datasets.add(dataset_id)
            if (dataset_id not in self.aggregate_consent or blocked) and isinstance(sanitized, dict):
                for key in ("utility", "rows", "columns", "operations", "affected_columns"):
                    sanitized.pop(key, None)
                if blocked:
                    sanitized["privacy"] = {"ok": True, "available": True, "status": "blocked", "details_withheld": True}
                else:
                    sanitized.pop("privacy", None)
                sanitized["evaluation_details_withheld"] = True
            return sanitized

        return self._sanitize_paths(sanitize_tool_result(result))

    def _schema_preview(self, tool_name: str, result: dict[str, Any]) -> Any:
        if tool_name == "preview_profile_changes":
            return {
                "change_id": result.get("change_id"),
                "diff": result.get("diff"),
                "requires_local_confirmation": result.get("requires_local_confirmation"),
            }
        if tool_name == "inspect_dataset":
            return {
                "name": result.get("name"),
                "column_count": result.get("column_count"),
                "columns": [
                    {key: column.get(key) for key in ("name", "pandas_type", "semantic_type", "semantic_type_suggestion", "manually_assigned_roles")}
                    for column in result.get("columns", []) if isinstance(column, dict)
                ],
                "potential_qi_groups": [
                    {key: group.get(key) for key in ("name", "attributes", "confidence")}
                    for group in result.get("potential_qi_groups", []) if isinstance(group, dict)
                ],
            }
        return result

    @staticmethod
    def _strip_small_counts(result: dict[str, Any]) -> dict[str, Any]:
        cleaned = dict(result)
        cleaned.pop("row_count", None)
        cleaned.pop("source_rows", None)
        cleaned.pop("unique_tuple_count", None)
        cleaned.pop("unique_tuple_ratio", None)
        if isinstance(cleaned.get("columns"), list):
            cleaned["columns"] = [
                {key: value for key, value in column.items() if key not in {"non_null_count", "missing_count", "unique_count", "unique_percent"}}
                for column in cleaned["columns"] if isinstance(column, dict)
            ]
        if isinstance(cleaned.get("attributes"), list):
            cleaned["attributes"] = [
                {key: value for key, value in item.items() if key != "reasons"}
                for item in cleaned["attributes"] if isinstance(item, dict)
            ]
            for item in cleaned["attributes"]:
                if isinstance(item.get("suggestions"), list):
                    item["suggestions"] = [
                        {key: value for key, value in suggestion.items() if key != "reasons"}
                        for suggestion in item["suggestions"] if isinstance(suggestion, dict)
                    ]
        if isinstance(cleaned.get("role_suggestions"), list):
            for item in cleaned["role_suggestions"]:
                if isinstance(item, dict):
                    item.pop("reasons", None)
                    if isinstance(item.get("suggestions"), list):
                        item["suggestions"] = [
                            {key: value for key, value in suggestion.items() if key != "reasons"}
                            for suggestion in item["suggestions"] if isinstance(suggestion, dict)
                        ]
        for group_key in ("groups", "qi_groups", "active_qi_groups"):
            if isinstance(cleaned.get(group_key), list):
                cleaned[group_key] = [
                    {key: value for key, value in group.items() if key not in {
                        "unique_tuple_count", "unique_tuple_ratio", "row_count", "reasons",
                        "attribute_evidence", "external_source_families",
                    }}
                    for group in cleaned[group_key] if isinstance(group, dict)
                ]
        if isinstance(cleaned.get("potential_qi_groups"), list):
            cleaned["potential_qi_groups"] = [
                {key: value for key, value in group.items() if key not in {"unique_tuple_count", "unique_tuple_ratio", "reasons"}}
                for group in cleaned["potential_qi_groups"] if isinstance(group, dict)
            ]
        return cleaned

    @staticmethod
    def _aggregate_preview(tool_name: str, result: dict[str, Any]) -> Any:
        if tool_name == "prepare_anonymization_plan":
            return {"plan": result.get("plan"), "suggested_destination": result.get("suggested_destination")}
        return result

    def _sanitize_paths(self, value: Any) -> Any:
        root = str(self.workspace)
        home = str(Path.home())

        def walk(item: Any) -> Any:
            if isinstance(item, dict):
                return {key: walk(child) for key, child in item.items() if key not in {"approval_token", "local_diff"}}
            if isinstance(item, list):
                return [walk(child) for child in item]
            if isinstance(item, str):
                return item.replace(root, "<рабочая_папка>").replace(home, "<домашняя_папка>")
            return item
        return walk(value)
