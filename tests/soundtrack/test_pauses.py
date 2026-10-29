"""Designed pauses between thoughts, paragraphs and chapters."""

import re

import numpy as np
import pytest

import filmkit.soundtrack.pauses as soundtrack_pauses


def test_statement_pauses_grow_with_the_thought_and_keep_their_mean(designed_policy):
    policy = designed_policy()
    segments = [
        {
            "id": "01",
            "utterance_groups": [
                "短句。",
                "这是一句明显更长的完整想法。",
                "谁来决定？",
                "结尾。",
            ],
        },
        {"id": "02", "utterance_groups": ["一个中等长度的想法。", "收尾。"]},
    ]
    targets = soundtrack_pauses.thought_pause_targets(segments, policy)
    assert [len(targets["01"]), len(targets["02"])] == [3, 1]
    assert targets["01"][2] == policy["pauses"]["question"]
    short, long, middle = targets["01"][0], targets["01"][1], targets["02"][0]
    assert short < middle < long
    assert (short + long + middle) / 3 == pytest.approx(policy["pauses"]["thought"])
    low, high = policy["thought_range"]
    assert all(low <= value <= high for value in (short, long, middle))


def test_the_closing_segment_settles_on_the_declared_coda_pause(designed_policy):
    policy = designed_policy(coda_thought_pause_seconds=0.9)
    segments = [
        {
            "id": "01",
            "utterance_groups": [
                "短句。",
                "这是一句明显更长的完整想法。",
                "中等长度的想法。",
                "又一句。",
                "这也是一句较长的完整想法。",
                "结尾。",
            ],
        },
        {
            "id": "02",
            "utterance_groups": ["一个中等长度的想法。", "收尾了吗？", "最后。"],
        },
    ]
    targets = soundtrack_pauses.thought_pause_targets(segments, policy)
    statements = targets["01"] + targets["02"][:1]
    assert targets["02"] == [0.9, 0.9]
    assert abs(sum(statements) / len(statements) - 0.45) < 1e-6
    assert all(0.3 <= value <= 0.6 for value in targets["01"])


def test_thought_boundaries_outlast_the_pauses_inside_both_neighbours(designed_policy):
    policy = designed_policy(thought_boundary_ratio=1.2)
    segments = [
        {
            "id": "01",
            "utterance_groups": [
                "短句。",
                "这是一句明显更长的完整想法。",
                "谁来决定？",
                "结尾。",
            ],
        },
        {"id": "02", "utterance_groups": ["一个中等长度的想法。", "收尾。"]},
    ]
    # The longest heard quiet inside every thought, and the unheard part of each join.
    inner = {"01": [0.0, 0.4, 0.3, 0.6], "02": [0.2, 0.0]}
    overhead = {"01": [0.0, 0.05, 0.0], "02": [0.0]}
    targets = soundtrack_pauses.thought_pause_targets(segments, policy, inner, overhead)
    # A join is floored by the longer inner quiet of the thoughts on either side, and
    # pays its unheard overhead.
    assert targets["01"][0] >= 1.2 * 0.4 - 1e-9
    assert targets["01"][1] >= 1.2 * 0.4 + 0.05 - 1e-9
    assert targets["01"][2] == pytest.approx(1.2 * 0.6)
    assert targets["02"][0] >= 1.2 * 0.2
    statements = [targets["01"][0], targets["01"][1], targets["02"][0]]
    assert sum(statements) / 3 == pytest.approx(policy["pauses"]["thought"])
    with pytest.raises(ValueError, match="larger declared statement pause"):
        soundtrack_pauses.thought_pause_targets(
            segments, policy, {"01": [0.5, 0.5, 0.0, 0.0], "02": [0.5, 0.0]}
        )


def test_a_declared_margin_lengthens_every_floored_thought_boundary(designed_policy):
    segments = [
        {
            "id": "01",
            "utterance_groups": [
                "短。",
                "这是一句明显更长的完整想法，后面还有更多具体的内容。",
                "又是一句很长的完整想法，说得具体而且清楚。",
                "结尾。",
            ],
        }
    ]
    # The short first thought holds 0.3 s of heard inner quiet, so its join is floored.
    inner = {"01": [0.3, 0.0, 0.0, 0.0]}
    plain = soundtrack_pauses.thought_pause_targets(
        segments, designed_policy(thought_boundary_ratio=1.2), inner
    )
    assert plain["01"][0] == pytest.approx(1.2 * 0.3)
    # A declared margin floors it that much above its ratio, so a measure bounded by the
    # aligned word edges still hears it at the declared ratio.
    margined = soundtrack_pauses.thought_pause_targets(
        segments,
        designed_policy(thought_boundary_ratio=1.2, thought_boundary_margin_seconds=0.06),
        inner,
    )
    assert margined["01"][0] == pytest.approx(1.2 * 0.3 + 0.06)


