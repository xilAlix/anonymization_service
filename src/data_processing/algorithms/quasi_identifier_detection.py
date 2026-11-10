import re
from collections.abc import Iterable


def _normalize_tokens(value: str) -> tuple[str, ...]:
    separated = re.sub(
        r"(?<=[a-zа-яё0-9])(?=[A-ZА-ЯЁ])",
        " ",
        value,
        flags=re.UNICODE,
    )
    normalized = re.sub(r"[\W_]+", " ", separated.casefold(), flags=re.UNICODE)
    return tuple(part for part in normalized.split() if part)


def _contains_phrase(tokens: tuple[str, ...], phrase: tuple[str, ...]) -> bool:
    if not phrase or len(phrase) > len(tokens):
        return False
    width = len(phrase)
    return any(tokens[index:index + width] == phrase for index in range(len(tokens) - width + 1))


def _match_aliases(attribute: str, aliases: Iterable[str]) -> list[str]:
    tokens = _normalize_tokens(attribute)
    matched: list[str] = []
    for alias in aliases:
        alias_tokens = _normalize_tokens(alias)
        if _contains_phrase(tokens, alias_tokens):
            matched.append(alias)
    return matched


def _confidence(name_match: bool, value_signal: bool) -> str:
    if name_match and value_signal:
        return "высокая"
    if name_match:
        return "средняя"
    return "низкая"


def detect_quasi_identifier_groups(
    column_profiles: list[dict],
    knowledge_catalog: dict,
) -> list[dict]:
    """Формирует объяснимые гипотезы о наборах фоновой информации для QI."""
    groups: list[dict] = []

    for family in knowledge_catalog.get("families", []):
        group_attributes: list[str] = []
        evidence_by_attribute: dict[str, dict] = {}
        group_confidences: list[str] = []

        for profile in column_profiles:
            attribute = str(profile.get("attribute", ""))
            if not attribute:
                continue

            concept_matches: list[dict] = []
            for concept in family.get("concepts", []):
                aliases = concept.get("aliases", [])
                matched_aliases = _match_aliases(attribute, aliases)
                if matched_aliases:
                    concept_matches.append({
                        "concept": concept.get("id", "unknown"),
                        "aliases": matched_aliases,
                        "note": concept.get("evidence_note", ""),
                    })

            value_signal_matches: list[dict] = []
            for signature in knowledge_catalog.get("value_signatures", []):
                if family.get("id") not in signature.get("family_ids", []):
                    continue
                sample_count = int(profile.get("sample_count", 0) or 0)
                observed = float(profile.get(signature.get("profile_field", ""), 0.0) or 0.0)
                if (
                    sample_count >= int(signature.get("minimum_sample", 0))
                    and observed >= float(signature.get("threshold", 1.0))
                ):
                    value_signal_matches.append({
                        "concept": signature.get("concept_id", "unknown"),
                        "note": signature.get("note", ""),
                    })

            known_concepts = {item["concept"] for item in concept_matches}
            for value_match in value_signal_matches:
                if value_match["concept"] not in known_concepts:
                    concept_matches.append({
                        "concept": value_match["concept"],
                        "aliases": [],
                        "note": value_match["note"],
                    })

            name_match = any(item["aliases"] for item in concept_matches)
            value_signal = bool(value_signal_matches)
            if not concept_matches:
                continue

            unique_ratio = profile.get("unique_ratio")
            if unique_ratio is not None:
                unique_ratio = float(unique_ratio)
            confidence = _confidence(name_match, value_signal)
            reasons: list[str] = []
            aliases = sorted({
                alias
                for match in concept_matches
                for alias in match["aliases"]
            })
            if aliases:
                reasons.append(
                    "Название столбца семантически совпало с признаками: "
                    + ", ".join(aliases)
                    + "."
                )
            for match in concept_matches:
                if match["note"]:
                    reasons.append(match["note"])
            if unique_ratio is not None:
                reasons.append(
                    f"В столбце {unique_ratio:.1%} уникальных непустых значений. "
                    "Это характеристика различимости внутри файла, а не доказательство внешней доступности."
                )

            group_attributes.append(attribute)
            evidence_by_attribute[attribute] = {
                "confidence": confidence,
                "concepts": [item["concept"] for item in concept_matches],
                "reasons": reasons,
            }
            group_confidences.append(confidence)

        if not group_attributes:
            continue

        confidence_order = {"низкая": 0, "средняя": 1, "высокая": 2}
        group_confidence = min(
            group_confidences,
            key=lambda value: confidence_order.get(value, 0),
        )
        groups.append({
            "id": family["id"],
            "name": family.get("default_name", family["id"]),
            "description": family.get("description", ""),
            "attributes": group_attributes,
            "source": "automatic",
            "confidence": group_confidence,
            "external_source_families": family.get("external_source_families", []),
            "attribute_evidence": evidence_by_attribute,
            "reasons": [
                "Группа сформирована по семантическим признакам и профилю столбцов. "
                "Это гипотеза о возможном источнике фоновой информации, а не подтверждение существования или доступности такого источника."
            ],
        })

    return groups
