from collections.abc import Callable, Sequence


def mdav_partition(
    row_indices: Sequence[int],
    k: int,
    centroid_factory: Callable[[list[int]], object],
    distance_to_centroid: Callable[[int, object], float],
    distance_between: Callable[[int, int], float],
) -> list[list[int]]:
    """Детерминированная эвристика MDAV для разбиения строк на группы размера не меньше k."""
    if isinstance(k, bool) or not isinstance(k, int) or k < 2:
        raise ValueError("Параметр k должен быть целым числом не меньше 2.")

    remaining = list(row_indices)
    if len(remaining) < k:
        raise ValueError(
            f"В блоке только {len(remaining)} строк, поэтому достичь k={k} невозможно."
        )

    groups: list[list[int]] = []

    def farthest_from_centroid(indices: list[int]) -> int:
        centroid = centroid_factory(indices)
        return max(
            indices,
            key=lambda index: (distance_to_centroid(index, centroid), -index),
        )

    def nearest_group(anchor: int, candidates: list[int], size: int) -> list[int]:
        ordered = sorted(
            (index for index in candidates if index != anchor),
            key=lambda index: (distance_between(anchor, index), index),
        )
        if len(ordered) < size - 1:
            raise ValueError("Недостаточно строк для формирования группы MDAV.")
        return [anchor, *ordered[: size - 1]]

    while len(remaining) >= 3 * k:
        first_anchor = farthest_from_centroid(remaining)
        first_group = nearest_group(first_anchor, remaining, k)
        first_set = set(first_group)
        after_first = [index for index in remaining if index not in first_set]

        second_anchor = max(
            after_first,
            key=lambda index: (distance_between(first_anchor, index), -index),
        )
        second_group = nearest_group(second_anchor, after_first, k)
        second_set = set(second_group)

        groups.extend([first_group, second_group])
        remaining = [
            index for index in after_first if index not in second_set
        ]

    if len(remaining) >= 2 * k:
        anchor = farthest_from_centroid(remaining)
        first_group = nearest_group(anchor, remaining, k)
        first_set = set(first_group)
        final_group = [index for index in remaining if index not in first_set]
        if len(final_group) < k:
            raise ValueError("MDAV сформировал остаточную группу меньше k.")
        groups.extend([first_group, final_group])
    elif remaining:
        if len(remaining) < k:
            raise ValueError("MDAV оставил остаток меньше k; разбиение невозможно.")
        groups.append(remaining)

    if any(len(group) < k for group in groups):
        raise RuntimeError("Внутренняя ошибка MDAV: создана группа меньше k.")
    if sorted(index for group in groups for index in group) != sorted(row_indices):
        raise RuntimeError("Внутренняя ошибка MDAV: разбиение потеряло или повторило строки.")

    return groups
