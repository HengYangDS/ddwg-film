"""Narration program level, loudness and boundary fades."""

import wave

import numpy as np
import pytest

import ddwg_film.soundtrack.level as soundtrack_level
import ddwg_film.specification as specification


def test_successor_boundary_fades_preserve_occupied_native_phrase_tails():
    source = np.zeros((1000, 2), dtype=np.int16)
    source[:96] = 3
    source[-96:] = np.arange(96, dtype=np.int16)[:, None] * 40
    result, evidence = soundtrack_level.fade_narration_boundaries(source)
    assert evidence["head"]["state"] == "faded_quiet"
    assert evidence["tail"]["state"] == "native_preserved"
    assert evidence["tail"]["fade_samples"] == 0
    assert np.array_equal(result[-96:], source[-96:])
    occupied = np.max(np.abs(source.astype(np.int32)), axis=1) > 260
    assert np.array_equal(result[occupied], source[occupied])


def test_measured_narration_level_keeps_timing_and_refuses_clipping():
    samples = np.array([[1000, -1000], [0, 0], [2400, -2400]], dtype=np.int16)
    assert soundtrack_level.correct_narration_level(samples, 0) is samples
    adjusted = soundtrack_level.correct_narration_level(samples, 1.36)
    assert adjusted.shape == samples.shape
    assert adjusted.dtype == samples.dtype
    assert np.array_equal(adjusted, np.rint(samples * 10 ** (1.36 / 20)).astype(np.int16))
    assert np.array_equal(adjusted[:, 0], -adjusted[:, 1])
    with pytest.raises(ValueError, match="clip"):
        soundtrack_level.correct_narration_level(np.array([[32700, -32700]], dtype=np.int16), 1.36)
    for gain in [float("nan"), float("inf"), 2.1]:
        with pytest.raises(ValueError, match="finite gain"):
            soundtrack_level.correct_narration_level(samples, gain)


def test_a_gain_rounds_every_sample_and_names_what_would_clip():
    samples = np.array([[1000, -1000], [16000, -16000]], dtype=np.int16)
    assert soundtrack_level.apply_gain(samples, 0, "Program level") is samples
    raised = soundtrack_level.apply_gain(samples, 6.0, "Program level")
    assert np.array_equal(raised, np.rint(samples * 10 ** (6.0 / 20)).astype(np.int16))
    with pytest.raises(soundtrack_level.LevelError, match="Program level would clip"):
        soundtrack_level.apply_gain(samples, 6.3, "Program level")


@pytest.mark.ffmpeg
def test_program_level_reaches_target_unless_true_peak_caps_it(tmp_path):
    def gain(integrated, true_peak):
        return soundtrack_level.program_gain(
            {"integrated_lufs": integrated, "true_peak_dbtp": true_peak}
        )

    assert gain(-19.7, -5.8) == 3.2
    assert gain(-21.1, -2.0) == 1.0
    for integrated in (-40.0, float("-inf")):
        with pytest.raises(ValueError, match="finite gain"):
            gain(integrated, -30.0)
    rate = specification.RATE
    tone = np.rint(np.sin(2 * np.pi * 997 * np.arange(rate * 4) / rate) * 3000)
    path = tmp_path / "tone.wav"

    def measure(samples):
        stereo = np.column_stack([samples, samples]).astype("<i2")
        with wave.open(str(path), "wb") as audio:
            audio.setparams((2, 2, rate, 0, "NONE", "not compressed"))
            audio.writeframes(stereo.tobytes())
        return soundtrack_level.measure_program_level(path)

    before = measure(tone)
    after = measure(np.rint(tone * 10 ** (soundtrack_level.program_gain(before) / 20)))
    level = specification.PROGRAM_LEVEL
    assert abs(after["integrated_lufs"] - level["integrated_lufs"]) < 0.1
    assert after["true_peak_dbtp"] <= level["true_peak_ceiling_dbtp"]


