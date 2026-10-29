"""Measure and set the narration's levels: thoughts, chapters, program level and boundary fades."""

from __future__ import annotations

import math
from itertools import pairwise
from typing import TYPE_CHECKING

import numpy as np

import filmkit.media as media
from filmkit.narration.spoken_units import thought_spans
from filmkit.soundtrack.quiet import QUIET_PCM
from filmkit.specification import PROGRAM_LEVEL

if TYPE_CHECKING:
    from pathlib import Path

# A raised level keeps its peak below -1 dBFS.
PEAK_CEILING_DBFS = -1.0
# The most a static gain moves a thought, and a chapter.
THOUGHT_GAIN_LIMIT_DB = 3.0
CHAPTER_GAIN_LIMIT_DB = 2.0


class LevelError(ValueError):
    """A level gain that is not finite and bounded, or that would clip the narration."""


def apply_gain(samples: np.ndarray, gain_db: float, name: str) -> np.ndarray:
    """Scale 16-bit samples by a gain in dB, rounding each one, and refuse to clip any."""
    if gain_db == 0:
        return samples
    scaled = samples.astype(np.float64)
    scaled *= 10 ** (gain_db / 20)
    np.rint(scaled, out=scaled)
    if scaled.min(initial=0) < -32768 or scaled.max(initial=0) > 32767:
        msg = f"{name} would clip"
        raise LevelError(msg)
    return scaled.astype(np.int16)


def correct_narration_level(samples: np.ndarray, gain_db: float) -> np.ndarray:
    """Apply a measured, bounded level correction without changing sample timing."""
    if not isinstance(gain_db, (int, float)) or not np.isfinite(gain_db) or abs(gain_db) > 2:
        msg = "Narration level correction needs a finite gain within 2 dB"
        raise LevelError(msg)
    return apply_gain(samples, gain_db, "Narration level correction")


def measure_program_level(path: Path) -> dict:
    """Measure integrated loudness and true peak (ITU-R BS.1770 through FFmpeg)."""
    level = media.loudness(path, timeout=900)
    return {key: level[key] for key in ("integrated_lufs", "true_peak_dbtp")}


def program_gain(measured: dict, level: dict = PROGRAM_LEVEL) -> float:
    """One gain that reaches the program level unless the true-peak ceiling caps it."""
    gain = min(
        level["integrated_lufs"] - measured["integrated_lufs"],
        level["true_peak_ceiling_dbtp"] - measured["true_peak_dbtp"],
    )
    if not math.isfinite(gain) or abs(gain) > 12:
        msg = "Program level needs a finite gain within 12 dB"
        raise LevelError(msg)
    return round(gain, 2)


