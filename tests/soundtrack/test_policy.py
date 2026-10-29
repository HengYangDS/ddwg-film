"""The designed pause contract each edition declares, and the releases it names."""

import json
import re

import pytest

import ddwg_film.repository as repository
import ddwg_film.soundtrack.policy as soundtrack_policy


def test_designed_pause_policy_keeps_the_declared_contract(designed_policy, performance):
    policy = designed_policy()
    # Undeclared optional parts take their defaults, in the order the receipt records.
    assert policy == {
        "pauses": performance["designed_pauses"],
        "limits": performance["designed_pause_limits"],
        "weights": performance["designed_pause_weights"],
        "tail_guard": 0.3,
        "thought_range": [0.3, 0.6],
        "paragraph_range": [1.2, 2.0],
        "boundary_ratio": 1.0,
        "boundary_margin": 0.0,
        "level_tolerance": None,
        "chapter_level_tolerance": None,
        "coda": None,
        "inner_cap": None,
        "inner_caps": None,
        "inner_floors": None,
        "inner_breath": None,
        "releases": {},
    }
    assert list(policy) == [
        "pauses",
        "limits",
        "weights",
        "tail_guard",
        "thought_range",
        "paragraph_range",
        "boundary_ratio",
        "boundary_margin",
        "level_tolerance",
        "chapter_level_tolerance",
        "coda",
        "inner_cap",
        "inner_caps",
        "inner_floors",
        "inner_breath",
        "releases",
    ]