def test_loudness_follows_bs1770_for_a_reference_tone():
    rate = 48000
    tone = np.sin(2 * np.pi * 997 * np.arange(2 * rate) / rate)
    left = np.stack([np.round(32767 * tone), np.zeros_like(tone)], axis=1).astype(np.int16)
    both = np.round(np.stack([3277 * tone] * 2, axis=1)).astype(np.int16)
    assert abs(soundtrack_level.loudness_lufs(left, rate) + 3.01) < 0.05
    assert abs(soundtrack_level.loudness_lufs(both, rate) + 20.0) < 0.05
    assert soundtrack_level.loudness_lufs(left[: rate // 4], rate) is None
    assert soundtrack_level.loudness_lufs(np.zeros((rate, 2), np.int16), rate) is None
    with pytest.raises(ValueError, match="48 kHz"):
        soundtrack_level.loudness_lufs(left, 44100)


def test_thought_levels_move_within_tolerance_by_static_gains():
    rate = 48000
    tone = np.sin(2 * np.pi * 997 * np.arange(rate) / rate)
    loud = np.round(np.stack([8000 * tone] * 2, axis=1)).astype(np.int16)
    soft = np.round(np.stack([2000 * tone] * 2, axis=1)).astype(np.int16)
    audio = np.concatenate([loud, np.zeros((rate // 2, 2), np.int16), soft])
    items = [
        {"text": "先", "start_time": 0.0, "end_time": 1.0},
        {"text": "看", "start_time": 1.5, "end_time": 2.5},
    ]
    leveled, record = soundtrack_level.level_thoughts(
        audio, items, "先。看", ["先。", "看"], rate, 1.5
    )
    assert [entry["gain_db"] for entry in record] == [-3.0, 3.0]
    assert abs(record[0]["loudness_lufs"] - record[1]["loudness_lufs"] - 12.04) < 0.05
    assert int(leveled[100, 0]) == int(np.rint(int(loud[100, 0]) * 10 ** (-3 / 20)))
    later = rate * 3 // 2 + 100
    assert int(leveled[later, 0]) == int(np.rint(int(soft[100, 0]) * 10 ** (3 / 20)))
    assert np.array_equal(leveled[rate : rate * 3 // 2], audio[rate : rate * 3 // 2])
    unchanged, none = soundtrack_level.level_thoughts(
        audio, items, "先。看", ["先。", "看"], rate, None
    )
    assert unchanged is audio
    assert none == []


def test_a_chapter_away_from_the_film_level_is_brought_within_tolerance():
    levels = {
        "body": [-21.0, -20.8, -21.2],
        "turn": [-20.9, -21.1],
        "coda": [-20.3, -20.2, -20.4],
    }
    peaks = {"body": 0.5, "turn": 0.5, "coda": 0.5}
    # The film's median thought is -20.85 LUFS; only the coda lies beyond 0.3 dB of it.
    assert soundtrack_level.chapter_level_gains(levels, peaks, 0.3) == {
        "body": 0.0,
        "turn": 0.0,
        "coda": -0.25,
    }
    assert soundtrack_level.chapter_level_gains(levels, peaks, None) == {
        "body": 0.0,
        "turn": 0.0,
        "coda": 0.0,
    }
    # A quieter chapter is raised only as far as its peak stays below -1 dBFS.
    quiet = {"loud": [-21.0, -21.0], "soft": [-22.0, -22.0]}
    assert soundtrack_level.chapter_level_gains(quiet, {"loud": 0.5, "soft": 0.88}, 0.3) == {
        "loud": -0.2,
        "soft": 0.11,
    }
    # A chapter without a measured thought keeps its level.
    assert (
        soundtrack_level.chapter_level_gains(
            {**quiet, "card": []}, {"loud": 0.5, "soft": 0.88, "card": 0.1}, 0.3
        )["card"]
        == 0.0
    )
