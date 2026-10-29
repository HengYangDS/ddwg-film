"""Heard quiet inside thoughts and its shaping."""

import numpy as np
import pytest

import filmkit.soundtrack.quiet as soundtrack_quiet


def test_inner_quiet_is_the_heard_quiet_inside_every_thought():
    rate = 1000
    voiced = np.full((200, 2), 5000, dtype=np.int16)
    audio = np.concatenate(
        [
            voiced,
            np.zeros((150, 2), np.int16),
            voiced,
            np.zeros((300, 2), np.int16),
            voiced,
            np.zeros((250, 2), np.int16),
            voiced,
        ]
    )
    items = [
        {"text": "先", "start_time": 0.0, "end_time": 0.2},
        {"text": "看", "start_time": 0.35, "end_time": 0.55},
        {"text": "再", "start_time": 0.85, "end_time": 1.05},
        {"text": "说", "start_time": 1.3, "end_time": 1.5},
    ]
    inner = soundtrack_quiet.thought_inner_quiet(
        audio, items, "先看。再说", ["先看。", "再说"], rate
    )
    # Heard quiet is counted in whole 10 ms frames, so a run may lose part of a frame
    # at each edge.
    assert inner == [pytest.approx(0.15, abs=0.011), pytest.approx(0.25, abs=0.011)]
    # Native quiet heard above -55 dBFS does not count.
    hush = audio.copy()
    hush[200:350] = 120
    inner = soundtrack_quiet.thought_inner_quiet(
        hush, items, "先看。再说", ["先看。", "再说"], rate
    )
    assert inner == [0.0, pytest.approx(0.25, abs=0.011)]


def test_inner_pauses_beyond_the_cap_lose_quiet_from_their_middle():
    rate = 1000
    voiced = np.full((200, 2), 5000, dtype=np.int16)
    audio = np.concatenate(
        [
            voiced,
            np.full((600, 2), 120, dtype=np.int16),
            voiced,
            np.zeros((150, 2), np.int16),
            voiced,
            np.zeros((700, 2), np.int16),
            voiced,
        ]
    )
    items = [
        {"text": "先", "start_time": 0.0, "end_time": 0.2},
        {"text": "看", "start_time": 0.8, "end_time": 1.0},
        {"text": "再", "start_time": 1.15, "end_time": 1.35},
        {"text": "说", "start_time": 2.05, "end_time": 2.25},
    ]
    text, groups = "先看再。说", ["先看再。", "说"]
    capped, moved, edits = soundtrack_quiet.cap_inner_quiet(audio, items, text, groups, rate, 0.4)
    assert edits == [
        {
            "source_sample": 400,
            "native_quiet_seconds": 0.6,
            "capped_quiet_seconds": 0.4,
            "removed_quiet_samples": 200,
            "crossfade_samples": 10,
        }
    ]
    # Speech, the short inner pause and the thought join stay as recorded, and the
    # crossfade keeps the capped quiet continuous.
    assert len(capped) == len(audio) - 200
    assert np.array_equal(capped[np.abs(capped[:, 0]) > 200], np.concatenate([voiced] * 4))
    assert np.all(capped[200:600] == 120)
    assert np.array_equal(capped[1150:], audio[1350:])
    assert [(m["start_time"], m["end_time"]) for m in moved] == [
        (0.0, 0.2),
        (0.6, 0.8),
        (0.95, 1.15),
        (1.85, 2.05),
    ]
    assert soundtrack_quiet.cap_inner_quiet(audio, items, text, groups, rate, None)[2] == []


def test_inner_pauses_take_the_cap_of_their_punctuation():
    rate = 1000
    voiced = np.full((200, 2), 5000, dtype=np.int16)
    quiet = np.zeros((500, 2), np.int16)
    audio = np.concatenate([voiced, quiet, voiced, quiet, voiced, quiet, voiced])
    items = [
        {"text": "one", "start_time": 0.0, "end_time": 0.2},
        {"text": "two", "start_time": 0.7, "end_time": 0.9},
        {"text": "three", "start_time": 1.4, "end_time": 1.6},
        {"text": "four", "start_time": 2.1, "end_time": 2.3},
    ]
    text, groups = "“One”, two. Three four", ["“One”, two. Three four"]
    capped, moved, edits = soundtrack_quiet.cap_inner_quiet(
        audio, items, text, groups, rate, 0.4, {",": 0.25}
    )
    # A comma is held to its own cap, also after a closing quote, a sentence end to the
    # inner cap, and a pause without punctuation to the smallest declared cap.
    assert [edit["capped_quiet_seconds"] for edit in edits] == [0.25, 0.4, 0.25]
    assert len(capped) == len(audio) - 250 - 100 - 250
    assert np.array_equal(capped[np.abs(capped[:, 0]) > 200], np.concatenate([voiced] * 4))
    assert [round(m["start_time"], 3) for m in moved] == [0.0, 0.45, 1.05, 1.5]
    # Without declared caps every pause takes the inner cap.
    plain = soundtrack_quiet.cap_inner_quiet(audio, items, text, groups, rate, 0.4)[2]
    assert [edit["capped_quiet_seconds"] for edit in plain] == [0.4, 0.4, 0.4]