@pytest.mark.parametrize("script", ["content/film-script.json", "content/en/film-script.json"])
def test_each_edition_declares_a_complete_pause_contract(script):
    performance = json.loads((repository.ROOT / script).read_text())["voice_performance"]
    policy = soundtrack_policy.designed_pause_policy(performance)
    # The policy is the declared contract under the receipt's names, with its defaults.
    expected = {
        "pauses": performance["designed_pauses"],
        "limits": performance["designed_pause_limits"],
        "weights": performance["designed_pause_weights"],
        "tail_guard": performance.get("tail_guard_seconds", 0.3),
        "thought_range": performance["thought_pause_range"],
        "paragraph_range": performance["paragraph_pause_range"],
        "boundary_ratio": performance.get("thought_boundary_ratio", 1.0),
        "boundary_margin": performance.get("thought_boundary_margin_seconds", 0.0),
        "level_tolerance": performance.get("thought_level_tolerance_db"),
        "chapter_level_tolerance": performance.get("chapter_level_tolerance_db"),
        "coda": performance.get("coda_thought_pause_seconds"),
        "inner_cap": performance.get("inner_pause_cap_seconds"),
        "inner_caps": performance.get("inner_pause_caps_seconds"),
        "inner_floors": performance.get("inner_pause_floors_seconds"),
        "inner_breath": performance.get("inner_breath"),
        "releases": performance.get("released_tail_seconds", {}),
    }
    assert policy == expected
    assert list(policy) == list(expected)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"assembly_mode": "quiet-only"}, "Assembly requires native speech with designed pauses"),
        ({"designed_pauses": {"thought": 0.45}}, "designed_pauses requires exactly"),
        (
            {"designed_pause_limits": {"opening": 1.0, "paragraph": 5.5, "chapter": 9.0}},
            "designed_pause_limits.opening must be a number from 3.0 to 20",
        ),
        (
            {"designed_pause_weights": {"opening": 0, "paragraph": 0, "chapter": 0}},
            "designed_pause_weights requires a positive weight",
        ),
        ({"tail_guard_seconds": 1.0}, "tail_guard_seconds must be a number from 0.05 to 0.6"),
        ({"thought_pause_range": [0.5, 0.6]}, "thought_pause_range low must be a number"),
        ({"thought_pause_range": [0.3]}, "thought_pause_range requires a low and a high value"),
        ({"paragraph_pause_range": [1.7, 2.0]}, "paragraph_pause_range low must be a number"),
        ({"paragraph_pause_range": [1.2, 6.0]}, "paragraph_pause_range high must be a number"),
        ({"paragraph_pause_range": [1.2]}, "paragraph_pause_range requires a low and a high"),
        ({"thought_boundary_ratio": 0.9}, "thought_boundary_ratio must be a number"),
        ({"thought_boundary_ratio": 2.5}, "thought_boundary_ratio must be a number"),
        (
            {"thought_boundary_margin_seconds": 0.3},
            "thought_boundary_margin_seconds must be a number from 0 to 0.2",
        ),
        ({"thought_level_tolerance_db": 0.1}, "thought_level_tolerance_db must be a number"),
        ({"chapter_level_tolerance_db": 0.05}, "chapter_level_tolerance_db must be a number"),
        ({"chapter_level_tolerance_db": 4.0}, "chapter_level_tolerance_db must be a number"),
        ({"coda_thought_pause_seconds": 0.4}, "coda_thought_pause_seconds must be a number"),
        ({"coda_thought_pause_seconds": 2.5}, "coda_thought_pause_seconds must be a number"),
        ({"inner_pause_cap_seconds": 0.1}, "inner_pause_cap_seconds must be a number"),
        ({"inner_pause_cap_seconds": 0.5}, "inner_pause_cap_seconds must be a number"),
        (
            {"inner_pause_floors_seconds": {}},
            "inner_pause_floors_seconds requires marks with seconds",
        ),
        (
            {"inner_pause_floors_seconds": {"，a": 0.15}},
            "inner_pause_floors_seconds keys must be punctuation marks",
        ),
        (
            {"inner_pause_floors_seconds": {"。，": 0.3, "，": 0.15}},
            "inner_pause_floors_seconds names a mark twice",
        ),
        (
            {"inner_pause_cap_seconds": 0.3, "inner_pause_floors_seconds": {"。": 0.32}},
            "inner_pause_floors_seconds.。 must be a number from 0.05 to 0.3",
        ),
        (
            {"inner_pause_caps_seconds": {",": 0.25}},
            "inner_pause_caps_seconds requires inner_pause_cap_seconds",
        ),
        (
            {"inner_pause_cap_seconds": 0.3, "inner_pause_caps_seconds": {}},
            "inner_pause_caps_seconds requires marks with seconds",
        ),
        (
            {"inner_pause_cap_seconds": 0.3, "inner_pause_caps_seconds": {",a": 0.25}},
            "inner_pause_caps_seconds keys must be punctuation marks",
        ),
        (
            {"inner_pause_cap_seconds": 0.3, "inner_pause_caps_seconds": {",": 0.35}},
            "inner_pause_caps_seconds., must be a number from 0.1 to 0.3",
        ),
        (
            {
                "inner_pause_cap_seconds": 0.3,
                "inner_pause_caps_seconds": {",;": 0.2, ";": 0.25},
            },
            "inner_pause_caps_seconds names a mark twice",
        ),
        (
            {
                "inner_pause_cap_seconds": 0.3,
                "inner_pause_caps_seconds": {"，": 0.2},
                "inner_pause_floors_seconds": {"，": 0.25},
            },
            "inner_pause_floors_seconds.， exceeds its cap in inner_pause_caps_seconds",
        ),
        (
            {"inner_breath": {"longest_group_seconds": 8.0, "pause_seconds": 0.28}},
            "inner_breath requires inner_pause_floors_seconds",
        ),
        (
            {
                "inner_pause_floors_seconds": {"，": 0.15},
                "inner_breath": {"longest_group_seconds": 8.0},
            },
            "inner_breath requires exactly longest_group_seconds and pause_seconds",
        ),
        (
            {
                "inner_pause_floors_seconds": {"，": 0.15},
                "inner_breath": {"longest_group_seconds": 1.0, "pause_seconds": 0.28},
            },
            "inner_breath.longest_group_seconds must be a number from 3 to 20",
        ),
        (
            {"released_tail_seconds": [0.15]},
            "released_tail_seconds requires seconds by thought join",
        ),
        (
            {"released_tail_seconds": {"24": 0.15}},
            "released_tail_seconds key must name a thought join such as 24.3: 24",
        ),
        (
            {"released_tail_seconds": {"24.0": 0.15}},
            "released_tail_seconds key must name a thought join such as 24.3: 24.0",
        ),
        (
            {"released_tail_seconds": {"24.3": 0.5}},
            "released_tail_seconds.24.3 must be a number from 0.06 to 0.3",
        ),
    ],
)
def test_designed_pause_policy_refuses_incomplete_contracts(designed_policy, overrides, message):
    with pytest.raises(soundtrack_policy.PausePolicyError, match=re.escape(message)):
        designed_policy(**overrides)


def test_released_tails_name_one_thought_join_of_a_segment(designed_policy):
    segments = [
        {"id": "01", "utterance_groups": ["一。"]},
        {"id": "02", "utterance_groups": ["一。", "二。", "三。"]},
    ]
    policy = designed_policy(released_tail_seconds={"02.2": 0.15})
    assert soundtrack_policy.segment_releases(policy, segments) == {"01": {}, "02": {2: 0.15}}
    for key in ("03.1", "02.3", "01.1"):
        policy = designed_policy(released_tail_seconds={key: 0.15})
        message = re.escape(f"names no thought join: {key}")
        with pytest.raises(soundtrack_policy.PausePolicyError, match=message):
            soundtrack_policy.segment_releases(policy, segments)
