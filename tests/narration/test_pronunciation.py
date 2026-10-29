"""Spoken copy, pronunciation targets, the language of a narration and its authored thoughts."""

import copy
import hashlib
import json

import pytest

import ddwg_film.narration.pronunciation as narration_pronunciation
import ddwg_film.repository as repository
from ddwg_film.production import CODES, Edition

OPEN_SPEC = {"display": "OpenSpec", "spoken": "Open Spec", "kind": "english-name"}


@pytest.fixture(scope="module")
def performance() -> dict:
    return repository.read("content/voice-performance.json")


def target(performance: dict, term: str) -> dict:
    targets = performance["pronunciation"]["languages"]["English"]["targets"]
    return next(item for item in targets if item["term"] == term)


def entry(performance: dict, term: str) -> dict:
    entries = performance["pronunciation"]["occurrence_plan"]["entries"]
    return next(item for item in entries if item["target_owner_term"] == term)


def stress(term, **changes):
    return lambda performance: target(performance, term)["lexical_stress"].update(changes)


def test_the_reviewed_contract_passes_its_target_checks(performance):
    narration_pronunciation.validate_pronunciation_targets(performance)


@pytest.mark.parametrize(
    ("tamper", "message"),
    [
        (stress("acquisition", syllable_count=0), "Invalid lexical stress target for acquisition"),
        (stress("acquisition", syllable_count="4"), "Invalid lexical stress target"),
        (stress("acquisition", primary_syllable=5), "Invalid lexical stress target"),
        (stress("acquisition", primary_syllable=None), "Invalid lexical stress target"),
        (stress("acquisition", secondary_syllables=[1, 1]), "Invalid lexical stress target"),
        (stress("acquisition", secondary_syllables=[3]), "Invalid lexical stress target"),
        (stress("acquisition", secondary_syllables="1"), "Invalid lexical stress target"),
        (
            stress("acquisition", arpabet=["AE2", "K", "W", "Z", "IH1", "SH", "AH0", "N"]),
            "Contradictory lexical stress phones for acquisition",
        ),
        (stress("acquisition", primary_syllable=2), "Contradictory lexical stress phones"),
        (stress("acquisition", secondary_syllables=[]), "Contradictory lexical stress phones"),
        (
            lambda performance: target(performance, "record")["lexical_stress"]["verb"][1].update(
                primary_syllable=3
            ),
            "Invalid lexical stress target for record",
        ),
        (
            lambda performance: performance["pronunciation"]["occurrence_plan"].update(count=1),
            "Pronunciation occurrence count differs from its entries",
        ),
        (
            lambda performance: entry(performance, "AI").update(display_word="Ai"),
            "Letter-name target requires an authored label",
        ),
        (
            lambda performance: entry(performance, "AI").update(grammar="noun"),
            "Letter-name target requires an authored label",
        ),
        (
            lambda performance: entry(performance, "use")["target_stress"].update(syllable_count=0),
            "Invalid lexical stress target for use",
        ),
    ],
)
def test_a_contradictory_target_is_refused(performance, tamper, message):
    changed = copy.deepcopy(performance)
    tamper(changed)
    with pytest.raises(ValueError, match=message):
        narration_pronunciation.validate_pronunciation_targets(changed)


@pytest.mark.parametrize("code", CODES)
def test_the_reviewed_contract_derives_every_spoken_text_of_the_script(code):
    edition = Edition(code)
    script = repository.read(edition.script)
    contract, _ = narration_pronunciation.pronunciation_contract(script, edition.language)
    for segment in script["segments"]:
        assert (
            narration_pronunciation.pronunciation_text(segment, contract) == segment["spoken_text"]
        )


@pytest.mark.parametrize(
    ("rule", "text", "spoken"),
    [
        (
            {"display": "重新", "spoken": "从新", "kind": "homophone"},
            "请重新判断。",
            "请从新判断。",
        ),
        (OPEN_SPEC, "Use openspec, not OpenSpecs.", "Use Open Spec, not OpenSpecs."),
        (OPEN_SPEC, "保存在OpenSpec中。", "保存在Open Spec中。"),
    ],
)
def test_a_normalization_rule_maps_whole_words(rule, text, spoken):
    contract = {"normalization": [rule]}
    assert narration_pronunciation.pronunciation_text({"text": text}, contract) == spoken


@pytest.mark.parametrize(
    ("rule", "message"),
    [
        ({"display": "", "spoken": "x", "kind": "homophone"}, "requires complete words"),
        ({"display": "行", "spoken": "航", "kind": "homophone"}, "word-scoped and 1:1"),
        ({"display": "重新", "spoken": "从新的", "kind": "homophone"}, "word-scoped and 1:1"),
        ({"display": "a", "spoken": "b", "kind": "phoneme"}, "Unknown pronunciation"),
    ],
)
def test_a_malformed_normalization_rule_is_refused(rule, message):
    with pytest.raises(ValueError, match=message):
        narration_pronunciation.pronunciation_text(
            {"text": "请重新判断。"}, {"normalization": [rule]}
        )


