"""The cast's retakes: segment and thought seeds, bound to the exact text they narrate."""

import copy
import hashlib

import pytest

import ddwg_film.narration.retakes as narration_retakes


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


PLANS = [
    {"text": "先核验。", "spoken_text": "先核验。"},
    {"text": "再说明。", "spoken_text": "再说明。"},
]


def test_a_thought_retake_seeds_only_its_bound_thought():
    retaken = narration_retakes.apply_retakes(
        PLANS, {"2": {"seed": 7, "text_sha256": sha256("再说明。")}}, 3
    )
    assert retaken == [PLANS[0], {**PLANS[1], "seed": 7}]
    assert "seed" not in PLANS[1]


@pytest.mark.parametrize(
    ("takes", "message"),
    [
        ({"3": {"seed": 7, "text_sha256": sha256("再说明。")}}, "index"),
        ({"0": {"seed": 7, "text_sha256": sha256("再说明。")}}, "index"),
        ({"2": {"seed": 3, "text_sha256": sha256("再说明。")}}, "declared thought"),
        ({"2": {"seed": 7, "text_sha256": "0" * 64}}, "declared thought"),
        (
            {"2": {"seed": 7, "text_sha256": sha256("再说明。"), "temperature": 1}},
            "declared thought",
        ),
    ],
)
def test_an_unbound_or_redundant_retake_is_refused(takes, message):
    with pytest.raises(ValueError, match=message):
        narration_retakes.apply_retakes(PLANS, takes, 3)


RUN_ON = {"spoken_text": "最后验收。", "cut_sample": 52800}


def test_a_run_on_retake_reads_its_thought_on_into_the_words_that_follow():
    retaken = narration_retakes.apply_retakes(
        PLANS, {"2": {"seed": 7, "text_sha256": sha256("再说明。"), "run_on": RUN_ON}}, 3
    )
    assert retaken == [PLANS[0], {**PLANS[1], "seed": 7, "run_on": RUN_ON}]
    assert retaken[1]["run_on"] is not RUN_ON


@pytest.mark.parametrize(
    "run_on",
    [{**RUN_ON, "cut_sample": 0}, {"spoken_text": "最后验收。"}, {**RUN_ON, "spoken_text": ""}],
    ids=["no-cut", "missing-cut", "no-text"],
)
def test_a_malformed_run_on_is_refused(run_on):
    takes = {"2": {"seed": 7, "text_sha256": sha256("再说明。"), "run_on": run_on}}
    with pytest.raises(ValueError, match="declared thought"):
        narration_retakes.apply_retakes(PLANS, takes, 3)


def test_thought_retakes_require_authored_thoughts():
    with pytest.raises(ValueError, match="authored utterance groups"):
        narration_retakes.apply_retakes(
            PLANS[:1], {"1": {"seed": 7, "text_sha256": sha256("先核验。")}}, 3
        )


@pytest.mark.parametrize(
    ("cast", "seed", "temperature"),
    [
        ({"full_narration_seed": 4677, "full_narration_temperature": 0.5}, 4677 + 26, 0.5),
        ({}, 227 + 26, 0.46),
        (
            {
                "full_narration_seed": 4677,
                "retakes": {"26": {"seed": 9228, "temperature": 0.4}},
            },
            9228,
            0.4,
        ),
    ],
    ids=["cast", "defaults", "segment-retake"],
)
def test_a_segment_is_narrated_with_its_take(cast, seed, temperature):
    taken = narration_retakes.segment_take({"id": "26"}, cast, PLANS)
    assert taken == (seed, temperature, PLANS)


def test_a_segment_take_applies_its_thought_retakes_against_its_own_seed():
    cast = {
        "retakes": {
            "26": {"seed": 9228, "groups": {"1": {"seed": 5, "text_sha256": sha256("先核验。")}}}
        }
    }
    assert narration_retakes.segment_take({"id": "26"}, cast, PLANS) == (
        9228,
        0.46,
        [{**PLANS[0], "seed": 5}, PLANS[1]],
    )
    cast["retakes"]["26"]["groups"]["1"]["seed"] = 9228
    with pytest.raises(ValueError, match="declared thought"):
        narration_retakes.segment_take({"id": "26"}, cast, PLANS)


SCRIPT = {
    "segments": [
        {"id": "06", "utterance_groups": ["按标准，这次交付不合格。", "决定由有权的人作出。"]}
    ]
}


def row(index: int, text: str, seed: int | None) -> dict:
    return {"segment": "06", "index": index, "text": text, "proposed_seed": seed}


def test_proposals_bind_the_current_thoughts_and_skip_those_without_a_seed():
    cast = {"reference_audio": "reference.wav"}
    rows = [row(2, "决定由有权的人作出。", 99711), row(1, "按标准，这次交付不合格。", None)]
    bound_cast, bound, skipped = narration_retakes.bind_proposals(SCRIPT, cast, rows)
    assert bound_cast == {
        "reference_audio": "reference.wav",
        "retakes": {
            "06": {"groups": {"2": {"seed": 99711, "text_sha256": sha256("决定由有权的人作出。")}}}
        },
    }
    assert (bound, skipped) == (["06.2=99711"], ["06.1"])
    assert cast == {"reference_audio": "reference.wav"}


def test_a_proposal_binds_its_run_on_with_its_seed():
    rows = [{**row(2, "决定由有权的人作出。", 99711), "proposed_run_on": RUN_ON}]
    bound_cast, bound, _ = narration_retakes.bind_proposals(SCRIPT, {}, rows)
    assert bound_cast["retakes"]["06"]["groups"]["2"] == {
        "seed": 99711,
        "text_sha256": sha256("决定由有权的人作出。"),
        "run_on": RUN_ON,
    }
    assert bound == ["06.2=99711"]


@pytest.mark.parametrize(
    "stale",
    [
        row(2, "决定由负责人作出。", 7),
        row(3, "决定由有权的人作出。", 7),
        {**row(1, "x", 7), "segment": "07"},
    ],
    ids=["text", "index", "segment"],
)
def test_a_proposal_for_a_changed_thought_is_refused(stale):
    with pytest.raises(ValueError, match="not the current thought"):
        narration_retakes.bind_proposals(SCRIPT, {}, [stale])


def test_a_bound_retake_follows_its_exact_text_or_is_released():
    bound = {
        "1": {"seed": 7, "text_sha256": sha256("甲。")},
        "2": {"seed": 5, "text_sha256": sha256("乙。")},
        "3": {"seed": 9, "text_sha256": sha256("丙。")},
    }
    before = copy.deepcopy(bound)
    moved, released = narration_retakes.rebind(bound, ["丙。", "新。", "甲。", "丙。"])
    assert moved == {"3": {"seed": 7, "text_sha256": sha256("甲。")}}
    assert released == ["2", "3"]
    assert bound == before


def test_a_thought_entry_binds_its_seed_to_its_text():
    assert narration_retakes.retake_entry(7, "甲。") == {"seed": 7, "text_sha256": sha256("甲。")}
