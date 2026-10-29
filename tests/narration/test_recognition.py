"""Recognition units and their comparison: how a transcript is checked against its text."""

import pytest

import ddwg_film.narration.recognition as narration_recognition


def test_units_fold_case_and_drop_punctuation_in_both_languages():
    assert narration_recognition.recognition_units("数据，先看 Agent 的用途。") == [
        *"数据先看",
        "agent",
        *"的用途",
    ]
    assert narration_recognition.recognition_units("Don't cite ETHOS-2, please!") == [
        "don't",
        "cite",
        "ethos",
        "2",
        "please",
    ]


@pytest.mark.parametrize(
    ("heard", "phrase", "expected"),
    [
        ("先看这份数据的用途。", "数据的用途", True),
        ("先看数据，再看用途。", "数据的用途", False),
        ("Ask these questions for the INTENDED use.", "intended use", True),
        ("Use it as intended.", "intended use", False),
        ("Anything at all.", "", False),
    ],
)
def test_heard_phrase_needs_its_units_contiguous(heard, phrase, expected):
    assert narration_recognition.heard_phrase(heard, phrase) is expected


@pytest.mark.parametrize(
    ("expected", "observed", "distance"),
    [
        (["数", "据"], ["数", "据"], 0),
        (["数", "据"], ["数", "句"], 1),
        (["agent", "use"], ["agent"], 1),
        (["use"], ["intended", "use"], 1),
        ([], ["extra", "words"], 2),
        (["a", "b", "c"], ["c", "b", "a"], 2),
    ],
)
def test_unit_distance_counts_the_fewest_unit_edits(expected, observed, distance):
    assert narration_recognition.unit_distance(expected, observed) == distance
