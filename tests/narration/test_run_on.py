"""Run-on takes: a thought narrated with the words that follow it, cut in the quiet between them."""

import numpy as np
import pytest

import filmkit.narration.run_on as narration_run_on

RATE = 24000


def take(*parts: tuple[float, float]) -> np.ndarray:
    """A 16-bit take of (seconds, amplitude) parts: a fading tone, or digital zero at 0."""
    pieces = []
    for seconds, amplitude in parts:
        n = round(seconds * RATE)
        tone = np.sin(2 * np.pi * 180 * np.arange(n) / RATE) * amplitude * np.linspace(1, 0.2, n)
        pieces.append((tone * 32767).astype(np.int16))
    return np.concatenate(pieces)


def test_a_run_on_take_is_cut_where_heard_quiet_after_its_thought_first_lasts_30_ms():
    pcm = take((1.0, 0.3), (0.025, 0), (0.01, 0.3), (0.08, 0), (0.8, 0.3))
    cut = narration_run_on.run_on_cut(pcm, RATE, thought_end=0.98, next_start=1.12)
    # Frames are read from the thought's end: the 25 ms of quiet after it are too short, and the
    # third quiet frame of the 80 ms run ends the cut.
    assert cut == round(1.07 * RATE)


def test_a_run_on_take_without_quiet_before_its_next_words_has_no_cut():
    pcm = take((1.0, 0.3), (0.02, 0), (0.8, 0.3))
    assert narration_run_on.run_on_cut(pcm, RATE, thought_end=0.96, next_start=1.0) is None


def test_the_cut_is_searched_only_up_to_one_aligner_step_after_the_next_words_begin():
    pcm = take((1.0, 0.3), (0.3, 0.3), (0.1, 0), (0.6, 0.3))
    assert narration_run_on.run_on_cut(pcm, RATE, thought_end=0.96, next_start=1.0) is None


def test_the_thought_bounds_come_from_the_units_of_the_thought_and_its_run_on():
    items = [
        {"text": "给结", "start_time": 0.1, "end_time": 0.5},
        {"text": "论", "start_time": 0.5, "end_time": 0.74},
        {"text": "与其", "start_time": 0.9, "end_time": 1.2},
    ]
    assert narration_run_on.thought_bounds(items, "给结论。", "与其。") == (0.74, 0.9)


def dying(seconds: float) -> np.ndarray:
    """A float thought whose voice holds and then dies away over its last 0.3 s."""
    n, tail = round(seconds * RATE), round(0.3 * RATE)
    envelope = np.concatenate([np.ones(n - tail), np.exp(-np.arange(tail) / (0.03 * RATE))])
    return (np.sin(2 * np.pi * 180 * np.arange(n) / RATE) * 0.3 * envelope).astype(np.float32)


def test_a_cut_keeps_the_float_samples_before_it_when_they_end_naturally():
    audio = np.concatenate([dying(1.0), np.zeros(2400, dtype=np.float32), dying(1.0)])
    kept = narration_run_on.cut_run_on(audio, 24000 + 1200, RATE)
    assert np.array_equal(kept, audio[: 24000 + 1200])


@pytest.mark.parametrize("cut", [0, 24000 + 2400 + 24000, 12000], ids=["start", "end", "voiced"])
def test_a_cut_outside_the_take_or_inside_its_voice_is_refused(cut):
    audio = np.concatenate([dying(1.0), np.zeros(2400, dtype=np.float32), dying(1.0)])
    with pytest.raises(RuntimeError, match="run-on"):
        narration_run_on.cut_run_on(audio, cut, RATE)


RECORDS = [
    {
        "id": "24",
        "utterance_groups": {
            "records": [{"index": 1, "spoken_text": "甲。"}, {"index": 2, "spoken_text": "乙。"}]
        },
    },
    {"id": "25", "utterance_groups": {"records": [{"index": 1, "spoken_text": "丙。"}]}},
]


@pytest.mark.parametrize(("segment", "index", "following"), [("24", 1, "乙。"), ("24", 2, "丙。")])
def test_a_run_on_reads_on_into_the_thought_that_follows_in_the_film(segment, index, following):
    assert narration_run_on.following_spoken_text(RECORDS, segment, index) == following


def test_the_last_thought_has_nothing_to_read_on_into():
    with pytest.raises(ValueError, match=r"25\.1: no thought follows"):
        narration_run_on.following_spoken_text(RECORDS, "25", 1)


@pytest.mark.parametrize(
    ("run_on", "valid"),
    [
        ({"spoken_text": "与其。", "cut_sample": 1200}, True),
        ({"spoken_text": " ", "cut_sample": 1200}, False),
        ({"spoken_text": "与其。", "cut_sample": 0}, False),
        ({"spoken_text": "与其。", "cut_sample": 1.5}, False),
        ({"spoken_text": "与其。"}, False),
        ({"spoken_text": "与其。", "cut_sample": 1200, "seed": 1}, False),
        ("与其。", False),
    ],
)
def test_a_declared_run_on_names_its_spoken_text_and_a_positive_cut(run_on, valid):
    assert narration_run_on.valid_run_on(run_on) is valid
