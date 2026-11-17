from __future__ import annotations

from dataclasses import dataclass
from secrets import compare_digest, token_urlsafe
from time import monotonic
from typing import Any


@dataclass
class PendingAction:
    action_id: str
    token: str
    dataset_id: str
    session_id: str
    payload: dict[str, Any]
    expires_at: float
    profile_digest: str | None = None


class PendingActionStore:
    """Одноразовые локальные подтверждения для изменяющих MCP-инструментов."""

    def __init__(self, lifetime_seconds: int = 600) -> None:
        self.lifetime_seconds = lifetime_seconds
        self._items: dict[str, PendingAction] = {}

    def create(
        self,
        *,
        dataset_id: str,
        session_id: str,
        payload: dict[str, Any],
        profile_digest: str | None = None,
    ) -> dict[str, str]:
        self._prune()
        action_id = token_urlsafe(18)
        token = token_urlsafe(32)
        self._items[action_id] = PendingAction(
            action_id=action_id,
            token=token,
            dataset_id=dataset_id,
            session_id=session_id,
            payload=payload,
            expires_at=monotonic() + self.lifetime_seconds,
            profile_digest=profile_digest,
        )
        return {"action_id": action_id, "approval_token": token}

    def consume(
        self,
        action_id: str,
        approval_token: str,
        *,
        dataset_id: str,
        session_id: str,
        profile_digest: str | None = None,
    ) -> dict[str, Any]:
        item = self._items.get(action_id)
        if item is None:
            raise ValueError("Действие не найдено, уже использовано или срок подтверждения истёк.")
        if monotonic() > item.expires_at:
            self._items.pop(action_id, None)
            raise ValueError("Срок подтверждения истёк. Подготовьте действие заново.")
        if not compare_digest(item.token, str(approval_token or "")):
            raise PermissionError("Подтверждение действия недействительно.")
        if item.dataset_id != dataset_id or item.session_id != session_id:
            raise ValueError("Активный набор данных изменился. Подготовьте действие заново.")
        if item.profile_digest is not None and item.profile_digest != profile_digest:
            raise ValueError("Профиль атрибутов изменился после предпросмотра. Подготовьте изменения заново.")
        self._items.pop(action_id, None)
        return item.payload

    def _prune(self) -> None:
        now = monotonic()
        expired = [key for key, value in self._items.items() if now > value.expires_at]
        for key in expired:
            self._items.pop(key, None)