def test_pause_shapes_refuse_a_mean_their_range_cannot_keep():
    # Nine short thoughts and one long one: at the lowest shift the bisection reaches, the
    # long thought still takes the high pause, so the mean would exceed the declared one.
    with pytest.raises(soundtrack_pauses.PauseError, match="cannot keep their declared mean"):
        soundtrack_pauses.mean_preserving_pauses([1] * 9 + [100], 0.45, 0.45, 0.6)
    shaped = soundtrack_pauses.mean_preserving_pauses([1] * 9 + [100], 0.5, 0.45, 0.6)
    assert sum(shaped) / len(shaped) == pytest.approx(0.5)


def test_designed_quiet_enters_the_heard_part_of_a_join():
    rate = 1000
    voiced = np.full((200, 2), 5000, dtype=np.int16)
    # A tail decays through quiet still heard above -55 dBFS before it falls silent.
    tail = np.full((80, 2), 120, dtype=np.int16)
    audio = np.concatenate([voiced, tail, np.zeros((200, 2), np.int16), voiced])
    items = [
        {"text": "先", "start_time": 0.0, "end_time": 0.2},
        {"text": "看", "start_time": 0.48, "end_time": 0.68},
    ]
    joins = soundtrack_pauses.thought_joins(audio, items, "先。看", ["先。", "看"], rate)
    assert joins[0].heard == (280, 480)
    assert joins[0].overhead == pytest.approx(0.08)
    designed, _, edits = soundtrack_pauses.design_thought_pauses(
        audio, items, "先。看", ["先。", "看"], rate, targets=[0.5]
    )
    # The designed quiet enters the middle of the heard quiet, so the tail keeps its
    # whole native decay before it.
    assert edits[0]["source_sample"] == 380
    assert edits[0]["heard_native_quiet_seconds"] == pytest.approx(0.2)
    # The tail is still heard where it meets the digital silence, so it is released
    # over its last 60 ms; everything before the release is untouched.
    assert edits[0]["released_tail_samples"] == 60
    assert np.array_equal(designed[:220], audio[:220])
    assert np.all(np.diff(designed[220:280, 0].astype(int)) <= 0)
    assert designed[279, 0] <= 1
    assert len(designed) == len(audio) + 220
    assert np.all(designed[280:700] == 0)


def test_designed_quiet_is_removed_only_from_the_heard_quiet():
    rate = 1000
    voiced = np.full((200, 2), 5000, dtype=np.int16)
    # 0.3 s of a decaying tail heard above -55 dBFS, then 0.1 s of digital silence.
    tail = np.full((300, 2), 120, dtype=np.int16)
    audio = np.concatenate([voiced, tail, np.zeros((100, 2), np.int16), voiced])
    items = [
        {"text": "先", "start_time": 0.0, "end_time": 0.2},
        {"text": "看", "start_time": 0.6, "end_time": 0.8},
    ]
    # 0.3 s of native quiet would have to go, but only 0.1 s of it is heard as quiet.
    with pytest.raises(soundtrack_pauses.PauseError, match="beyond its heard quiet"):
        soundtrack_pauses.design_thought_pauses(
            audio, items, "先。看", ["先。", "看"], rate, targets=[0.1]
        )
    designed, aligned, edits = soundtrack_pauses.design_thought_pauses(
        audio, items, "先。看", ["先。", "看"], rate, targets=[0.32]
    )
    assert edits[0]["removed_quiet_samples"] == 80
    assert len(designed) == len(audio) - 80
    assert np.array_equal(designed[-200:], voiced)
    assert aligned[1]["start_time"] == pytest.approx(0.52)


def test_a_zero_crossing_inside_a_decay_is_not_digital_silence():
    rate = 1000
    voiced = np.full((200, 2), 5000, dtype=np.int16)
    # The voice decays through a zero crossing into quiet that crosses zero now and then,
    # but no run of digital silence lies between the thoughts.
    decay = np.full((60, 2), 2000, dtype=np.int16)
    decay[30] = 0
    hush = np.tile(np.array([[1, 1], [0, 0], [-1, -1], [1, 1]], np.int16), (50, 1))
    audio = np.concatenate([voiced, decay, hush, voiced])
    items = [
        {"text": "先", "start_time": 0.0, "end_time": 0.26},
        {"text": "看", "start_time": 0.46, "end_time": 0.66},
    ]
    designed, _, edits = soundtrack_pauses.design_thought_pauses(
        audio, items, "先。看", ["先。", "看"], rate, targets=[0.5]
    )
    # Nothing is released: the decay keeps every sample up to the quiet it dies into.
    assert edits[0]["released_tail_samples"] == 0
    assert np.array_equal(designed[:260], audio[:260])


