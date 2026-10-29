"""Find and shape the quiet a listener hears inside and between spoken units.

A recording is native quiet where its peak stays at most QUIET_PCM, and heard as quiet where
its 10 ms frames stay at most HEARD_QUIET_DBFS. The quiet between two aligned items is measured
in their join window. The pauses inside each thought are capped and lengthened here, and
digital quiet is spliced into or out of a recording at points, with the aligned times moved to
match.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from ddwg_film.narration.spoken_units import QUOTATION_MARKS, item_joins, thought_spans

if TYPE_CHECKING:
    from ddwg_film.narration.spoken_units import ItemJoin

# A sample is native quiet at a peak of at most this PCM value.
QUIET_PCM = 260
# Quiet as a listener hears it: 10 ms frames whose RMS is at most -55 dBFS before the
# program gain, about -50 dBFS after it.
HEARD_QUIET_DBFS = -55.0
# Heard quiet is measured in frames of 10 ms.
FRAME_SECONDS = 0.01
# The quiet between two aligned items is measured from 65 ms before the left item ends to
# 65 ms after the right item starts.
JOIN_MARGIN_SECONDS = 0.065
# Native quiet beside inserted digital quiet fades into it over at most 50 ms.
FADE_SECONDS = 0.05
# Quiet removed from the middle of a pause is crossfaded over at most 10 ms.
CROSSFADE_SECONDS = 0.01
# A recording that reaches digital silence while still heard is released over its last
# 60 ms instead of stopping while it decays; a thought whose every take still sounds at
# its end may declare a longer release (released_tail_seconds).
RELEASE_SECONDS = 0.06
# A pause with less native quiet than this is spoken through and keeps its speech.
LEAST_PAUSE_SECONDS = 0.02
# A clip begins at least this long before its first aligned word.
CLIP_LEAD_SECONDS = 0.10
# A clip's end waits at most this long past its tail guard for its voice to die away.
TAIL_WAIT_SECONDS = 0.5


def _mono(audio: np.ndarray) -> np.ndarray:
    """The channel mean of 16-bit samples, scaled to [-1, 1)."""
    part = audio.astype(np.float64)
    return (part.mean(axis=1) if part.ndim > 1 else part) / 32768


def _frame_dbfs(mono: np.ndarray) -> np.ndarray:
    """The RMS level in dBFS of mono samples, over their last axis."""
    return 20 * np.log10(np.sqrt(np.mean(mono**2, axis=-1)) + 1e-12)


def heard_before(audio: np.ndarray, stop: int, rate: int) -> bool:
    """Whether the 10 ms before stop are heard: their RMS is above HEARD_QUIET_DBFS."""
    part = audio[max(0, stop - round(FRAME_SECONDS * rate)) : stop]
    return bool(len(part)) and bool(_frame_dbfs(_mono(part)) > HEARD_QUIET_DBFS)


def release_tail(audio: np.ndarray, stop: int, rate: int, seconds: float = RELEASE_SECONDS) -> int:
    """Fade the seconds before stop to silence in place; return the samples."""
    start = max(0, stop - round(seconds * rate))
    part = audio[start:stop]
    ramp = 0.5 + 0.5 * np.cos(np.pi * np.arange(1, len(part) + 1) / (len(part) + 1))
    part[:] = np.round(part * (ramp[:, None] if part.ndim > 1 else ramp)).astype(audio.dtype)
    return len(part)


def longest_run(mask: np.ndarray) -> tuple[int, int] | None:
    """The first longest run of true values in a mask, as its start and stop; None without one."""
    edges = np.diff(np.r_[False, mask, False].astype(np.int8))
    starts, stops = np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)
    if not len(starts):
        return None
    run = int(np.argmax(stops - starts))
    return int(starts[run]), int(stops[run])


def join_window(left: dict, right: dict, rate: int, length: int) -> tuple[int, int]:
    """The samples in which the quiet between two aligned items is measured.

    The window runs from 65 ms before the left item ends to 65 ms after the right item starts,
    within a recording of the given length. It is empty when the items overlap by more.
    """
    margin = round(JOIN_MARGIN_SECONDS * rate)
    return (
        max(0, round(left["end_time"] * rate) - margin),
        min(length, round(right["start_time"] * rate) + margin),
    )


def native_quiet_run(audio: np.ndarray, first: int, last: int) -> tuple[int, int] | None:
    """The longest run of samples at a peak of at most QUIET_PCM within [first, last)."""
    run = longest_run(np.max(np.abs(audio[first:last].astype(np.int32)), axis=1) <= QUIET_PCM)
    return None if run is None else (first + run[0], first + run[1])


def heard_quiet_run(audio: np.ndarray, first: int, last: int, rate: int) -> tuple[int, int] | None:
    """The longest run of 10 ms frames heard as quiet within [first, last), in samples.

    A frame is heard as quiet when the RMS of its channel mean is at most
    HEARD_QUIET_DBFS; frames start at first.
    """
    frame = round(FRAME_SECONDS * rate)
    count = (last - first) // frame
    if count <= 0:
        return None
    mono = _mono(audio[first : first + count * frame])
    run = longest_run(_frame_dbfs(mono.reshape(count, frame)) <= HEARD_QUIET_DBFS)
    return None if run is None else (first + run[0] * frame, first + run[1] * frame)


def clip_start(audio: np.ndarray, first_word: float, rate: int) -> int | None:
    """The first sample of a recording's clip, inside the recording's own heard quiet.

    The clip begins at the latest 10 ms frame heard as quiet that starts at least
    0.10 s before the first aligned word, so a breath or onset that the aligner leaves
    before that word is kept whole. None when the voice is heard from the recording's
    first sample.
    """
    frame = round(FRAME_SECONDS * rate)
    sample = max(0, round((first_word - CLIP_LEAD_SECONDS) * rate))
    while True:
        mono = _mono(audio[sample : sample + frame])
        if len(mono) == frame and _frame_dbfs(mono) <= HEARD_QUIET_DBFS:
            return sample
        if sample == 0:
            return None
        sample = max(0, sample - frame)


def clip_end(audio: np.ndarray, last_word: float, guard: float, rate: int) -> int:
    """The sample after a recording's clip, in the recording's own heard quiet where it can be.

    The clip ends at least `guard` seconds after the last aligned word, at the first 10 ms
    step from there whose last 10 ms are heard as quiet, so a final syllable that outlasts its
    aligned end is kept whole. It waits at most TAIL_WAIT_SECONDS past the guard and never past
    the recording's end; a voice still heard there is released.
    """
    frame = round(FRAME_SECONDS * rate)
    sample = min(len(audio), round((last_word + guard) * rate))
    limit = min(len(audio), round((last_word + guard + TAIL_WAIT_SECONDS) * rate))
    while sample < limit and heard_before(audio, sample, rate):
        sample = min(limit, sample + frame)
    return sample


def fade_into_quiet(audio: np.ndarray, center: int, begin: int, end: int, fade: int) -> int:
    """Fade the native quiet [begin, end) out into center and back in after it, in place.

    Digital quiet inserted at center then joins the native quiet beside it without a step.
    Return the samples faded on each side: at most fade, and within the native quiet.
    """
    span = min(fade, center - begin, end - center)
    if span:
        rise = 0.5 - 0.5 * np.cos(np.pi * np.arange(span) / span)
        audio[center - span : center] = np.round(
            audio[center - span : center] * rise[::-1, None]
        ).astype(audio.dtype)
        audio[center : center + span] = np.round(
            audio[center : center + span] * rise[:, None]
        ).astype(audio.dtype)
    return span


def splice_quiet(audio: np.ndarray, shifts: list[tuple[int, int]]) -> np.ndarray:
    """The recording with each shift applied, in source order.

    A shift (sample, delta) with a delta of zero or more inserts that many samples of digital
    quiet at the sample; a negative delta removes that many samples around it, the extra
    sample of an odd count before it.
    """
    chunks, cursor = [], 0
    for center, delta in shifts:
        if delta >= 0:
            chunks.extend([audio[cursor:center], np.zeros((delta, audio.shape[1]), audio.dtype)])
            cursor = center
        else:
            start = center + delta // 2
            chunks.append(audio[cursor:start])
            cursor = start - delta
    chunks.append(audio[cursor:])
    return np.concatenate(chunks)


def shifted_items(items: list[dict], shifts: list[tuple[int, int]], rate: int) -> list[dict]:
    """The aligned items with each time moved by every shift at or before it."""

    def moved(seconds: float) -> float:
        sample = round(seconds * rate)
        return (sample + sum(delta for at, delta in shifts if at <= sample)) / rate

    return [
        {**item, "start_time": moved(item["start_time"]), "end_time": moved(item["end_time"])}
        for item in items
    ]


def thought_inner_quiet(
    audio: np.ndarray, items: list[dict], text: str, groups: list[str], rate: int
) -> list[float]:
    """Measure the longest heard quiet inside each thought, in seconds.

    Quiet is measured as at a join: between consecutive aligned items of one thought, in
    their join window.
    """
    longest = [0.0] * len(groups)
    for join in item_joins(text, items, groups):
        if join.ends_thought:
            continue
        first, last = join_window(items[join.left], items[join.right], rate, len(audio))
        run = heard_quiet_run(audio, first, last, rate)
        if run:
            longest[join.thought] = max(longest[join.thought], (run[1] - run[0]) / rate)
    return longest


@dataclass(frozen=True)
class _Cut:
    """Native quiet removed from the middle of a pause inside a thought, in samples."""

    at: int
    removed: int
    native: int
    limit: int


def _pause_cap(marks: str, cap: float, caps: dict[str, float] | None) -> float:
    """The cap of a pause: the largest cap of its marks, or the smallest without marks.

    A mark without a declared cap takes the inner cap. Quotation marks are not pauses, so a
    comma after a closing quote is a comma.
    """
    marks = "".join(mark for mark in marks if mark not in QUOTATION_MARKS)
    if not caps:
        return cap
    if not marks:
        return min(caps.values())
    return max(
        next((seconds for key, seconds in caps.items() if mark in key), cap) for mark in marks
    )


def _cap_cuts(
    audio: np.ndarray,
    items: list[dict],
    joins: list[ItemJoin],
    rate: int,
    cap: float,
    caps: dict[str, float] | None,
) -> list[_Cut]:
    """The quiet beyond its cap in each pause inside a thought, centered in its native run."""
    cuts = []
    for join in joins:
        if join.ends_thought:
            continue
        limit = round(_pause_cap(join.marks, cap, caps) * rate)
        run = native_quiet_run(
            audio, *join_window(items[join.left], items[join.right], rate, len(audio))
        )
        if run and run[1] - run[0] > limit:
            length = run[1] - run[0]
            cuts.append(_Cut(run[0] + limit // 2, length - limit, length, limit))
    return cuts


def _crossfade_cuts(
    audio: np.ndarray, cuts: list[_Cut], rate: int
) -> tuple[np.ndarray, list[dict]]:
    """Remove each cut through a 10 ms crossfade of the quiet on either side of it."""
    fade = round(CROSSFADE_SECONDS * rate)
    chunks, cursor, edits = [], 0, []
    for cut in cuts:
        span = min(fade, cut.removed, cut.limit // 2)
        ramp = 0.5 - 0.5 * np.cos(np.pi * np.arange(1, span + 1) / (span + 1))
        after = cut.at + cut.removed
        leaving, entering = audio[cut.at - span : cut.at], audio[after - span : after]
        blend = leaving * ramp[::-1, None] + entering * ramp[:, None]
        chunks.extend([audio[cursor : cut.at - span], np.round(blend).astype(audio.dtype)])
        cursor = after
        edits.append(
            {
                "source_sample": cut.at,
                "native_quiet_seconds": cut.native / rate,
                "capped_quiet_seconds": cut.limit / rate,
                "removed_quiet_samples": cut.removed,
                "crossfade_samples": span,
            }
        )
    chunks.append(audio[cursor:])
    return np.concatenate(chunks), edits


def _moved_by_cuts(items: list[dict], cuts: list[_Cut], rate: int) -> list[dict]:
    """The aligned items with each time moved back by the quiet cut before it."""

    def moved(seconds: float) -> float:
        sample = round(seconds * rate)
        return (sample - sum(min(cut.removed, max(0, sample - cut.at)) for cut in cuts)) / rate

    return [
        {**item, "start_time": moved(item["start_time"]), "end_time": moved(item["end_time"])}
        for item in items
    ]


def cap_inner_quiet(
    audio: np.ndarray,
    items: list[dict],
    text: str,
    groups: list[str],
    rate: int,
    cap: float | None,
    caps: dict[str, float] | None = None,
) -> tuple[np.ndarray, list[dict], list[dict]]:
    """Shorten each native pause inside a thought to at most its declared cap.

    A pause is measured as at a join, between consecutive aligned items inside one
    thought. Its cap is the largest cap of the marks written between its words, where
    a mark without a declared cap takes the inner cap and a pause without marks takes
    the smallest declared cap, so a comma can be held shorter than a sentence end.
    Quotation marks are not marks: a comma after a closing quote keeps the comma's cap.
    Quiet beyond the cap is removed from the pause's middle through a 10 ms crossfade
    of the quiet on either side, so speech samples, the pause's edges and every thought
    join stay as recorded. Aligned times move with the removed quiet.
    """
    joins = item_joins(text, items, groups)
    if cap is None:
        return audio, items, []
    cuts = _cap_cuts(audio, items, joins, rate, cap, caps)
    if not cuts:
        return audio, items, []
    capped, edits = _crossfade_cuts(audio, cuts, rate)
    return capped, _moved_by_cuts(items, cuts, rate), edits


@dataclass(frozen=True)
class _InnerPause:
    """A pause inside a thought: its place, its marks and floor, and its native quiet."""

    index: int
    thought: int
    left: float
    right: float
    marks: str
    floor: float
    run: tuple[int, int] | None

    def native(self, rate: int) -> float:
        """The pause's native quiet in seconds."""
        return (self.run[1] - self.run[0]) / rate if self.run else 0.0


