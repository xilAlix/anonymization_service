from collections.abc import Callable, Iterable


def tokenize_values(
    values: Iterable[object],
    token_factory: Callable[[], str],
) -> list[object]:
    """Заменяет повторяющиеся значения одинаковыми токенами в пределах одного набора."""
    mapping: dict[tuple[str, object], str] = {}
    used_tokens: set[str] = set()
    result: list[object] = []

    for value in values:
        if value is None:
            result.append(None)
            continue

        try:
            key = (type(value).__qualname__, value)
            hash(key)
        except TypeError as error:
            raise TypeError("Токенизация поддерживает только скалярные значения.") from error

        if key not in mapping:
            token = token_factory()
            if not isinstance(token, str) or not token:
                raise ValueError("Генератор токенов должен возвращать непустую строку.")
            if token in used_tokens:
                raise ValueError("Генератор токенов вернул повторяющееся значение.")
            mapping[key] = token
            used_tokens.add(token)

        result.append(mapping[key])

    return result