def test_a_recording_cut_while_voiced_is_released_before_digital_silence():
    rate = 1000
    voiced = np.full((200, 2), 5000, dtype=np.int16)
    audio = np.concatenate([voiced, np.zeros((300, 2), np.int16), voiced])
    items = [
        {"text": "先", "start_time": 0.0, "end_time": 0.2},
        {"text": "看", "start_time": 0.5, "end_time": 0.7},
    ]
    designed, _, edits = soundtrack_pauses.design_thought_pauses(
        audio, items, "先。看", ["先。", "看"], rate, targets=[0.3]
    )
    # The voice stops on a step in the recording; the last 60 ms fade into the quiet.
    assert edits[0]["released_tail_samples"] == 60
    assert np.array_equal(designed[:140], audio[:140])
    assert 0 < designed[170, 0] < 5000
    assert designed[199, 0] <= 5
    # A thought may declare a longer release for a take that still sounds at its end.
    designed, _, edits = soundtrack_pauses.design_thought_pauses(
        audio, items, "先。看", ["先。", "看"], rate, targets=[0.3], releases={1: 0.15}
    )
    assert edits[0]["released_tail_samples"] == 150
    assert np.array_equal(designed[:50], audio[:50])
    assert 0 < designed[125, 0] < 5000
    assert designed[199, 0] <= 5


def test_inserted_quiet_fades_the_native_quiet_beside_it():
    rate = 1000
    voiced = np.full((200, 2), 5000, dtype=np.int16)
    hush = np.full((200, 2), 120, dtype=np.int16)
    audio = np.concatenate([voiced, hush, voiced])
    items = [
        {"text": "先", "start_time": 0.0, "end_time": 0.2},
        {"text": "看", "start_time": 0.4, "end_time": 0.6},
    ]
    designed, _, edits = soundtrack_pauses.design_thought_pauses(
        audio, items, "先。看", ["先。", "看"], rate, targets=[0.5]
    )
    zeros = np.flatnonzero(np.all(designed == 0, axis=1))
    assert edits[0]["fade_samples"] == 50
    assert len(zeros) >= edits[0]["inserted_quiet_samples"]
    before, after = designed[zeros[0] - 1], designed[zeros[-1] + 1]
    assert abs(int(before[0])) < 120
    assert abs(int(after[0])) < 120
    assert np.array_equal(designed[np.abs(designed[:, 0]) > 200], np.concatenate([voiced] * 2))


def test_digital_silence_inside_a_join_is_entered_through_a_soft_fade():
    rate = 1000
    voiced = np.full((200, 2), 5000, dtype=np.int16)
    # A tail that has already decayed below heard quiet keeps its 10 ms soft edge.
    tail = np.full((40, 2), 50, dtype=np.int16)
    audio = np.concatenate([voiced, tail, np.zeros((160, 2), np.int16), voiced])
    items = [
        {"text": "先", "start_time": 0.0, "end_time": 0.2},
        {"text": "看", "start_time": 0.4, "end_time": 0.6},
    ]
    designed, _, _ = soundtrack_pauses.design_thought_pauses(
        audio, items, "先。看", ["先。", "看"], rate, targets=[0.3]
    )
    zeros = np.flatnonzero(np.all(designed == 0, axis=1))
    assert 0 < abs(int(designed[zeros[0] - 1, 0])) < 50
    assert abs(int(designed[zeros[0] - 11, 0])) == 50
    assert np.array_equal(designed[np.abs(designed[:, 0]) > 2048], np.concatenate([voiced] * 2))


def test_a_tail_too_quiet_to_step_keeps_its_samples_beside_digital_silence():
    rate = 1000
    voiced = np.full((200, 2), 5000, dtype=np.int16)
    # The voice has died to about -80 dBFS before the silence, so there is no step to fade.
    tail = np.full((40, 2), 3, dtype=np.int16)
    audio = np.concatenate([voiced, tail, np.zeros((160, 2), np.int16), voiced])
    items = [
        {"text": "先", "start_time": 0.0, "end_time": 0.2},
        {"text": "看", "start_time": 0.4, "end_time": 0.6},
    ]
    designed, _, _ = soundtrack_pauses.design_thought_pauses(
        audio, items, "先。看", ["先。", "看"], rate, targets=[0.3]
    )
    assert np.array_equal(designed[:240], audio[:240])