def _inner_pauses(
    audio: np.ndarray,
    items: list[dict],
    joins: list[ItemJoin],
    rate: int,
    floors: dict[str, float],
) -> list[_InnerPause]:
    """Each pause inside a thought, with the largest floor declared for its marks."""
    pauses = []
    for join in joins:
        if join.ends_thought:
            continue
        left, right = items[join.left], items[join.right]
        pauses.append(
            _InnerPause(
                index=len(pauses),
                thought=join.thought,
                left=left["end_time"],
                right=right["start_time"],
                marks=join.marks,
                floor=max(
                    (seconds for key, seconds in floors.items() if set(key) & set(join.marks)),
                    default=0.0,
                ),
                run=native_quiet_run(audio, *join_window(left, right, rate, len(audio))),
            )
        )
    return pauses


def _divide(first: float, last: float, marks: list[_InnerPause], limit: float) -> list[int]:
    """Breathe a run of speech longer than limit at the mark nearest its middle, recursively.

    Return the indices of the pauses chosen to breathe, among the marks inside the run.
    """
    inside = [pause for pause in marks if first < pause.left and pause.right < last]
    if last - first <= limit or not inside:
        return []
    middle = (first + last) / 2
    chosen = min(inside, key=lambda pause: abs((pause.left + pause.right) / 2 - middle))
    return [
        chosen.index,
        *_divide(first, chosen.left, inside, limit),
        *_divide(chosen.right, last, inside, limit),
    ]