def test_inner_pauses_reach_the_floor_of_their_punctuation():
    rate = 1000
    voiced = np.full((200, 2), 5000, dtype=np.int16)
    audio = np.concatenate(
        [
            voiced,
            np.zeros((100, 2), np.int16),
            voiced,
            np.full((50, 2), 120, dtype=np.int16),
            voiced,
            np.zeros((200, 2), np.int16),
            voiced,
            np.zeros((5, 2), np.int16),
            voiced,
        ]
    )
    items = [
        {"text": "先", "start_time": 0.0, "end_time": 0.2},
        {"text": "看", "start_time": 0.3, "end_time": 0.5},
        {"text": "再", "start_time": 0.55, "end_time": 0.75},
        {"text": "说", "start_time": 0.95, "end_time": 1.15},
        {"text": "好", "start_time": 1.155, "end_time": 1.355},
    ]
    text, groups = "先，看。再。说，好", ["先，看。再。", "说，好"]
    floors = {"。？！": 0.32, "；：": 0.26, "，": 0.16}
    lengthened, moved, edits = soundtrack_quiet.lengthen_inner_quiet(
        audio, items, text, groups, rate, floors
    )
    assert edits == [
        {
            "source_sample": 250,
            "marks": "，",
            "breath": False,
            "native_quiet_seconds": 0.1,
            "floor_seconds": 0.16,
            "inserted_quiet_samples": 60,
            "fade_samples": 50,
        },
        {
            "source_sample": 525,
            "marks": "。",
            "breath": False,
            "native_quiet_seconds": 0.05,
            "floor_seconds": 0.32,
            "inserted_quiet_samples": 270,
            "fade_samples": 25,
        },
    ]
    # Speech, the thought join and a comma spoken without quiet stay as recorded; the
    # inserted quiet is digital zero and the native quiet beside it fades into it.
    assert len(lengthened) == len(audio) + 330
    assert np.array_equal(lengthened[np.abs(lengthened[:, 0]) > 200], np.concatenate([voiced] * 5))
    assert np.all(lengthened[200:360] == 0)
    assert np.all(lengthened[560:880] <= 120)
    assert not np.any(lengthened[585:855])
    assert lengthened[560, 0] == 120
    assert np.array_equal(lengthened[1080:], audio[750:])
    assert [(m["start_time"], m["end_time"]) for m in moved] == [
        (0.0, 0.2),
        (0.36, 0.56),
        (0.88, 1.08),
        (1.28, 1.48),
        (1.485, 1.685),
    ]
    assert soundtrack_quiet.lengthen_inner_quiet(audio, items, text, groups, rate, None)[2] == []


def test_a_long_run_of_speech_breathes_at_the_mark_nearest_its_middle():
    rate = 1000
    voiced = np.full((200, 2), 5000, dtype=np.int16)
    hush = np.full((50, 2), 120, dtype=np.int16)
    audio = np.concatenate([voiced, hush, voiced, hush, voiced, hush, voiced])
    items = [
        {"text": word, "start_time": 0.25 * index, "end_time": 0.25 * index + 0.2}
        for index, word in enumerate("一二三四")
    ]
    text, groups = "一，二，三，四。", ["一，二，三，四。"]
    breath = {"longest_group_seconds": 0.5, "pause_seconds": 0.28}
    _, _, edits = soundtrack_quiet.lengthen_inner_quiet(
        audio, items, text, groups, rate, {"，": 0.16}, breath
    )
    assert [(e["breath"], e["inserted_quiet_samples"]) for e in edits] == [
        (False, 110),
        (True, 230),
        (False, 110),
    ]
    # A run within the breath group needs no breath.
    breath["longest_group_seconds"] = 1.0
    _, _, edits = soundtrack_quiet.lengthen_inner_quiet(
        audio, items, text, groups, rate, {"，": 0.16}, breath
    )
    assert not any(e["breath"] for e in edits)