def test_paragraph_pauses_grow_with_the_paragraph_and_keep_their_mean(designed_policy):
    policy = designed_policy()
    segments = [
        {"id": "01", "chapter": "a", "text": "短。"},
        {"id": "02", "chapter": "a", "text": "这一段明显更长，说了好几件完整的事情。"},
        {"id": "03", "chapter": "a", "text": "中等长度的一段话。"},
        {"id": "04", "chapter": "b", "text": "新的一章。"},
        {"id": "05", "chapter": "b", "text": "结尾。"},
    ]
    assert soundtrack_pauses.gap_kinds(segments) == [
        "opening",
        "paragraph",
        "paragraph",
        "chapter",
        "paragraph",
    ]
    bases = soundtrack_pauses.gap_pause_targets(segments, policy)
    pauses = policy["pauses"]
    assert bases[0] == pauses["opening"]
    assert bases[3] == pauses["chapter"]
    after_short, after_long, after_new = bases[1], bases[2], bases[4]
    assert after_short < after_new < after_long
    assert (after_short + after_long + after_new) / 3 == pytest.approx(pauses["paragraph"])
    low, high = policy["paragraph_range"]
    assert all(low <= value <= high for value in (after_short, after_long, after_new))


def test_designed_gaps_fill_exact_runtime_by_weight_within_limits(designed_policy):
    policy = designed_policy()
    rate = 100
    kinds = ["opening", "paragraph", "chapter", "paragraph"]
    minimum = sum(round(policy["pauses"][kind] * rate) for kind in kinds)
    closing = round(policy["pauses"]["closing"] * rate)
    total = 10_000
    speech = total - minimum - closing - 900
    gaps, tail = soundtrack_pauses.allocate_designed_gaps(kinds, speech, policy, rate, total)
    assert tail == closing
    assert sum(gaps) + speech + tail == total
    assert all(
        gap >= round(policy["pauses"][kind] * rate) for kind, gap in zip(kinds, gaps, strict=True)
    )
    assert all(
        gap <= round(policy["limits"][kind] * rate) for kind, gap in zip(kinds, gaps, strict=True)
    )
    assert gaps[2] - 340 > gaps[1] - 160
    assert abs(gaps[1] - gaps[3]) <= 1
    with pytest.raises(ValueError, match=re.escape("exceeds the runtime by 0.01 s")):
        soundtrack_pauses.allocate_designed_gaps(kinds, speech + 901, policy, rate, total)
    with pytest.raises(ValueError, match="short by"):
        soundtrack_pauses.allocate_designed_gaps(kinds, 10, policy, rate, total)
    bases = [3.0, 1.2, 3.4, 2.0]
    floor = sum(round(base * rate) for base in bases) + closing
    gaps, _ = soundtrack_pauses.allocate_designed_gaps(
        kinds, total - floor, policy, rate, total, bases=bases
    )
    assert gaps == [round(base * rate) for base in bases]
    with pytest.raises(ValueError, match="one designed pause"):
        soundtrack_pauses.allocate_designed_gaps(kinds, speech, policy, rate, total, bases=[1.0])


def test_thought_pauses_move_only_measured_quiet():
    rate = 1000
    voiced = np.full((200, 2), 5000, dtype=np.int16)
    # The thought before the join decays below heard quiet, so no release applies.
    audio = np.concatenate(
        [
            voiced,
            np.zeros((300, 2), np.int16),
            voiced,
            np.full((30, 2), 8, np.int16),
            np.zeros((120, 2), np.int16),
            voiced,
        ]
    )
    items = [
        {"text": "先", "start_time": 0.0, "end_time": 0.2},
        {"text": "看", "start_time": 0.5, "end_time": 0.7},
        {"text": "再", "start_time": 0.85, "end_time": 1.05},
    ]
    designed, aligned, edits = soundtrack_pauses.design_thought_pauses(
        audio, items, "先看？再", ["先看？", "再"], rate, targets=[0.7]
    )
    assert [edit["designed_quiet_seconds"] for edit in edits] == [0.7]
    assert edits[0]["released_tail_samples"] == 0
    assert np.array_equal(designed[np.abs(designed[:, 0]) > 2048], np.concatenate([voiced] * 3))
    assert aligned[2]["start_time"] - aligned[1]["end_time"] == pytest.approx(0.7, abs=0.15)
    assert aligned[0] == items[0]
    assert len(designed) == len(audio) + edits[0]["inserted_quiet_samples"]
    with pytest.raises(ValueError, match="complete nonempty thought groups"):
        soundtrack_pauses.design_thought_pauses(
            audio,
            items,
            "先看？再",
            ["先看？", "再再"],
            rate,
            targets=[0.7],
        )
    with pytest.raises(ValueError, match="one designed pause"):
        soundtrack_pauses.design_thought_pauses(
            audio, items, "先看？再", ["先看？", "再"], rate, targets=[]
        )
