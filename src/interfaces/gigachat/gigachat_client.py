from __future__ import annotations

import json
import os
import ssl
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from interfaces.gigachat.config import normalize_auth_key

TOKEN_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
DEFAULT_API_BASE = "https://api.giga.chat"
MAX_RESPONSE_BYTES = 8 * 1024 * 1024


class GigaChatAPIError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None, code: int | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code


class GigaChatClient:
    """Минимальный REST-клиент GigaChat с безопасной TLS-проверкой и OAuth-кэшем."""

    def __init__(
        self,
        authorization_key: str,
        scope: str = "GIGACHAT_API_PERS",
        model: str = "",
        api_base: str = DEFAULT_API_BASE,
        timeout: int = 30,
        ca_bundle_file: str | Path | None = None,
    ) -> None:
        if scope not in {"GIGACHAT_API_PERS", "GIGACHAT_API_B2B", "GIGACHAT_API_CORP"}:
            raise ValueError("Неизвестный GigaChat API scope.")
        self.authorization_key = normalize_auth_key(authorization_key)
        self.scope = scope
        self.model = model.strip()
        self.api_base = api_base.rstrip("/")
        self.timeout = timeout
        self.ca_bundle_file = str(ca_bundle_file or os.environ.get("GIGACHAT_CA_BUNDLE_FILE", "")).strip()
        self._ssl_context = self._build_ssl_context(self.ca_bundle_file)
        self._access_token: str | None = None
        self._token_expires_at = 0.0

    @staticmethod
    def _build_ssl_context(ca_bundle_file: str = "") -> ssl.SSLContext:
        # Системные доверенные CA остаются включёнными. Дополнительный сертификат
        # добавляется к ним, а проверка TLS никогда не отключается.
        context = ssl.create_default_context()
        if not ca_bundle_file:
            return context
        path = Path(ca_bundle_file).expanduser()
        if not path.is_file():
            raise ValueError("Файл CA-сертификата не найден. Проверь --ca-bundle или GIGACHAT_CA_BUNDLE_FILE.")
        try:
            raw = path.read_bytes()
            if b"-----BEGIN CERTIFICATE-----" in raw:
                context.load_verify_locations(cadata=raw.decode("ascii"))
            else:
                # Поддерживаем одиночный DER .cer наряду с PEM .crt/.pem.
                pem = ssl.DER_cert_to_PEM_cert(raw)
                context.load_verify_locations(cadata=pem)
        except (OSError, UnicodeError, ssl.SSLError, ValueError):
            raise ValueError("Не удалось загрузить CA-сертификат. Ожидается PEM или DER X.509 сертификат.") from None
        return context

    def _request_json(self, request: Request) -> dict[str, Any]:
        try:
            with urlopen(request, timeout=self.timeout, context=self._ssl_context) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
                if len(raw) > MAX_RESPONSE_BYTES:
                    raise GigaChatAPIError("Ответ GigaChat API превысил допустимый размер.")
                parsed = json.loads(raw.decode("utf-8"))
                if not isinstance(parsed, dict):
                    raise GigaChatAPIError("GigaChat API вернул JSON неожиданного формата.")
                return parsed
        except HTTPError as error:
            payload: dict[str, Any] = {}
            try:
                parsed = json.loads(error.read(16_384).decode("utf-8", errors="replace"))
                if isinstance(parsed, dict):
                    payload = parsed
            except Exception:
                pass
            detail = payload.get("message") or payload.get("error_description") or payload.get("error")
            code_raw = payload.get("code")
            try:
                api_code = int(code_raw) if code_raw is not None else None
            except (TypeError, ValueError):
                api_code = None
            if api_code == 4 or (isinstance(detail, str) and "Can't decode 'Authorization' header" in detail):
                message = (
                    "GigaChat отклонил Authorization Key: формат ключа не распознан. "
                    "Нужен полный Authorization Key из кабинета GigaChat API. "
                    "Проверь ключ или замени сохранённый через запуск host.py --change-key."
                )
            elif api_code == 6:
                message = (
                    "Authorization Key не соответствует выбранному API scope. "
                    "Проверь тип проекта в кабинете GigaChat и параметр --scope."
                )
            elif error.code == 401:
                message = "GigaChat отклонил авторизацию (HTTP 401). Проверь Authorization Key и API scope."
            elif error.code == 422 and isinstance(detail, str) and "does not support functions" in detail.casefold():
                message = (
                    "Выбранная модель не поддерживает Function Calling. Выбери модель генерации диалога "
                    "из /models; Embeddings-модели для чата недоступны."
                )
            elif error.code == 422:
                message = f"GigaChat отклонил формат запроса (HTTP 422). Проверь /validate-functions."
                if isinstance(detail, str) and detail:
                    message += " Детали: " + detail[:240]
            else:
                message = f"GigaChat API вернул HTTP {error.code}."
                if isinstance(detail, str) and detail:
                    message += " " + detail[:240]
            raise GigaChatAPIError(message, status=error.code, code=api_code) from None
        except URLError as error:
            reason = getattr(error, "reason", None)
            if isinstance(reason, ssl.SSLCertVerificationError):
                message = (
                    "Не пройдена проверка TLS-сертификата GigaChat. Установи корневой сертификат НУЦ Минцифры "
                    "в Windows либо укажи CA bundle (PEM/DER) через --ca-bundle или GIGACHAT_CA_BUNDLE_FILE. "
                    "Проверка сертификатов остаётся включённой."
                )
            else:
                message = f"Не удалось подключиться к GigaChat API: {reason or 'ошибка сети'}."
            raise GigaChatAPIError(message) from None
        except ssl.SSLCertVerificationError:
            raise GigaChatAPIError(
                "Не пройдена проверка TLS-сертификата GigaChat. Установи сертификат НУЦ Минцифры "
                "или укажи CA bundle через --ca-bundle. Проверка TLS не отключается."
            ) from None
        except TimeoutError:
            raise GigaChatAPIError(f"Истекло время ожидания GigaChat API ({self.timeout} с).") from None
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
        if expires_value > 10_000_000_000:
            expires_value /= 1000.0
        if expires_value <= time.time():
            expires_value = time.time() + 1800
        self._access_token = token
        self._token_expires_at = expires_value
        return token

    def authenticate(self) -> None:
        """Проверяет TLS и Authorization Key, получая access token до открытия чата."""
        self._get_access_token()

    def list_models(self) -> list[str]:
        """Возвращает фактически доступные аккаунту модели из GET /v1/models."""
        token = self._get_access_token()
        request = Request(
            f"{self.api_base}/v1/models",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            method="GET",
        )
        payload = self._request_json(request)
        data = payload.get("data")
        if not isinstance(data, list):
            raise GigaChatAPIError("GigaChat API вернул некорректный список моделей.")
        models: list[str] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            model_id = item.get("id") or item.get("id_")
            if not isinstance(model_id, str) or not model_id or model_id in models:
                continue
            # /models возвращает также embedding-модели. Они предназначены для
            # /embeddings и не поддерживают /chat/completions с Function Calling.
            if "embedding" in model_id.casefold() or "эмбеддинг" in model_id.casefold():
                continue
            models.append(model_id)
        if not models:
            raise GigaChatAPIError(
                "GigaChat API не вернул доступных моделей генерации диалога для этого ключа и scope."
            )
        return models

    def validate_function(self, function: dict[str, Any]) -> dict[str, Any]:
        """Проверяет одну пользовательскую функцию официальным валидатором GigaChat."""
        if not isinstance(function, dict) or not isinstance(function.get("name"), str):
            raise ValueError("Для проверки GigaChat нужна корректная функция.")
        token = self._get_access_token()
        request = Request(
            f"{self.api_base}/v1/functions/validate",
            data=json.dumps(function, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        return self._request_json(request)

    def chat(self, messages: list[dict[str, Any]], functions: list[dict[str, Any]]) -> dict[str, Any]:
        if not self.model:
            raise GigaChatAPIError("Модель GigaChat не выбрана. Перезапусти Host и выбери модель из списка API.")
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
                if attempt == 0 and error.status == 401:
                    self._access_token = None
                    continue
                raise
        raise GigaChatAPIError("Не удалось выполнить запрос к GigaChat API.")
