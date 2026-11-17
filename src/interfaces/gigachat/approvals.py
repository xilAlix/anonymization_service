from __future__ import annotations

import json
from typing import Any, Callable


ConfirmInput = Callable[[str], str]


def _yes(value: str) -> bool:
    return value.strip().casefold() in {"y", "yes", "да", "д", "ага"}


def confirm_profile_change(change_id: str, local_diff: dict[str, Any], input_func: ConfirmInput = input) -> bool:
    print("\n" + "=" * 68)
    print("ПОДТВЕРЖДЕНИЕ ИЗМЕНЕНИЯ ПРОФИЛЯ")
    print(f"ID изменения: {change_id}")
    print("Будут сохранены следующие локальные изменения:")
    print(json.dumps(local_diff, ensure_ascii=False, indent=2, default=str))
    print("Изменения не затрагивают исходный CSV и не запускают анонимизацию.")
    return _yes(input_func("Сохранить профиль? [да/Н]: "))


def confirm_anonymization(plan_id: str, plan: Any, destination: str, overwrite: bool, input_func: ConfirmInput = input) -> bool:
    print("\n" + "=" * 68)
    print("ПОДТВЕРЖДЕНИЕ АНОНИМИЗАЦИИ")
    print(f"ID плана: {plan_id}")
    print("Параметры подготовленного плана:")
    print(json.dumps(plan, ensure_ascii=False, indent=2, default=str))
    print(f"Файл результата внутри рабочей папки: {destination}")
    print(f"Перезапись существующего файла: {'ДА' if overwrite else 'НЕТ'}")
    print("Исходный CSV не перезаписывается.")
    return _yes(input_func("Выполнить анонимизацию? [да/Н]: "))


def confirm_metadata_sharing(prompt: str, input_func: ConfirmInput = input) -> bool:
    print("\n" + "=" * 68)
    print("СОГЛАСИЕ НА ПЕРЕДАЧУ ДАННЫХ В GIGACHAT")
    print(prompt)
    return _yes(input_func("Разрешить передачу? [да/Н]: "))
