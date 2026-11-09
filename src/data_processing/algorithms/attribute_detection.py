import re
from collections.abc import Iterable
from itertools import islice


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


def _normalize_name(value: str) -> tuple[str, ...]:
    normalized = re.sub(r"[^\w]+", "_", value.casefold(), flags=re.UNICODE).strip("_")
    return tuple(part for part in normalized.split("_") if part)


def _contains_phrase(tokens: tuple[str, ...], phrase: tuple[str, ...]) -> bool:
    width = len(phrase)
    return any(
        tokens[index:index + width] == phrase
        for index in range(len(tokens) - width + 1)
    )


def _value_pattern_suggestion(values: list[str]) -> dict | None:
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
    if email_matches / len(values) >= 0.8:
        return {
            "role": "direct_identifier",
            "confidence": "высокая",
            "reasons": [
                f"Формат электронной почты обнаружен в {email_matches} из {len(values)} проверенных значений."
            ],
        }
    if phone_matches / len(values) >= 0.8:
        return {
            "role": "direct_identifier",
            "confidence": "средняя",
            "reasons": [
                f"Значения похожи на телефонные номера ({phone_matches} из {len(values)}); требуется ручная проверка."
            ],
        }
    return None


def suggest_attribute_roles(attribute: str, values: Iterable[object]) -> list[dict]:
    """Возвращает эвристические предложения в виде обычных словарей и списков."""
    tokens = _normalize_name(attribute)
    token_set = set(tokens)
    suggestions: list[dict] = []
    sample = [
        str(value)
        for value in islice((item for item in values if item is not None), 1000)
    ]

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

    value_suggestion = _value_pattern_suggestion(sample)
    if value_suggestion is not None:
        direct_reasons.extend(value_suggestion["reasons"])

    if direct_reasons:
        strong_name_match = bool(
            direct_name_matches
            & {
                "email", "phone", "telephone", "inn", "snils", "passport",
                "фио", "телефон", "инн", "снилс", "паспорт",
            }
        )
        confidence = "высокая" if (
            strong_name_match
            or (value_suggestion is not None and value_suggestion["confidence"] == "высокая")
        ) else "средняя"
        suggestions.append({
            "role": "direct_identifier",
            "confidence": confidence,
            "reasons": direct_reasons,
        })

    quasi_matches = sorted(token_set & _QUASI_NAME_TOKENS)
    if quasi_matches:
        suggestions.append({
            "role": "quasi_identifier",
            "confidence": "средняя",
            "reasons": [
                "Название столбца содержит признак, который может участвовать в повторной идентификации: "
                + ", ".join(quasi_matches) + "."
            ],
        })

    sensitive_matches = sorted(token_set & _SENSITIVE_NAME_TOKENS)
    if sensitive_matches:
        suggestions.append({
            "role": "sensitive_attribute",
            "confidence": "средняя",
            "reasons": [
                "Название столбца указывает на потенциально конфиденциальное содержание: "
                + ", ".join(sensitive_matches) + "."
            ],
        })

    return suggestions