def test_a_clip_begins_in_the_heard_quiet_before_its_voice():
    rate = 1000
    quiet = np.full((300, 2), 20, np.int16)
    breath = np.full((150, 2), 1500, np.int16)
    voice = np.full((400, 2), 5000, np.int16)
    # The aligner places the first word after a breath that starts 0.15 s before it,
    # so the fixed 0.10 s lead would start the clip inside the breath.
    late = np.concatenate([quiet, breath, voice])
    assert soundtrack_quiet.clip_start(late, 0.50, rate) == 290
    # A lead already heard as quiet is kept.
    assert soundtrack_quiet.clip_start(np.concatenate([quiet, quiet, voice]), 0.45, rate) == 350
    assert soundtrack_quiet.clip_start(np.concatenate([quiet, voice]), 0.05, rate) == 0
    # Quiet is heard at most -55 dBFS: a lead of PCM 120 (about -49 dBFS) is not quiet,
    # and a take heard from its first sample has no quiet to begin in.
    hushed = np.concatenate([np.full((300, 2), 120, np.int16), voice])
    assert soundtrack_quiet.clip_start(hushed, 0.40, rate) is None
    assert soundtrack_quiet.clip_start(voice, 0.0, rate) is None


def test_a_take_is_heard_before_a_stop_while_its_last_10_ms_are_heard():
    rate = 1000
    voiced = np.full((200, 2), 5000, dtype=np.int16)
    cut = np.concatenate([voiced, np.zeros((300, 2), np.int16)])
    assert soundtrack_quiet.heard_before(cut, 200, rate)
    # A recording that has already decayed below heard quiet is not heard at the stop.
    decayed = np.concatenate([voiced, np.full((100, 2), 10, np.int16)])
    assert not soundtrack_quiet.heard_before(decayed, 300, rate)
    assert not soundtrack_quiet.heard_before(decayed, 0, rate)
    # A release fades the samples before the stop to silence and leaves the rest.
    released = soundtrack_quiet.release_tail(cut, 200, rate)
    assert released == 60
    assert np.array_equal(cut[:140], voiced[:140])
    assert np.all(np.diff(cut[140:200, 0].astype(int)) <= 0)


def test_quiet_runs_are_the_longest_in_their_window():
    mask = np.array([False, True, True, False, True, True, False, True])
    assert soundtrack_quiet.longest_run(mask) == (1, 3)
    assert soundtrack_quiet.longest_run(np.zeros(4, bool)) is None
    audio = np.concatenate(
        [np.full((10, 2), 5000), np.full((5, 2), 260), np.full((3, 2), 261), np.zeros((7, 2))]
    ).astype(np.int16)
    # A peak of at most 260 is native quiet; the run is counted within the window only.
    assert soundtrack_quiet.native_quiet_run(audio, 0, len(audio)) == (18, 25)
    assert soundtrack_quiet.native_quiet_run(audio, 5, 16) == (10, 15)
    assert soundtrack_quiet.native_quiet_run(audio, 16, 16) is None
    left, right = {"end_time": 0.1}, {"start_time": 0.3}
    assert soundtrack_quiet.join_window(left, right, 1000, 1000) == (35, 365)
    assert soundtrack_quiet.join_window(left, right, 1000, 300) == (35, 300)


def test_spliced_quiet_moves_the_aligned_times_after_it():
    audio = np.arange(20, dtype=np.int16).reshape(10, 2)
    # Three samples of digital quiet at sample 2, and three samples removed around sample 6.
    shifts = [(2, 3), (6, -3)]
    spliced = soundtrack_quiet.splice_quiet(audio, shifts)
    assert spliced[:, 0].tolist() == [0, 2, 0, 0, 0, 4, 6, 14, 16, 18]
    items = [{"text": "a", "start_time": 0.001, "end_time": 0.002}]
    items.append({"text": "b", "start_time": 0.008, "end_time": 0.009})
    moved = soundtrack_quiet.shifted_items(items, shifts, 1000)
    assert [(item["start_time"], item["end_time"]) for item in moved] == [
        (0.001, 0.005),
        (0.008, 0.009),
    ]


def test_a_clip_ends_in_the_heard_quiet_after_its_voice():
    rate = 1000
    voice = np.full((400, 2), 5000, np.int16)
    tail = np.full((150, 2), 1500, np.int16)
    quiet = np.full((300, 2), 20, np.int16)
    # The last syllable sounds on past the tail guard after its aligned end, so the clip
    # keeps it whole and ends once 10 ms of heard quiet follow it.
    assert soundtrack_quiet.clip_end(np.concatenate([voice, tail, quiet]), 0.25, 0.3, rate) == 560
    # A guard that already ends in quiet ends the clip.
    assert soundtrack_quiet.clip_end(np.concatenate([voice, quiet, quiet]), 0.35, 0.3, rate) == 650
    # A voice heard to the recording's end, or past the wait, ends the clip there.
    assert soundtrack_quiet.clip_end(voice, 0.1, 0.3, rate) == 400
    long = np.full((2000, 2), 5000, np.int16)
    assert soundtrack_quiet.clip_end(long, 0.2, 0.3, rate) == 1000
