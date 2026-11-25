from __future__ import annotations

from pathlib import Path
from typing import Any

from application.anonymization_workflow import (
    K_ANONYMITY,
    REMOVE_DIRECT_IDENTIFIERS,
    TOKENIZE_DIRECT_IDENTIFIERS,
)
from application.k_anonymization_workflow import LDiversityViolationError, TClosenessViolationError
from application.service import execute_anonymization_for_session, prepare_anonymization_plan as prepare_plan
from infrastructure.attribute_profile_store import DEFAULT_PROFILE_PATH
from interfaces.mcp.action_store import PendingActionStore
from interfaces.mcp.analysis_tools import get_privacy_result, serialize_utility, minimum_group_size
from interfaces.mcp.profile_tools import _profile_snapshot, profile_digest
from interfaces.mcp.registry import DatasetRegistry

SUPPORTED_OPERATIONS = [TOKENIZE_DIRECT_IDENTIFIERS, REMOVE_DIRECT_IDENTIFIERS, K_ANONYMITY]


def prepare_anonymization_plan(
    registry: DatasetRegistry,
    store: PendingActionStore,
    dataset_id: str,
    operations: list[str],
    default_k: int = 5,
    representative: str = "mean",
    enable_l_diversity: bool = True,
    default_l: int = 2,
    l_variant: str = "both",
    enable_t_closeness: bool = True,
    default_t: float = 0.4,
    profile_path: str | Path | None = None,
) -> dict[str, Any]:
    try:
        session = registry.get_active_session(dataset_id)
        plan = prepare_plan(
            session,
            operations,
            default_k=default_k,
            enable_l_diversity=enable_l_diversity,
            default_l=default_l,
            l_variant=l_variant,
            enable_t_closeness=enable_t_closeness,
            default_t=default_t,
            **({"profile_path": profile_path} if profile_path else {}),
        )
        snapshot = _profile_snapshot(session, str(profile_path or DEFAULT_PROFILE_PATH))
        pending = store.create(
            dataset_id=dataset_id,
            session_id=session.session_id,
            payload={
                "operations": list(operations),
                "default_k": default_k,
                "representative": representative,
                "enable_l_diversity": enable_l_diversity,
                "default_l": default_l,
                "l_variant": l_variant,
                "enable_t_closeness": enable_t_closeness,
                "default_t": default_t,
            },
            profile_digest=profile_digest(snapshot),
        )
        suggested_name = f"output/{session.source_path.stem}_anonymized.csv"
        return {
            "ok": True,
            "plan_id": pending["action_id"],
            "approval_token": pending["approval_token"],
            "plan": plan,
            "suggested_destination": suggested_name,
            "requires_local_confirmation": True,
        }
    except LookupError:
        return {"ok": False, "error_code": "dataset_not_open", "message": "Сначала откройте CSV."}
    except (OSError, ValueError) as error:
        return {"ok": False, "error_code": "plan_invalid", "message": str(error)}


def execute_anonymization(
    registry: DatasetRegistry,
    store: PendingActionStore,
    dataset_id: str,
    plan_id: str,
    approval_token: str,
    destination: str,
    overwrite: bool = False,
    profile_path: str | Path | None = None,
) -> dict[str, Any]:
    try:
        session = registry.get_active_session(dataset_id)
        profile_file = str(profile_path) if profile_path else None
        snapshot = _profile_snapshot(session, profile_file or str(DEFAULT_PROFILE_PATH))
        output_path = registry.resolve_output_path(destination, create_parent=True)
        if output_path == session.source_path:
            return {"ok": False, "error_code": "source_overwrite_blocked", "message": "Нельзя перезаписывать исходный CSV."}
        if output_path.exists() and not overwrite:
            return {
                "ok": False,
                "error_code": "output_exists",
                "message": "Файл назначения уже существует. Укажите другое относительное имя или отдельно подтвердите перезапись.",
            }
        plan = store.consume(
            plan_id,
            approval_token,
            dataset_id=dataset_id,
            session_id=session.session_id,
            profile_digest=profile_digest(snapshot),
        )
        result = execute_anonymization_for_session(
            session,
            output_path,
            operations=plan["operations"],
            default_k=plan["default_k"],
            representative=plan["representative"],
            enable_l_diversity=plan["enable_l_diversity"],
            default_l=plan["default_l"],
            l_variant=plan["l_variant"],
            enable_t_closeness=plan["enable_t_closeness"],
            default_t=plan["default_t"],
            **({"profile_path": profile_file} if profile_file else {}),
            overwrite=overwrite,
        )
        privacy = get_privacy_result(registry, dataset_id)
        threshold = minimum_group_size(registry, dataset_id)
        utility = serialize_utility(result.utility, threshold)
        return {
            "ok": True,
            "dataset_id": dataset_id,
            "output_file": str(output_path.relative_to(registry.workspace)).replace("\\", "/"),
            "rows": int(len(result.execution.dataframe)),
            "columns": int(len(result.execution.dataframe.columns)),
            "operations": list(result.execution.operations),
            "affected_columns": list(result.execution.affected_columns),
            "privacy": privacy,
            "utility": utility,
            "source_rows_included": False,
            "source_values_included": False,
        }
    except LookupError:
        return {"ok": False, "error_code": "dataset_not_open", "message": "Сессия закрыта или исходный CSV изменился."}
    except PermissionError:
        return {"ok": False, "error_code": "approval_invalid", "message": "Подтверждение запуска недействительно."}
    except LDiversityViolationError as error:
        report = error.report.get("l_diversity", error.report)
        return {
            "ok": False,
            "error_code": "privacy_check_failed",
            "check": "l_diversity",
            "status": report.get("status", "failed"),
            "failed_check_count": report.get("failed_check_count"),
            "check_count": report.get("check_count"),
            "message": str(error),
            "csv_saved": False,
        }
    except TClosenessViolationError as error:
        report = error.report.get("t_closeness", error.report)
        return {
            "ok": False,
            "error_code": "privacy_check_failed",
            "check": "t_closeness",
            "status": report.get("status", "failed"),
            "t": report.get("t"),
            "failed_check_count": report.get("failed_check_count"),
            "check_count": report.get("check_count"),
            "maximum_distance": report.get("maximum_distance"),
            "message": str(error),
            "csv_saved": False,
        }
    except (OSError, ValueError) as error:
        return {"ok": False, "error_code": "execution_failed", "message": str(error)}
