from dataclasses import dataclass
import re
from typing import Iterable

import pandas as pd


ROLE_LABELS = {
    "direct_identifier": "Прямой идентификатор",
    "quasi_identifier": "Квази-идентификатор",
    "sensitive_attribute": "Конфиденциальный атрибут",
    "analytical_attribute": "Аналитический атрибут",
}

_DIRECT_NAME_TOKENS = {
    "identifier", "uuid", "guid", "inn", "snils", "passport",
    "phone", "telephone", "mobile", "email", "fio", "ssn",
    "address", "идентификатор", "инн", "снилс", "паспорт",
    "телефон", "мобильный", "почта", "фио", "адрес",
}
_PERSON_ENTITY_TOKENS = {
    "customer", "client", "user", "person", "patient", "employee", "buyer",
    "клиент", "пользователь", "пациент", "сотрудник", "покупатель",
}
_DIRECT_PHRASES = {
    ("full", "name"), ("first", "name"), ("last", "name"),
    ("person", "name"), ("полное", "имя"), ("фамилия",),
}
_QUASI_NAME_TOKENS = {
    "age", "birth", "birthday", "dob", "date_of_birth", "postcode",
    "postal", "zip", "district", "region", "city", "state", "county",
    "gender", "sex", "occupation", "education", "marital_status",
    "возраст", "рождение", "дата_рождения", "район", "регион", "город",
    "область", "индекс", "пол", "профессия", "образование",
    "семейное_положение",
}
_SENSITIVE_NAME_TOKENS = {
    "salary", "income", "wage", "earnings", "debt", "credit", "diagnosis",
    "disease", "health", "medical", "medication", "treatment", "religion",
    "political", "sexual_orientation", "biometric", "disability", "criminal",
    "доход", "зарплата", "оклад", "заработок", "долг", "кредит", "диагноз",
    "заболевание", "здоровье", "медицина", "лекарство", "лечение", "религия",
    "политика", "ориентация", "биометрия", "инвалидность", "судимость",
}
_EMAIL_PATTERN = re.compile(
    r"^[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Z0-9.-]+\.[A-Z]{2,}$",
    re.I,
)
_PHONE_PATTERN = re.compile(r"^\+?[\d\s()\-]{8,20}$")


@dataclass(frozen=True)
class RoleSuggestion:
    role: str
    confidence: str
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class AttributeClassificationResult:
    attribute: str
    pandas_type: str
    suggestions: tuple[RoleSuggestion, ...]
    assigned_roles: tuple[str, ...]
    assignment_source: str


def _normalize_name(value: str) -> tuple[str, ...]:
    normalized = re.sub(r"[^\w]+", "_", value.casefold(), flags=re.UNICODE).strip("_")
    return tuple(part for part in normalized.split("_") if part)


def _contains_phrase(tokens: tuple[str, ...], phrase: tuple[str, ...]) -> bool:
    width = len(phrase)
    return any(tokens[index:index + width] == phrase for index in range(len(tokens) - width + 1))


def _value_pattern_suggestion(series: pd.Series) -> RoleSuggestion | None:
    values = series.dropna().astype(str).head(1000)
    if len(values) < 3:
        return None

    email_matches = sum(bool(_EMAIL_PATTERN.fullmatch(value.strip())) for value in values)

    def looks_like_formatted_phone(value: str) -> bool:
        value = value.strip()
        digits = re.sub(r"\D", "", value)
        has_formatting = bool(re.search(r"[+()\-\s]", value))
        return (
            bool(_PHONE_PATTERN.fullmatch(value))
            and 10 <= len(digits) <= 15
            and has_formatting
        )

    phone_matches = sum(looks_like_formatted_phone(value) for value in values)
    email_ratio = email_matches / len(values)
    phone_ratio = phone_matches / len(values)

    if email_ratio >= 0.8:
        return RoleSuggestion(
            role="direct_identifier",
            confidence="высокая",
            reasons=(
                f"Формат электронной почты обнаружен в {email_matches} из {len(values)} проверенных значений.",
            ),
        )
    if phone_ratio >= 0.8:
        return RoleSuggestion(
            role="direct_identifier",
            confidence="средняя",
            reasons=(
                f"Значения похожи на телефонные номера ({phone_matches} из {len(values)}); требуется ручная проверка.",
            ),
        )
    return None