def fade_narration_boundaries(samples: np.ndarray) -> tuple[np.ndarray, dict]:
    """Fade only quiet successor boundaries while retaining occupied native tails."""
    result = samples.copy()
    count = min(96, len(result) // 2)
    evidence = {"maximum_fade_samples": count}
    for name, section, envelope in (
        ("head", slice(0, count), np.linspace(0, 1, count)),
        ("tail", slice(len(result) - count, len(result)), np.linspace(1, 0, count)),
    ):
        maximum = int(np.abs(result[section].astype(np.int32)).max(initial=0))
        applied = maximum <= QUIET_PCM
        if applied:
            result[section] = (result[section] * envelope[:, None]).astype(np.int16)
        evidence[name] = {
            "maximum_pcm": maximum,
            "fade_samples": count if applied else 0,
            "state": "faded_quiet" if applied else "native_preserved",
        }
    return result, evidence


# ITU-R BS.1770-4 K-weighting at 48 kHz: a high-shelf pre-filter, then the RLB
# high-pass.
K_WEIGHTING = (
    (
        (1.53512485958697, -2.69169618940638, 1.19839281085285),
        (1.0, -1.69065929318241, 0.73248077421585),
    ),
    ((1.0, -2.0, 1.0), (1.0, -1.99004745483398, 0.99007225036621)),
)


def loudness_lufs(audio: np.ndarray, rate: int) -> float | None:
    """Measure the gated integrated loudness of 48 kHz PCM by ITU-R BS.1770-4.

    The K-weighting filters are applied in the frequency domain, with at least a second
    of zero padding for their decay. Blocks of 400 ms every 100 ms pass the absolute
    -70 LUFS gate and the relative gate 10 LU below their mean; a span shorter than one
    block, or with no block above the gates, has no loudness.
    """
    if rate != 48000:
        msg = "K-weighting is declared for 48 kHz audio"
        raise LevelError(msg)
    block, hop = round(0.4 * rate), round(0.1 * rate)
    if len(audio) < block:
        return None
    size = 1 << (len(audio) + rate - 1).bit_length()
    delay = np.exp(-2j * np.pi * np.arange(size // 2 + 1) / size)
    response = np.ones_like(delay)
    for (b0, b1, b2), (_, a1, a2) in K_WEIGHTING:
        response *= (b0 + delay * (b1 + delay * b2)) / (1 + delay * (a1 + delay * a2))
    signal = audio.reshape(len(audio), -1).astype(np.float64) / 32768
    weighted = np.fft.irfft(np.fft.rfft(signal, size, axis=0) * response[:, None], size, axis=0)[
        : len(audio)
    ]
    energy = np.concatenate([np.zeros((1, weighted.shape[1])), np.cumsum(weighted**2, axis=0)])
    starts = np.arange(0, len(audio) - block + 1, hop)
    power = ((energy[starts + block] - energy[starts]) / block).sum(axis=1)
    level = -0.691 + 10 * np.log10(np.maximum(power, 1e-30))
    gated = power[level > -70]
    if not len(gated):
        return None
    relative = -0.691 + 10 * math.log10(gated.mean()) - 10
    return float(-0.691 + 10 * math.log10(power[(level > -70) & (level > relative)].mean()))


def _toleranced_gain(offset: float, tolerance_db: float, limit_db: float, peak: float) -> float:
    """The static gain that moves a level offset to the edge of its tolerance, in dB.

    The gain moves by at most the limit, and a raised level keeps its peak, as a fraction of
    full scale, below -1 dBFS.
    """
    gain = max(-limit_db, min(limit_db, offset - math.copysign(tolerance_db, offset)))
    if gain > 0 and peak > 0:
        gain = min(gain, 20 * math.log10(10 ** (PEAK_CEILING_DBFS / 20) / peak))
    return round(max(gain, -limit_db), 2)


def chapter_level_gains(
    levels: dict[str, list[float]], peaks: dict[str, float], tolerance_db: float | None
) -> dict[str, float]:
    """One static gain per chapter that brings its level within tolerance of the film's.

    A chapter's level is the median loudness of its leveled thoughts, and the film's
    level is the median over every thought. A chapter beyond the tolerance moves to its
    edge, by at most 2 dB, and a raised chapter keeps its peak below -1 dBFS. A chapter
    without a measured thought keeps its level.
    """
    measured = [level for values in levels.values() for level in values]
    reference = float(np.median(measured)) if measured else 0.0
    gains = {}
    for chapter, values in levels.items():
        offset = reference - float(np.median(values)) if values else 0.0
        gains[chapter] = (
            _toleranced_gain(offset, tolerance_db, CHAPTER_GAIN_LIMIT_DB, peaks[chapter])
            if tolerance_db is not None and abs(offset) > tolerance_db
            else 0.0
        )
    return gains


def level_thoughts(
    audio: np.ndarray,
    items: list[dict],
    text: str,
    groups: list[str],
    rate: int,
    tolerance_db: float | None,
) -> tuple[np.ndarray, list[dict]]:
    """Level each thought within tolerance of its segment by one static gain.

    A thought's level is the BS.1770 loudness of its aligned speech, and the reference
    is the median of those levels. A gain changes at the midpoint of the quiet between
    two thoughts and never exceeds 3 dB or the headroom below -1 dBFS, so timing and
    dynamics within a thought are untouched.
    """
    spans = [
        (items[span.first]["start_time"], items[span.last]["end_time"])
        for span in thought_spans(text, items, groups)
    ]
    if tolerance_db is None or len(groups) < 2:
        return audio, []
    levels = [
        loudness_lufs(audio[round(begin * rate) : round(end * rate)], rate) for begin, end in spans
    ]
    measured = [level for level in levels if level is not None]
    reference = float(np.median(measured)) if measured else 0.0
    cuts = (
        [0]
        + [round((left[1] + right[0]) / 2 * rate) for left, right in pairwise(spans)]
        + [len(audio)]
    )
    result, record = audio.astype(np.float64), []
    for index, level in enumerate(levels):
        gain = 0.0
        if level is not None and abs(reference - level) > tolerance_db:
            part = result[cuts[index] : cuts[index + 1]]
            peak = float(np.abs(part).max(initial=0)) / 32768
            gain = _toleranced_gain(reference - level, tolerance_db, THOUGHT_GAIN_LIMIT_DB, peak)
            result[cuts[index] : cuts[index + 1]] = part * 10 ** (gain / 20)
        record.append(
            {
                "thought_group_index": index + 1,
                "loudness_lufs": None if level is None else round(level, 2),
                "reference_lufs": round(reference, 2),
                "gain_db": gain,
            }
        )
    return np.clip(np.rint(result), -32768, 32767).astype(audio.dtype), record
