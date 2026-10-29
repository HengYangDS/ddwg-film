"""Exercise the review measurements on a synthetic narration and small fixtures."""

import subprocess
import sys
import wave

import numpy as np
import pytest

import ddwg_film.picture.rendering as picture_rendering
import ddwg_film.picture.sync_audit as picture_sync_audit
import ddwg_film.repository as repository
import ddwg_film.review.endings as review_endings
import ddwg_film.review.measurement as review_measurement
import ddwg_film.review.support as review_support
from ddwg_film.production import Edition
from ddwg_film.review import ReviewError

RATE = 48000
# Each segment's words: text, start, end and the release that ends a thought.
WORDS = {
    "01": [
        ("Read", 0.20, 0.50, 0),
        ("the", 0.50, 0.70, 0),
        ("data.", 0.85, 1.20, 0.03),
        ("Then", 1.60, 1.90, 0),
        ("decide.", 1.90, 2.60, 0.03),
    ],
    "02": [
        ("Ship", 3.20, 3.60, 0),
        ("it.", 3.60, 4.00, 0.03),
        ("Check", 4.50, 5.00, 0),
        ("it.", 5.13, 5.60, 0.03),
    ],
}
THOUGHTS = {"01": ["Read the data. ", "Then decide."], "02": ["Ship it. ", "Check it."]}
CHINESE = {
    "01": (["读数据。", "再决定。"], ["读", "数", "据。", "再决", "定。"]),
    "02": (["发布。", "检查。"], ["发", "布。", "检", "查。"]),
}


def voiced(seconds, release):
    """A 200 Hz voice whose level swells five times a second, released over its last seconds."""
    t = np.arange(round(seconds * RATE)) / RATE
    swell = 0.6 + 0.4 * np.sin(2 * np.pi * 5 * t - np.pi / 2)
    voice = sum(
        weight * np.sin(2 * np.pi * hz * t) for hz, weight in ((200, 1), (400, 0.5), (600, 0.25))
    )
    signal = 0.25 * swell * voice
    if release:
        signal[-round(release * RATE) :] *= np.linspace(1, 0, round(release * RATE))
    return signal


def spoken(dying=voiced):
    """Six seconds of the words of WORDS, each thought's last word ended by `dying`."""
    mono = np.zeros(6 * RATE)
    for words in WORDS.values():
        for _, start, end, release in words:
            piece = dying(end - start, release) if release else voiced(end - start, 0)
            mono[round(start * RATE) : round(start * RATE) + len(piece)] = piece
    return mono


