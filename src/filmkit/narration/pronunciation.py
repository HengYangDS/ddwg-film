"""Spoken text, pronunciation targets, narration language and the thoughts each segment speaks.

One reviewed performance contract per script owns how display text is spoken: its
normalization rules derive every spoken text, and its English lexical stress targets must agree
with their ARPAbet phones before any speech provider loads.
"""

from __future__ import annotations

import json
import re

import filmkit.repository as repository
from filmkit.narration.thought_groups import authored_groups

HAN = r"[\u3400-\u4dbf\u4e00-\u9fff]"


def pronunciation_contract(script: dict, language: str) -> tuple[dict, str]:
    """The script's pronunciation contract for one language and the contract file's SHA-256.

    The contract's lexical stress targets are checked before it is used.
    """
    path = script.get("pronunciation_contract")
    if not path:
        msg = "A script must declare its pronunciation contract"
        raise ValueError(msg)
    raw = (repository.ROOT / path).read_bytes()
    performance = json.loads(raw)
    validate_pronunciation_targets(performance)
    return performance["pronunciation"]["languages"][language], repository.content_sha(raw)


def validate_pronunciation_targets(performance: dict) -> None:
    """Reject contradictory lexical stress before loading a speech provider."""
    targets = performance["pronunciation"]["languages"].get("English", {}).get("targets", [])
    for target in targets:
        _check_stress(target.get("lexical_stress", {}), target["term"])
    _check_occurrence_plan(performance["pronunciation"].get("occurrence_plan"), targets)


def _check_stress(value: object, term: str) -> None:
    """Check each stress target in a value: one target, its variants or its senses."""
    if isinstance(value, list):
        for member in value:
            _check_stress(member, term)
        return
    if not isinstance(value, dict):
        return
    if "syllable_count" in value:
        _check_syllables(value, term)
        if "arpabet" in value:
            _check_arpabet(value, term)
    for member in value.values():
        _check_stress(member, term)


def _check_syllables(value: dict, term: str) -> None:
    """Check that the stressed syllables are distinct places within the syllable count."""
    count = value["syllable_count"]
    primary = value.get("primary_syllable")
    secondary = value.get("secondary_syllables", [])

    def place(index: object) -> bool:
        return type(index) is int and 1 <= index <= count

    if (
        type(count) is not int
        or count < 1
        or (count > 1 and not place(primary))
        or (count == 1 and primary is not None and not place(primary))
        or not isinstance(secondary, list)
        or any(not place(index) for index in secondary)
        or len(set(secondary)) != len(secondary)
        or primary in secondary
    ):
        msg = f"Invalid lexical stress target for {term}"
        raise ValueError(msg)


def _check_arpabet(value: dict, term: str) -> None:
    """Check that the phones' vowels and stress marks agree with the declared syllables."""
    count = value["syllable_count"]
    vowels = [phone for phone in value["arpabet"] if phone[-1:].isdigit()]
    primary = [index for index, phone in enumerate(vowels, 1) if phone.endswith("1")]
    secondary = [index for index, phone in enumerate(vowels, 1) if phone.endswith("2")]
    if (
        len(vowels) != count
        or (count > 1 and primary != [value.get("primary_syllable")])
        or secondary != value.get("secondary_syllables", [])
    ):
        msg = f"Contradictory lexical stress phones for {term}"
        raise ValueError(msg)


def _check_occurrence_plan(occurrence_plan: dict | None, targets: list[dict]) -> None:
    """Check the planned occurrences: their count, letter-name labels and English stress."""
    if occurrence_plan is None:
        return
    entries = occurrence_plan["entries"]
    if occurrence_plan["count"] != len(entries):
        msg = "Pronunciation occurrence count differs from its entries"
        raise ValueError(msg)
    target_by_term = {target["term"]: target for target in targets}
    for entry in entries:
        term = entry["target_owner_term"]
        target = target_by_term.get(term)
        if (
            target
            and target.get("kind") == "letter-name"
            and (entry["display_word"] != term or entry.get("grammar") != "letter-name")
        ):
            msg = "Letter-name target requires an authored label"
            raise ValueError(msg)
        if entry["locale"] == "en":
            _check_stress(entry["target_stress"], term)


def pronunciation_text(section: dict, contract: dict) -> str:
    """Derive speech copy from the single reviewed performance contract."""
    derived = section["text"]
    for rule in contract["normalization"]:
        derived = _normalized(derived, rule)
    if section.get("spoken_text", derived) != derived:
        msg = "Speech text differs from the declared pronunciation mapping"
        raise ValueError(msg)
    return derived


def _normalized(text: str, rule: dict) -> str:
    """Apply one normalization rule: a 1:1 homophone, or an English name as a whole word."""
    display, spoken = rule["display"], rule["spoken"]
    if not display or not spoken:
        msg = "Pronunciation normalization requires complete words"
        raise ValueError(msg)
    if rule["kind"] == "homophone":
        if len(display) < 2 or len(display) != len(spoken):
            msg = "Homophone normalization must be word-scoped and 1:1"
            raise ValueError(msg)
        return text.replace(display, spoken)
    if rule["kind"] == "english-name":
        return re.sub(
            rf"(?<![A-Za-z]){re.escape(display)}(?![A-Za-z])",
            lambda _match: spoken,
            text,
            flags=re.IGNORECASE,
        )
    msg = "Unknown pronunciation normalization kind"
    raise ValueError(msg)


def validate_language_reference(narration: dict, cast: dict) -> str:
    """Bind the narration language to its clauses and its reference, independent of path.

    Returns:
        The narration language.
    """
    segments = narration["segments"]
    has_mandarin = any(
        re.search(HAN, item[field])
        for item in segments
        for field in ("text", "spoken_text")
        if field in item
    )
    language = cast.get("narration_language", narration.get("language", "auto"))
    declared = narration.get("language")
    if has_mandarin and language != "Chinese":
        msg = "Mandarin clauses require Chinese narration language"
        raise ValueError(msg)
    if declared and declared != language:
        msg = "Declared narration language differs from selected conditioning"
        raise ValueError(msg)
    if any(item.get("language", language) != language for item in segments):
        msg = "Every complete clause must match the selected language"
        raise ValueError(msg)
    transcript = cast.get("reference_text", "")
    reference_language = cast.get("reference_language")
    if language == "English" and (re.search(HAN, transcript) or reference_language != "English"):
        msg = "English narration requires a qualified English reference"
        raise ValueError(msg)
    if language == "Chinese" and (
        reference_language not in (None, "Chinese")
        or (transcript and not re.search(HAN, transcript))
    ):
        msg = "Mandarin narration requires a Chinese reference"
        raise ValueError(msg)
    return language


def native_utterance_plan(section: dict, contract: dict) -> list[dict]:
    """The section's authored thoughts and their spoken text, before any model or write."""
    plans = [
        {"text": text, "spoken_text": pronunciation_text({"text": text}, contract)}
        for text in authored_groups(section)
    ]
    if "".join(item["spoken_text"] for item in plans) != section["spoken_text"]:
        msg = "Utterance groups change the declared speech mapping"
        raise ValueError(msg)
    return plans