def test_stale_spoken_copy_is_refused():
    section = {"text": "保存在OpenSpec中。", "spoken_text": "保存在OpenSpec中。"}
    with pytest.raises(ValueError, match="Speech text differs from the declared pronunciation"):
        narration_pronunciation.pronunciation_text(section, {"normalization": [OPEN_SPEC]})


def test_a_script_declares_its_pronunciation_contract(tmp_path, monkeypatch):
    monkeypatch.setattr(repository, "ROOT", tmp_path)
    contract = {"pronunciation": {"languages": {"English": {"normalization": [OPEN_SPEC]}}}}
    repository.write("contract.json", contract)
    script = {"pronunciation_contract": "contract.json"}
    assert narration_pronunciation.pronunciation_contract(script, "English") == (
        {"normalization": [OPEN_SPEC]},
        hashlib.sha256((tmp_path / "contract.json").read_bytes()).hexdigest(),
    )
    with pytest.raises(ValueError, match="must declare its pronunciation contract"):
        narration_pronunciation.pronunciation_contract({}, "English")


def test_a_contract_with_a_contradictory_target_is_not_read(tmp_path, monkeypatch):
    monkeypatch.setattr(repository, "ROOT", tmp_path)
    targets = [{"term": "data", "lexical_stress": {"syllable_count": 0}}]
    contract = {"pronunciation": {"languages": {"English": {"targets": targets}}}}
    (tmp_path / "contract.json").write_text(json.dumps(contract))
    with pytest.raises(ValueError, match="Invalid lexical stress target for data"):
        narration_pronunciation.pronunciation_contract(
            {"pronunciation_contract": "contract.json"}, "English"
        )


@pytest.mark.parametrize("code", CODES)
def test_each_edition_narrates_in_its_cast_language(code):
    edition = Edition(code)
    script, cast = repository.read(edition.script), repository.read(edition.cast)
    assert narration_pronunciation.validate_language_reference(script, cast) == edition.language


ENGLISH = {
    "language": "English",
    "segments": [{"id": "01", "text": "A thought.", "spoken_text": "A thought."}],
}
ENGLISH_CAST = {
    "narration_language": "English",
    "reference_language": "English",
    "reference_text": "A reference thought.",
}
CHINESE = {"language": "Chinese", "segments": [{"id": "01", "text": "先核验。"}]}
CHINESE_CAST = {
    "narration_language": "Chinese",
    "reference_language": "Chinese",
    "reference_text": "看清事实。",
}


@pytest.mark.parametrize(
    ("narration", "cast", "message"),
    [
        ({**CHINESE, "language": None}, ENGLISH_CAST, "Mandarin clauses require Chinese"),
        (ENGLISH, {**ENGLISH_CAST, "narration_language": "Chinese"}, "Declared narration language"),
        (
            {"segments": [{"id": "01", "text": "A thought.", "language": "Chinese"}]},
            ENGLISH_CAST,
            "Every complete clause must match",
        ),
        (ENGLISH, {**ENGLISH_CAST, "reference_text": "看清事实。"}, "qualified English reference"),
        (ENGLISH, {**ENGLISH_CAST, "reference_language": "Chinese"}, "qualified English reference"),
        (
            ENGLISH,
            {key: value for key, value in ENGLISH_CAST.items() if key != "reference_language"},
            "qualified English reference",
        ),
        (CHINESE, {**CHINESE_CAST, "reference_language": "English"}, "Chinese reference"),
        (CHINESE, {**CHINESE_CAST, "reference_text": "A reference."}, "Chinese reference"),
    ],
)
def test_a_narration_and_reference_in_different_languages_are_refused(narration, cast, message):
    with pytest.raises(ValueError, match=message):
        narration_pronunciation.validate_language_reference(narration, cast)


def test_authored_utterance_groups_refuse_source_or_pronunciation_drift():
    section = {
        "text": "OpenSpec 保存意图。然后核验事实。",
        "spoken_text": "Open Spec 保存意图。然后核验事实。",
        "utterance_groups": ["OpenSpec 保存意图。", "然后核验事实。"],
    }
    contract = {"normalization": [OPEN_SPEC]}
    plan = narration_pronunciation.native_utterance_plan(section, contract)
    assert plan == [
        {"text": "OpenSpec 保存意图。", "spoken_text": "Open Spec 保存意图。"},
        {"text": "然后核验事实。", "spoken_text": "然后核验事实。"},
    ]
    for groups in (
        None,
        ["OpenSpec 保存意图。", "然后核验。"],
        ["Open", "Spec 保存意图。然后核验事实。"],
    ):
        with pytest.raises(ValueError, match="exact text and complete thought endings"):
            narration_pronunciation.native_utterance_plan(
                {**section, "utterance_groups": groups}, contract
            )
    with pytest.raises(ValueError, match="change the declared speech mapping"):
        narration_pronunciation.native_utterance_plan(section, {"normalization": []})
