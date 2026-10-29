"""Design the pauses between thoughts, paragraphs and chapters of the narration.

A statement pause grows with the thought it follows and a paragraph gap with the paragraph it
follows, at their declared means. Each thought join is then set to its designed quiet inside the
part of its native quiet heard as quiet, and the remaining runtime is shared among the gaps
before each segment within their declared limits.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import pairwise

import numpy as np

from ddwg_film.narration.spoken_units import QUESTION_MARKS, item_joins, units
from ddwg_film.soundtrack.quiet import (
    FADE_SECONDS,
    RELEASE_SECONDS,
    fade_into_quiet,
    heard_before,
    heard_quiet_run,
    join_window,
    native_quiet_run,
    release_tail,
    shifted_items,
    splice_quiet,
)

# A soft edge (peak at most -24 dBFS) beside digital silence fades over 10 ms instead
# of stopping on a step.
EDGE_PCM = 2048
EDGE_FADE_SECONDS = 0.01
# Digital silence is a run of exact zeros at least this long; a lone zero sample is a
# zero crossing of the waveform, not silence.
DIGITAL_SILENCE_SECONDS = 0.01
# An edge at or below this level beside digital silence makes no step worth fading.
SILENT_EDGE_DBFS = -70.0
# A thought join holds at least this much native quiet to design.
JOIN_QUIET_SECONDS = 0.1
# Bisection steps for the one shift that keeps a pause shape at its declared mean.
SHAPE_STEPS = 80
# How far a shaped pause's mean may lie from the declared mean, in seconds.
MEAN_TOLERANCE = 1e-9


class PauseError(ValueError):
    """Pauses that cannot be designed or laid out as the pause contract declares."""


def mean_preserving_pauses(
    lengths: list[int],
    mean: float,
    low: float,
    high: float,
    floors: list[float] | None = None,
) -> list[float]:
    """Grow each pause with the square root of the length it follows, at the given mean.

    Each pause stays within [low, high] and at or above its floor, which may exceed
    high; one shift, found by bisection, keeps the mean of all pauses at the declared
    mean, so the shape changes while the total does not. Floors that the declared mean
    cannot fund are refused, as is a shape whose range cannot keep the mean.
    """
    if not lengths:
        return []
    floors = [0.0] * len(lengths) if floors is None else floors
    if len(floors) != len(lengths):
        msg = "Every pause requires one floor"
        raise PauseError(msg)
    if sum(max(low, floor) for floor in floors) > mean * len(lengths) + 1e-9:
        msg = "Thought boundaries need a larger declared statement pause"
        raise PauseError(msg)
    average = sum(lengths) / len(lengths)

    def pause(length: float, floor: float, shift: float) -> float:
        shaped = mean * math.sqrt(length / average) + shift
        return min(max(high, floor), max(low, floor, shaped))

    lower, upper = -high, high
    for _ in range(SHAPE_STEPS):
        shift = (lower + upper) / 2
        total = sum(
            pause(length, floor, shift) for length, floor in zip(lengths, floors, strict=True)
        )
        if total < mean * len(lengths):
            lower = shift
        else:
            upper = shift
    shaped = [pause(length, floor, upper) for length, floor in zip(lengths, floors, strict=True)]
    if abs(sum(shaped) - mean * len(lengths)) > MEAN_TOLERANCE * len(lengths):
        msg = "Designed pauses cannot keep their declared mean within their range"
        raise PauseError(msg)
    return shaped


def thought_pause_targets(
    segments: list[dict],
    policy: dict,
    inner: dict[str, list[float]] | None = None,
    overhead: dict[str, list[float]] | None = None,
) -> dict[str, list[float]]:
    """Give each thought join its designed quiet, in seconds, by segment.

    A question keeps the question pause. A statement pause grows with the square root of
    the spoken length of the thought it follows, within the declared range, at the
    edition's declared mean statement pause. Given the longest heard quiet inside each
    thought, every join is heard at least the declared boundary ratio longer than the
    quiet inside the thoughts on either side, so a thought boundary is always the
    stronger break. A declared coda pause is the least heard quiet after each thought of
    the closing segment, so the ending settles. A join's overhead is the part of its
    native quiet that is not heard as quiet, so its designed quiet exceeds its heard
    floor by that much, and a declared margin lengthens every floored join beyond it, so a
    measure bounded by the aligned word edges still hears it at the declared ratio.
    """
    question, ratio = policy["pauses"]["question"], policy["boundary_ratio"]
    margin = policy.get("boundary_margin", 0.0)
    inner, overhead = inner or {}, overhead or {}
    closing = segments[-1]["id"] if segments else None
    coda = policy["coda"] or 0.0

    def floor(segment: dict, index: int) -> float:
        quiet = inner.get(segment["id"], [0.0] * len(segment["utterance_groups"]))
        extra = overhead.get(segment["id"], [0.0] * len(segment["utterance_groups"]))
        heard = max(
            ratio * max(quiet[index], quiet[index + 1]),
            coda if segment["id"] == closing else 0.0,
        )
        return heard + extra[index] + margin if heard else 0.0

    joins = [
        (
            segment["id"],
            len(units(group)),
            group.rstrip()[-1:] in QUESTION_MARKS,
            floor(segment, index),
        )
        for segment in segments
        for index, group in enumerate(segment["utterance_groups"][:-1])
    ]
    statements = iter(
        mean_preserving_pauses(
            [length for _, length, asked, _ in joins if not asked],
            policy["pauses"]["thought"],
            *policy["thought_range"],
            floors=[floor for _, _, asked, floor in joins if not asked],
        )
    )
    targets: dict[str, list[float]] = {segment["id"]: [] for segment in segments}
    for segment_id, _, asked, floor in joins:
        targets[segment_id].append(max(question, floor) if asked else next(statements))
    return targets


def gap_kinds(segments: list[dict]) -> list[str]:
    """Name the gap before each segment: opening, then chapter or paragraph joins."""
    return ["opening"] + [
        "chapter" if segment["chapter"] != previous["chapter"] else "paragraph"
        for previous, segment in pairwise(segments)
    ]


def gap_pause_targets(segments: list[dict], policy: dict) -> list[float]:
    """Give the gap before each segment its designed seconds before allocation.

    Opening and chapter gaps keep their declared pauses. A paragraph gap grows with the
    square root of the spoken length of the paragraph it follows, within the declared
    range, at the declared paragraph pause, as statement pauses do.
    """
    pauses, kinds = policy["pauses"], gap_kinds(segments)
    paragraphs = iter(
        mean_preserving_pauses(
            [
                len(units(previous["text"]))
                for previous, kind in zip(segments[:-1], kinds[1:], strict=True)
                if kind == "paragraph"
            ],
            pauses["paragraph"],
            *policy["paragraph_range"],
        )
    )
    return [next(paragraphs) if kind == "paragraph" else pauses[kind] for kind in kinds]


@dataclass(frozen=True)
class ThoughtJoin:
    """A complete-thought join: its native quiet, the part of it heard as quiet, and the rest.

    `group` numbers the thought the join follows from 1; `begin` and `end` bound the native
    quiet in samples; `overhead` is the native quiet not heard as quiet, in seconds.
    """

    group: int
    begin: int
    end: int
    heard: tuple[int, int] | None
    overhead: float


def thought_joins(
    audio: np.ndarray, items: list[dict], text: str, groups: list[str], rate: int
) -> list[ThoughtJoin]:
    """Find each complete-thought join's native quiet and the part heard as quiet.

    A join's native quiet is the longest run at a peak of at most QUIET_PCM in the join
    window between the two aligned items. Within it, the heard run is the longest run of
    frames heard as quiet; the rest of the native quiet is the join's overhead.
    """
    joins = []
    for join in item_joins(text, items, groups):
        if not join.ends_thought:
            continue
        group = join.thought + 1
        window = join_window(items[join.left], items[join.right], rate, len(audio))
        run = native_quiet_run(audio, *window)
        if run is None or run[1] - run[0] < round(JOIN_QUIET_SECONDS * rate):
            msg = f"Thought join {group} has no measured quiet"
            raise PauseError(msg)
        begin, end = run
        heard = heard_quiet_run(audio, begin, end, rate)
        overhead = (end - begin - (heard[1] - heard[0] if heard else 0)) / rate
        joins.append(ThoughtJoin(group, begin, end, heard, overhead))
    return joins


def _soften(audio: np.ndarray, start: int, stop: int, *, rising: bool) -> None:
    """Fade a soft edge in place: in when rising, out otherwise; a louder edge keeps its step."""
    part = audio[max(0, start) : stop]
    if len(part) and int(np.abs(part.astype(np.int32)).max()) <= EDGE_PCM:
        ramp = 0.5 - 0.5 * np.cos(np.pi * np.arange(1, len(part) + 1) / (len(part) + 1))
        part[:] = np.round(part * (ramp if rising else ramp[::-1])[:, None]).astype(audio.dtype)


def _edge_dbfs(part: np.ndarray) -> float:
    """The RMS level of an edge's samples, in dBFS."""
    x = part.astype(np.float64) / 32768
    return float(20 * np.log10(np.sqrt(np.mean(x**2)) + 1e-12)) if x.size else -120.0