def _mark_breaths(
    pauses: list[_InnerPause], spans: list[tuple[float, float]], breath: dict, rate: int
) -> set[int]:
    """The pauses that take the breath pause, by index.

    Within each thought, a run of speech longer than the breath group, between pauses of at
    least the breath pause, breathes at the floored mark nearest its middle. Such a mark has a
    floor and native quiet below the breath pause, and at least 20 ms of native quiet.
    """
    limit, seconds = breath["longest_group_seconds"], breath["pause_seconds"]
    least = round(LEAST_PAUSE_SECONDS * rate)
    breathing = set()
    for thought, (first, last) in enumerate(spans):
        mine = [pause for pause in pauses if pause.thought == thought]
        marks = [
            pause
            for pause in mine
            if 0 < pause.floor < seconds
            and pause.native(rate) < seconds
            and pause.native(rate) * rate >= least
        ]
        start = first
        for pause in mine:
            if max(pause.floor, pause.native(rate)) >= seconds:
                breathing.update(_divide(start, pause.left, marks, limit))
                start = pause.right
        breathing.update(_divide(start, last, marks, limit))
    return breathing


@dataclass(frozen=True)
class _FloorPlan:
    """Digital quiet inserted at the middle of a pause's heard quiet to reach its floor."""

    begin: int
    end: int
    center: int
    delta: int
    marks: str
    floor: float
    breath: bool