def _suggest_roles(attribute: str, series: pd.Series) -> tuple[RoleSuggestion, ...]:
    tokens = _normalize_name(attribute)
    token_set = set(tokens)
    suggestions: list[RoleSuggestion] = []

    direct_reasons: list[str] = []
    direct_name_matches = token_set & _DIRECT_NAME_TOKENS
    if {"tax", "id"}.issubset(token_set) or {"national", "id"}.issubset(token_set):
        direct_name_matches = direct_name_matches | {"идентификатор"}
    if direct_name_matches:
        direct_reasons.append(
            "Название столбца содержит признак идентификатора: "
            + ", ".join(sorted(direct_name_matches))
            + "."
        )
    has_id_token = bool(token_set & {"id", "код", "номер"})
    if has_id_token and (token_set & _PERSON_ENTITY_TOKENS or tokens in {("id",), ("код",)}):
        direct_reasons.append(
            "Название столбца похоже на устойчивый идентификатор субъекта или записи."
        )
    if tokens in {("name",), ("имя",)} or any(
        _contains_phrase(tokens, phrase) for phrase in _DIRECT_PHRASES
    ):
        direct_reasons.append("Название столбца похоже на персональное имя.")
    value_suggestion = _value_pattern_suggestion(series)
    if value_suggestion is not None:
        direct_reasons.extend(value_suggestion.reasons)

    if direct_reasons:
        confidence = "высокая" if (
            direct_name_matches
            & {
                "email", "phone", "telephone", "inn", "snils", "passport",
                "фио", "телефон", "инн", "снилс", "паспорт",
            }
            or (value_suggestion is not None and value_suggestion.confidence == "высокая")
        ) else "средняя"
        suggestions.append(
            RoleSuggestion("direct_identifier", confidence, tuple(direct_reasons))
        )

    quasi_matches = sorted(token_set & _QUASI_NAME_TOKENS)
    if quasi_matches:
        suggestions.append(
            RoleSuggestion(
                "quasi_identifier",
                "средняя",
                ("Название столбца содержит признак, который может участвовать в повторной идентификации: "
                 + ", ".join(quasi_matches) + ".",),
            )
        )

    sensitive_matches = sorted(token_set & _SENSITIVE_NAME_TOKENS)
    if sensitive_matches:
        suggestions.append(
            RoleSuggestion(
                "sensitive_attribute",
                "средняя",
                ("Название столбца указывает на потенциально конфиденциальное содержание: "
                 + ", ".join(sensitive_matches) + ".",),
            )
        )

    return tuple(suggestions)


def classify_attributes(
    dataframe: pd.DataFrame,
    manual_overrides: dict[str, list[str]] | None = None,
) -> list[AttributeClassificationResult]:
    overrides = manual_overrides or {}
    results: list[AttributeClassificationResult] = []

    for column, series in dataframe.items():
        attribute = str(column)
        suggestions = _suggest_roles(attribute, series)
        if attribute in overrides:
            assigned_roles = tuple(overrides[attribute])
            source = "Вручную"
        else:
            assigned_roles = tuple(suggestion.role for suggestion in suggestions)
            source = "Автоматически"

        results.append(
            AttributeClassificationResult(
                attribute=attribute,
                pandas_type=str(series.dtype),
                suggestions=suggestions,
                assigned_roles=assigned_roles,
                assignment_source=source,
            )
        )

    return results


def role_labels(roles: Iterable[str]) -> str:
    labels = [ROLE_LABELS[role] for role in roles if role in ROLE_LABELS]
    return ", ".join(labels) if labels else "Не назначены"