def _enter_digital_silence(
    audio: np.ndarray, join: ThoughtJoin, rate: int, release_seconds: float
) -> int:
    """Enter and leave the digital silence inside a join without a step, in place.

    Digital silence where two thought recordings meet is entered and left through a short
    fade of the soft edge beside it; a recording still heard as it reaches the silence is
    released instead, and an edge too quiet to make a step keeps its samples, so a decay
    keeps its tail. Only runs of exact zeros at least DIGITAL_SILENCE_SECONDS long are
    digital silence, so a zero crossing in a decaying voice is never taken for one. Return
    the released samples.
    """
    zero = np.all(audio[join.begin : join.end] == 0, axis=1)
    run = round(DIGITAL_SILENCE_SECONDS * rate)
    silent = np.flatnonzero(np.convolve(zero, np.ones(run, dtype=int), "valid") == run)
    if not len(silent):
        return 0
    first, last = join.begin + int(silent[0]), join.begin + int(silent[-1]) + run
    edge, released = round(EDGE_FADE_SECONDS * rate), 0
    if heard_before(audio, first, rate):
        released = release_tail(audio, first, rate, release_seconds)
    elif _edge_dbfs(audio[max(0, first - edge) : first]) > SILENT_EDGE_DBFS:
        _soften(audio, first - edge, first, rising=False)
    _soften(audio, last, last + edge, rising=True)
    return released