def _floor_plans(
    audio: np.ndarray,
    pauses: list[_InnerPause],
    breathing: set[int],
    breath: dict | None,
    rate: int,
) -> list[_FloorPlan]:
    """The pauses that fall short of their floor, in order and without overlap."""
    least = round(LEAST_PAUSE_SECONDS * rate)
    plans = []
    for pause in pauses:
        breathes = pause.index in breathing
        floor = breath["pause_seconds"] if breathes else pause.floor
        if not floor or not pause.run:
            continue
        begin, end = pause.run
        delta = round(floor * rate) - (end - begin)
        if delta <= 0 or end - begin < least or (plans and begin < plans[-1].end):
            continue
        heard = heard_quiet_run(audio, begin, end, rate) or (begin, end)
        center = (heard[0] + heard[1]) // 2
        plans.append(_FloorPlan(begin, end, center, delta, pause.marks, floor, breathes))
    return plans


def lengthen_inner_quiet(
    audio: np.ndarray,
    items: list[dict],
    text: str,
    groups: list[str],
    rate: int,
    floors: dict[str, float] | None,
    breath: dict | None = None,
) -> tuple[np.ndarray, list[dict], list[dict]]:
    """Lengthen each native pause inside a thought to the floor of its punctuation.

    A pause is measured as at a join, between consecutive aligned items inside one
    thought, and takes the largest floor declared for the marks written between them,
    so a sentence end inside a thought is heard as a longer break than a comma. A run
    of speech longer than the declared breath group, between pauses of at least the
    breath pause, then takes that pause at the floored mark nearest its middle, until
    every run fits or has no such mark left. Digital quiet is inserted into the middle
    of the part of the native quiet heard as quiet, and the native quiet beside it fades
    into it and back out, so speech samples, the pause's edges and every thought join
    stay as recorded. A join without native quiet keeps its speech untouched. Aligned
    times move with the inserted quiet.
    """
    joins = item_joins(text, items, groups)
    if not floors:
        return audio, items, []
    pauses = _inner_pauses(audio, items, joins, rate, floors)
    breathing = set()
    if breath:
        spans = [
            (items[span.first]["start_time"], items[span.last]["end_time"])
            for span in thought_spans(text, items, groups)
        ]
        breathing = _mark_breaths(pauses, spans, breath, rate)
    plans = _floor_plans(audio, pauses, breathing, breath, rate)
    if not plans:
        return audio, items, []
    audio, fade = audio.copy(), round(FADE_SECONDS * rate)
    edits = []
    for plan in plans:
        span = fade_into_quiet(audio, plan.center, plan.begin, plan.end, fade)
        edits.append(
            {
                "source_sample": plan.center,
                "marks": plan.marks,
                "breath": plan.breath,
                "native_quiet_seconds": (plan.end - plan.begin) / rate,
                "floor_seconds": plan.floor,
                "inserted_quiet_samples": plan.delta,
                "fade_samples": span,
            }
        )
    shifts = [(plan.center, plan.delta) for plan in plans]
    return splice_quiet(audio, shifts), shifted_items(items, shifts, rate), edits