def write_narration(path, mono):
    """A stereo narration of mono samples, the second channel at 80%."""
    pcm = np.round(np.stack([mono, 0.8 * mono], axis=1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(2)
        audio.setsampwidth(2)
        audio.setframerate(RATE)
        audio.writeframes(pcm.tobytes())
    return path


@pytest.fixture
def narration(tmp_path):
    """A six-second stereo narration of two segments, its timeline and its assembly.

    Each segment holds two thoughts heard apart by 0.4 s and 0.5 s of digital zero; the
    first thought of 01 and the second of 02 hold an inner quiet of 0.15 s and 0.13 s.
    """
    path = write_narration(tmp_path / "narration.wav", spoken())
    timeline = {
        "segments": [
            {
                "id": name,
                "chapter": "one" if name == "01" else "two",
                "text": "".join(THOUGHTS[name]),
                "utterance_groups": THOUGHTS[name],
                "voice_start": words[0][1],
                "voice_end": words[-1][2],
                "words": [{"text": text, "start": a, "end": b} for text, a, b, _ in words],
            }
            for name, words in WORDS.items()
        ]
    }
    assembly = {
        "designed_pause_policy": {"boundary_ratio": 1.2},
        "records": [
            {
                "id": name,
                "designed_thought_pauses": [
                    {
                        "thought_group_index": 1,
                        "designed_quiet_seconds": designed,
                        "inner_quiet_seconds": inner,
                    }
                ],
            }
            for name, designed, inner in (("01", 0.42, 0.15), ("02", 0.52, 0.13))
        ],
    }
    return path, timeline, assembly


def test_the_audio_structure_reports_what_reviewers_read(narration):
    path, timeline, assembly = narration
    structure = review_measurement.audio_structure("en", path, timeline, assembly)
    assert structure == {
        "method": review_measurement.STRUCTURE_METHOD,
        "designed_pause_hierarchy": {
            "joins": 2,
            "longer_than_inner_quiet": 2,
            "measured_inner_quiet": 2,
            "median_ratio_to_inner_quiet": 3.4,
        },
        "heard_pause_hierarchy": {
            "thought_boundaries": 2,
            "boundary_not_longer_than_longest_inner_quiet": 0,
            "boundary_quiet_seconds": {"count": 2, "min": 0.4, "median": 0.45, "max": 0.5},
            "inner_quiet_of_at_least_120_ms_seconds": {
                "count": 2,
                "min": 0.13,
                "median": 0.14,
                "max": 0.15,
            },
        },
        "boundary_to_inner_quiet_ratio": {
            "method": review_measurement.RATIO_METHOD,
            "boundaries": 2,
            "lowest": [
                {
                    "boundary": "01.1>01.2",
                    "ratio": 2.67,
                    "heard_seconds": 0.4,
                    "inner_seconds": 0.15,
                },
                {
                    "boundary": "02.1>02.2",
                    "ratio": 3.85,
                    "heard_seconds": 0.5,
                    "inner_seconds": 0.13,
                },
            ],
            "declared_ratio": 1.2,
            "below_declared_ratio": 0,
            "designed_minus_heard_seconds": {"count": 2, "median": 0.02, "p90": 0.02, "max": 0.02},
        },
        # Every word but the thoughts' released last ones enters and leaves digital zero
        # at full level; three of the words entering it end in the trough of their swell,
        # so only two step at the zero itself.
        "quiet_edges": {
            "digital_zero_runs_of_20_ms_or_more": 7,
            "edge_window_ms": 5,
            "entered_above_minus_45_dbfs": 5,
            "left_above_minus_45_dbfs": 6,
            "step_window_ms": 1,
            "entered_with_a_step_above_minus_45_dbfs": 2,
            "left_with_a_step_above_minus_45_dbfs": 6,
        },
        "level_continuity": {
            "method": review_measurement.LEVEL_METHOD,
            "thoughts": 4,
            "median_absolute_step_lu": 0.82,
            "p90_absolute_step_lu": 0.99,
            "largest_steps": [("01.2", 1.03), ("02.2", -0.82), ("02.1", 0.06)],
        },
        "chapter_profile": {
            "one": {
                "units_per_articulated_second": 2.7,
                "acoustic_syllables_per_articulated_second": 5.95,
                "median_f0_hz": 200.0,
                "f0_p10_p90_semitones": 0.0,
                "median_level_dbfs": -20.2,
            },
            "two": {
                "units_per_articulated_second": 2.26,
                "acoustic_syllables_per_articulated_second": 5.65,
                "median_f0_hz": 200.0,
                "f0_p10_p90_semitones": 0.0,
                "median_level_dbfs": -20.2,
            },
        },
    }
    # Chinese characters are written syllables, so the Chinese profile validates the
    # acoustic count against them.
    for segment in timeline["segments"]:
        groups, words = CHINESE[segment["id"]]
        segment["utterance_groups"], segment["text"] = groups, "".join(groups)
        for word, text in zip(segment["words"], words, strict=True):
            word["text"] = text
    profile = review_measurement.audio_structure("zh", path, timeline, assembly)["chapter_profile"]
    assert {name: chapter["units_per_articulated_second"] for name, chapter in profile.items()} == {
        "one": 3.24,
        "two": 2.26,
    }
    assert {
        name: chapter["acoustic_per_written_syllable"] for name, chapter in profile.items()
    } == {
        "one": 1.833,
        "two": 2.5,
    }


def test_thought_spans_are_filled_by_their_aligned_words(narration):
    _, timeline, _ = narration
    spans = [review_support.thought_spans(segment) for segment in timeline["segments"]]
    assert spans == [[(0.2, 1.2), (1.6, 2.6)], [(3.2, 4.0), (4.5, 5.6)]]
    # A word past the last thought is refused by name rather than indexing past the thoughts.
    segment = timeline["segments"][1]
    segment["words"].append({"text": "Again.", "start": 5.7, "end": 5.9})
    with pytest.raises(ReviewError, match="02: Alignment does not cover exact text"):
        review_support.thought_spans(segment)


def dies_away(seconds, _release):
    """A voiced word whose last quarter second dies away to below -80 dBFS, as speech ends."""
    piece = voiced(seconds, 0)
    tail = round(0.25 * RATE)
    piece[-tail:] *= np.exp(-np.arange(tail) / (0.027 * RATE))
    return piece


def test_delivered_endings_judge_each_thought_where_its_sound_stops(narration, tmp_path):
    _, timeline, _ = narration
    # Each thought dies away into the digital zero that follows it.
    path = write_narration(tmp_path / "natural.wav", spoken(dies_away))
    assert review_endings.delivered_endings(path, timeline) == {
        "thoughts": 4,
        "natural": 4,
        "abrupt": [],
        "released": [],
        "cut_while_voiced": [],
    }
    # A thought whose last word is cut at full voice ends abruptly as delivered, though its
    # sound stops at the same zero.
    mono = spoken(dies_away)
    second = round(1.90 * RATE)
    mono[second : second + round(0.70 * RATE)] = voiced(0.70, 0)
    path = write_narration(tmp_path / "cut.wav", mono)
    cut = review_endings.delivered_endings(path, timeline)
    assert cut == {
        "thoughts": 4,
        "natural": 3,
        "abrupt": ["01.2"],
        "released": [],
        "cut_while_voiced": [],
    }
    # Released over its last 60 ms, the cut voice reaches the zero quietly, but it is heard at
    # nearly full voice where the release begins.
    release = round(0.06 * RATE)
    mono[second + round(0.70 * RATE) - release : second + round(0.70 * RATE)] *= 0.5 + 0.5 * np.cos(
        np.pi * np.arange(1, release + 1) / (release + 1)
    )
    path = write_narration(tmp_path / "released.wav", mono)
    released = review_endings.delivered_endings(path, timeline, released={"01.2"})
    assert released["released"] == ["01.2"]
    assert released["cut_while_voiced"] == ["01.2"]
    # A thought that dies away by itself is never judged where no release began.
    path = write_narration(tmp_path / "natural.wav", spoken(dies_away))
    assert (
        review_endings.delivered_endings(path, timeline, released={"01.1"})["cut_while_voiced"]
        == []
    )
    # Joined without digital zero to the next thought, a thought is delivered up to one
    # aligner step before the next one's aligned first word, which may begin that early.
    mono = spoken(dies_away)
    rng = np.random.default_rng(1)
    gap = slice(round(1.2 * RATE), round(1.6 * RATE))
    mono[gap] = rng.standard_normal(gap.stop - gap.start) * 10 ** (-70 / 20)
    mono[round(1.55 * RATE) : round(1.6 * RATE)] = voiced(0.05, 0)
    path = write_narration(tmp_path / "joined.wav", mono)
    assert review_endings.delivered_endings(path, timeline)["abrupt"] == []
    # Room quiet at -52 dBFS after the second thought's last word is heard through a 4.5 dB
    # program gain; with the gain taken out it lies below the takes' -55 dBFS.
    mono = spoken(dies_away)
    rng = np.random.default_rng(0)
    room = rng.standard_normal(round(0.2 * RATE)) * 10 ** (-52 / 20)
    mono[round(2.60 * RATE) : round(2.80 * RATE)] = room
    path = write_narration(tmp_path / "room.wav", mono)
    assert review_endings.delivered_endings(path, timeline)["abrupt"] == ["01.2"]
    assert review_endings.delivered_endings(path, timeline, 4.5)["abrupt"] == []


def test_phrase_endings_list_a_phrase_cut_before_the_pause_inside_its_thought(tmp_path):
    words = [("Read", 0.2, 0.5), ("the", 0.5, 0.7), ("data", 0.7, 1.2), ("then", 1.4, 1.7)]
    words.append(("decide", 1.7, 2.4))
    segment = {
        "id": "01",
        "text": "Read the data, then decide.",
        "utterance_groups": ["Read the data, then decide."],
        "words": [{"text": text, "start": a, "end": b} for text, a, b in words],
    }
    timeline = {"segments": [segment]}

    def narrated(phrase_end):
        mono = np.zeros(3 * RATE)
        mono[round(0.2 * RATE) : round(0.7 * RATE)] = voiced(0.5, 0)
        mono[round(0.7 * RATE) : round(1.2 * RATE)] = phrase_end(0.5, 0)
        mono[round(1.4 * RATE) : round(2.4 * RATE)] = dies_away(1.0, 0)
        return write_narration(tmp_path / f"{phrase_end.__name__}.wav", mono)

    # The comma's 0.2 s of quiet follows "data", cut at full voice inside the thought.
    cut = review_endings.phrase_endings(narrated(voiced), timeline)
    assert [(end["thought"], end["word"]) for end in cut["stopped"]] == [("01.1", "data,")]
    assert cut["heard"] == 1
    assert review_endings.phrase_endings(narrated(dies_away), timeline)["stopped"] == []


def test_the_thoughts_an_assembly_released_are_named_by_their_joins_and_clip_ends():
    timeline = {
        "segments": [
            {"id": "01", "utterance_groups": ["甲。", "乙。", "丙。"]},
            {"id": "02", "utterance_groups": ["丁。", "戊。"]},
        ]
    }
    assembly = {
        "records": [
            {
                "id": "01",
                "designed_thought_pauses": [
                    {"thought_group_index": 1, "released_tail_samples": 0},
                    {"thought_group_index": 2, "released_tail_samples": 2880},
                ],
                "boundary_fades": {"released_tail_samples": 0},
            },
            {
                "id": "02",
                "designed_thought_pauses": [{"thought_group_index": 1, "released_tail_samples": 0}],
                "boundary_fades": {"released_tail_samples": 2880},
            },
        ]
    }
    assert review_endings.released_thoughts(assembly, timeline) == {"01.2", "02.2"}


def thoughts(name, words):
    """A segment whose thoughts are single aligned words."""
    return {
        "id": name,
        "text": "".join(text for text, _, _ in words),
        "utterance_groups": [text for text, _, _ in words],
        "words": [{"text": text, "start": a, "end": b} for text, a, b in words],
    }


def test_boundary_ratios_weigh_each_heard_boundary_against_the_quiet_beside_it():
    # Quiet 10 ms frames: runs inside thoughts and across their boundaries. The longer
    # inner quiet lies before some boundaries and after others; 02 has none beside it.
    quiet = np.zeros(1000, bool)
    for start, stop in (
        (30, 50),
        (100, 150),
        (180, 190),
        (250, 263),
        (320, 332),
        (500, 540),
        (660, 680),
        (700, 720),
        (900, 940),
        (960, 990),
    ):
        quiet[start:stop] = True
    segments = [
        thoughts("01", [("ab", 0.0, 1.0), ("cd", 1.5, 2.5), ("ef", 3.0, 4.0)]),
        thoughts("02", [("gh", 4.5, 5.0), ("ij", 5.5, 6.0)]),
        thoughts("03", [("kl", 6.5, 7.0), ("mn", 7.5, 8.0)]),
        thoughts("04", [("op", 8.5, 9.0), ("qr", 9.5, 10.0)]),
    ]
    designed = {"01": [0.6, 0.2], "02": [0.45], "03": [0.25], "04": [0.52]}
    assembly = {
        "designed_pause_policy": {"boundary_ratio": 1.2},
        "records": [
            {
                "id": name,
                "designed_thought_pauses": [
                    {"thought_group_index": index, "designed_quiet_seconds": seconds}
                    for index, seconds in enumerate(pauses, 1)
                ],
            }
            for name, pauses in designed.items()
        ],
    }
    summary = review_measurement.boundary_ratios(quiet, segments, assembly)
    assert summary["boundaries"] == 5
    assert [
        (row["boundary"], row["ratio"], row["heard_seconds"], row["inner_seconds"])
        for row in summary["lowest"]
    ] == [
        ("03.1>03.2", 1.0, 0.2, 0.2),
        ("01.2>01.3", 1.08, 0.13, 0.12),
        ("04.1>04.2", 1.33, 0.4, 0.3),
        ("01.1>01.2", 2.5, 0.5, 0.2),
    ]
    # Boundaries are counted against the edition's declared ratio.
    assert (summary["declared_ratio"], summary["below_declared_ratio"]) == (1.2, 2)
    assembly["designed_pause_policy"]["boundary_ratio"] = 1.62
    assert (
        review_measurement.boundary_ratios(quiet, segments, assembly)["below_declared_ratio"] == 3
    )
    assert summary["designed_minus_heard_seconds"] == {
        "count": 5,
        "median": 0.07,
        "p90": 0.112,
        "max": 0.12,
    }


def test_the_measured_sync_carries_its_continuity_and_binds_its_sources(root, put):
    # The review reads unnamed speech, held pictures and seats from the measurements, and
    # only from an audit of the current timeline drawn by the current composition.
    edition = Edition("zh")
    composition = put(root / picture_rendering.COMPOSITION_SCRIPT, "/* film */")
    continuity = {"unnamed_speech": [], "held_over": [], "seats": []}
    report = dict.fromkeys(picture_sync_audit.SUMMARY_KEYS, 0)
    report |= {"findings": [], "continuity": continuity, "bound_timeline": {"sha256": "ab"}}
    put(edition.picture_sync, report | {"composition_sha256": repository.sha(composition)})
    measured = review_measurement.picture_sync(edition, "ab")
    assert measured == {
        **dict.fromkeys(picture_sync_audit.SUMMARY_KEYS, 0),
        "findings": [],
        "continuity": continuity,
    }
    with pytest.raises(
        ReviewError, match="zh: the sync audit is not bound to the current timeline"
    ):
        review_measurement.picture_sync(edition, "cd")
    for bound in ({}, {"composition_sha256": "0" * 64}):
        put(edition.picture_sync, report | bound)
        with pytest.raises(
            ReviewError, match="zh: the sync audit is not bound to the current composition"
        ):
            review_measurement.picture_sync(edition, "ab")


@pytest.mark.usefixtures("root")
def test_the_measured_geometry_checks_the_current_staged_document(put):
    edition = Edition("en")
    staged = put(edition.picture_stage / "index.html", "<!doctype html>")
    geometry = {
        "checked": 45000,
        "step_frames": 2,
        "findings": [],
        "errors": [],
        "browser": "Chrome",
        "index_sha256": repository.sha(staged),
    }
    put(edition.picture_geometry, geometry)
    assert review_measurement.picture_geometry(edition) == {
        "geometry_frames_checked": 45000,
        "step_frames": 2,
        "findings": 0,
        "errors": 0,
        "browser": "Chrome",
        "index_sha256": repository.sha(staged),
    }
    put(staged, "<!doctype html><title>Restaged</title>")
    with pytest.raises(
        ReviewError, match="en: the picture geometry does not check the current stage"
    ):
        review_measurement.picture_geometry(edition)


def test_the_review_tools_and_the_verifier_load_no_speech_runtime():
    # They run on any host: none of them imports the MLX speech runtime, which needs a
    # Metal device. A child process imports them, since this one may hold MLX already.
    modules = (
        "ddwg_film.review.measurement",
        "ddwg_film.review.round",
        "ddwg_film.review.listening_plan",
        "ddwg_film.picture.sync_audit",
        "ddwg_film.delivery.verification",
    )
    probe = (
        "import importlib, sys\n"
        "for name in sys.argv[1:]:\n"
        "    importlib.import_module(name)\n"
        "print(sorted(m for m in sys.modules if m.partition('.')[0] in ('mlx', 'mlx_audio')))"
    )
    loaded = subprocess.run(
        [sys.executable, "-c", probe, *modules],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    )
    assert loaded.stdout.strip() == "[]"