def _check_removal(join: ThoughtJoin, center: int, delta: int) -> None:
    """Refuse removing quiet beyond the heard quiet at a join, or its native quiet without one."""
    heard = join.heard or (join.begin, join.end)
    start = center + delta // 2
    if start < heard[0] or start - delta > heard[1]:
        msg = f"Designed quiet at thought join {join.group} would cut beyond its heard quiet"
        raise PauseError(msg)


def design_thought_pauses(
    audio: np.ndarray,
    items: list[dict],
    text: str,
    groups: list[str],
    rate: int,
    *,
    targets: list[float],
    releases: dict[int, float] | None = None,
) -> tuple[np.ndarray, list[dict], list[dict]]:
    """Set each complete-thought join to its designed quiet; speech never moves.

    Designed quiet is inserted into, or removed from, the middle of the part of the
    native quiet heard as quiet, so a decaying tail or a rising onset keeps its native
    quiet beside it. releases maps a thought's index to its declared release seconds.
    """
    joins = thought_joins(audio, items, text, groups, rate)
    if len(targets) != len(groups) - 1:
        msg = "Every thought join requires one designed pause"
        raise PauseError(msg)
    audio, fade, releases = audio.copy(), round(FADE_SECONDS * rate), releases or {}
    shifts, edits = [], []
    for join, target in zip(joins, targets, strict=True):
        released = _enter_digital_silence(
            audio, join, rate, releases.get(join.group, RELEASE_SECONDS)
        )
        designed, native = round(target * rate), join.end - join.begin
        delta = designed - native
        heard = join.heard or (join.begin, join.end)
        center = (heard[0] + heard[1]) // 2
        span = 0
        if delta >= 0:
            # The native quiet beside inserted digital quiet fades into it and back out.
            span = fade_into_quiet(audio, center, join.begin, join.end, fade)
        else:
            _check_removal(join, center, delta)
        shifts.append((center, delta))
        edits.append(
            {
                "thought_group_index": join.group,
                "source_sample": center,
                "native_quiet_seconds": native / rate,
                "heard_native_quiet_seconds": (heard[1] - heard[0]) / rate if join.heard else 0.0,
                "designed_quiet_seconds": designed / rate,
                "inserted_quiet_samples": max(0, delta),
                "removed_quiet_samples": max(0, -delta),
                "fade_samples": span,
                "released_tail_samples": released,
            }
        )
    return splice_quiet(audio, shifts), shifted_items(items, shifts, rate), edits


def allocate_designed_gaps(
    kinds: list[str],
    speech_frames: int,
    policy: dict,
    rate: int,
    total_frames: int,
    bases: list[float] | None = None,
) -> tuple[list[int], int]:
    """Give exact remaining runtime to picture gaps by weight within declared limits.

    Each gap starts from its designed seconds (by default its kind's declared pause).
    """
    pauses, limits, weights = policy["pauses"], policy["limits"], policy["weights"]
    bases = [pauses[kind] for kind in kinds] if bases is None else bases
    if len(bases) != len(kinds):
        msg = "Every gap requires one designed pause"
        raise PauseError(msg)
    gaps = [round(base * rate) for base in bases]
    caps = [round(limits[kind] * rate) for kind in kinds]
    closing = round(pauses["closing"] * rate)
    free = total_frames - speech_frames - sum(gaps) - closing
    if free < 0:
        msg = f"Narration exceeds the runtime by {-free / rate:.2f} s"
        raise PauseError(msg)
    while free:
        open_gaps = [
            index
            for index, kind in enumerate(kinds)
            if weights[kind] > 0 and gaps[index] < caps[index]
        ]
        if not open_gaps:
            msg = f"Narration is short by {free / rate:.2f} s for the declared gap limits"
            raise PauseError(msg)
        total_weight = sum(weights[kinds[index]] for index in open_gaps)
        grants = {
            index: min(
                caps[index] - gaps[index],
                int(free * weights[kinds[index]] / total_weight),
            )
            for index in open_gaps
        }
        if not any(grants.values()):
            grants = dict.fromkeys(open_gaps[:free], 1)
        for index, grant in grants.items():
            gaps[index] += grant
            free -= grant
    return gaps, closing
