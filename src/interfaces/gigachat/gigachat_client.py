from __future__ import annotations

import json
import time
import uuid
from email.message import Message
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

TOKEN_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
DEFAULT_API_BASE = "https://api.giga.chat"


class GigaChatAPIError(RuntimeError):
    pass


class GigaChatClient:
    """Минимальный REST-клиент GigaChat с кэшированием 30-минутного access token."""

    def __init__(
        self,
        authorization_key: str,
        scope: str = "GIGACHAT_API_PERS",
        model: str = "GigaChat-2-Pro",
        api_base: str = DEFAULT_API_BASE,
        timeout: int = 45,
    ) -> None:
        if scope not in {"GIGACHAT_API_PERS", "GIGACHAT_API_B2B", "GIGACHAT_API_CORP"}:
            raise ValueError("Неизвестный GigaChat API scope.")
        self.authorization_key = authorization_key
        self.scope = scope
        self.model = model
        self.api_base = api_base.rstrip("/")
        self.timeout = timeout
        self._access_token: str | None = None
        self._token_expires_at = 0.0

    def _request_json(self, request: Request) -> dict[str, Any]:
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read(8 * 1024 * 1024 + 1)
                if len(raw) > 8 * 1024 * 1024:
                    raise GigaChatAPIError("Ответ GigaChat API превысил допустимый размер.")
                return json.loads(raw.decode("utf-8"))
        except HTTPError as error:
            message = f"GigaChat API вернул HTTP {error.code}."
            try:
                payload = json.loads(error.read(16_384).decode("utf-8", errors="replace"))
                detail = payload.get("message") or payload.get("error_description") or payload.get("error")
                if isinstance(detail, str) and detail:
                    message += " " + detail[:300]
            except Exception:
                pass
            raise GigaChatAPIError(message) from None
        except URLError as error:
            reason = getattr(error, "reason", None)
            raise GigaChatAPIError(f"Не удалось подключиться к GigaChat API: {reason or 'ошибка сети'}.") from None
        except TimeoutError:
            raise GigaChatAPIError("Истекло время ожидания ответа GigaChat API.") from None
        except (UnicodeError, json.JSONDecodeError):
            raise GigaChatAPIError("GigaChat API вернул некорректный JSON.") from None

    def _get_access_token(self, force_refresh: bool = False) -> str:
        if not force_refresh and self._access_token and time.time() < self._token_expires_at - 60:
            return self._access_token
        headers = {
            "Authorization": f"Basic {self.authorization_key}",
            "RqUID": str(uuid.uuid4()),
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        }
        body = urlencode({"scope": self.scope}).encode("ascii")
        request = Request(TOKEN_URL, data=body, headers=headers, method="POST")
        payload = self._request_json(request)
        token = payload.get("access_token")
        expires_at = payload.get("expires_at")
        if not isinstance(token, str) or not token:
            raise GigaChatAPIError("GigaChat API не вернул access_token.")
        try:
            expires_value = float(expires_at)
        except (TypeError, ValueError):
            expires_value = time.time() + 1800
        # API normally returns Unix seconds; tolerate millisecond timestamps too.
        if expires_value > 10_000_000_000:
            expires_value /= 1000.0
        if expires_value <= time.time():
            expires_value = time.time() + 1800
        self._access_token = token
        self._token_expires_at = expires_value
        return token

    def chat(self, messages: list[dict[str, Any]], functions: list[dict[str, Any]]) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "messages": messages,
            "functions": functions,
            "function_call": "auto",
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        for attempt in range(2):
            token = self._get_access_token(force_refresh=attempt == 1)
            request = Request(
                f"{self.api_base}/v1/chat/completions",
                data=body,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                method="POST",
            )
            try:
                response = self._request_json(request)
                choices = response.get("choices")
                if not isinstance(choices, list) or not choices:
                    raise GigaChatAPIError("GigaChat API вернул пустой список choices.")
                message = choices[0].get("message")
                if not isinstance(message, dict):
                    raise GigaChatAPIError("GigaChat API вернул некорректное сообщение.")
                return {"message": message, "finish_reason": choices[0].get("finish_reason")}
            except GigaChatAPIError as error:
                # A 401 is the only condition where one refresh/retry is useful.
                if attempt == 0 and "HTTP 401" in str(error):
                    self._access_token = None
                    continue
                raise
        raise GigaChatAPIError("Не удалось выполнить запрос к GigaChat API.")
