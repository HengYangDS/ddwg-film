"""Run-on takes: a thought narrated with the words that follow it, then cut in the quiet between.

A thought whose every take ends inside its last syllable can be narrated with the spoken text
that follows it in the film, so the model finishes that syllable on its way to the next words.
The take is cut where 30 ms of heard quiet first complete after the thought's last aligned
unit ends, before the next unit has begun, and the thought before the cut must end naturally.
A cast's retake records the run-on text and its cut, so synthesis narrates the same take and
cuts it at the same sample without the aligner.
"""

from __future__ import annotations

import numpy as np

from ddwg_film.narration.spoken_units import aligned_lookup, units
from ddwg_film.narration.take_edges import ending
from ddwg_film.soundtrack.quiet import FRAME_SECONDS, HEARD_QUIET_DBFS

# The quiet that ends a run-on take's thought: this many 10 ms frames heard as quiet.
CUT_QUIET_FRAMES = 3
# The aligner moves in steps of 0.08 s, so the quiet may reach this far past the next unit's
# aligned start before that unit is heard.
ALIGNER_STEP_SECONDS = 0.08


def following_spoken_text(records: list[dict], segment: str, index: int) -> str:
    """The spoken text of the thought that follows one thought in a receipt's recordings.

    Raises:
        ValueError: No thought follows it.
    """
    thoughts = [
        (record["id"], child["index"], child["spoken_text"])
        for record in records
        for child in record["utterance_groups"]["records"]
    ]
    place = next(k for k, (sid, at, _) in enumerate(thoughts) if (sid, at) == (segment, index))
    if place + 1 == len(thoughts):
        msg = f"{segment}.{index}: no thought follows it to read on into"
        raise ValueError(msg)
    return thoughts[place + 1][2]


def thought_bounds(items: list[dict], spoken: str, run_on: str) -> tuple[float, float]:
    """The aligned end of a thought's last unit and the aligned start of its run-on's first."""
    _, times = aligned_lookup(spoken + run_on, items)
    last = len(units(spoken))
    return times[last - 1][1], times[last][0]


def run_on_cut(pcm: np.ndarray, rate: int, thought_end: float, next_start: float) -> int | None:
    """The sample that ends a run-on take's thought, or None without quiet before its next words.

    From the thought's aligned end, 10 ms frames are read up to one aligner step past the next
    unit's aligned start; the cut is the end of the first CUT_QUIET_FRAMES frames in a row
    heard as quiet.
    """
    frame = round(FRAME_SECONDS * rate)
    first = round(thought_end * rate)
    last = min(len(pcm), round((next_start + ALIGNER_STEP_SECONDS) * rate))
    samples, run = pcm.astype(np.float64) / 32768, 0
    for start in range(first, last - frame + 1, frame):
        level = 20 * np.log10(np.sqrt(np.mean(samples[start : start + frame] ** 2)) + 1e-12)
        run = run + 1 if level <= HEARD_QUIET_DBFS else 0
        if run == CUT_QUIET_FRAMES:
            return start + frame
    return None


def cut_run_on(audio: np.ndarray, cut: int, rate: int) -> np.ndarray:
    """A run-on take's thought: its float samples before the cut, which must end it naturally.

    The samples are judged as the 16-bit PCM that a recording of them retains.
    """
    if not 0 < cut < len(audio):
        msg = "A run-on cut lies outside its take"
        raise RuntimeError(msg)
    pcm = (np.clip(audio[:cut], -1.0, 1.0) * 32767).astype(np.int16)
    if not ending(pcm, rate)["natural"]:
        msg = "A run-on take does not end naturally at its cut"
        raise RuntimeError(msg)
    return audio[:cut]


def valid_run_on(run_on: object) -> bool:
    """Whether a declared run-on names exactly its following spoken text and a positive cut."""
    return (
        isinstance(run_on, dict)
        and set(run_on) == {"spoken_text", "cut_sample"}
        and isinstance(run_on["spoken_text"], str)
        and bool(run_on["spoken_text"].strip())
        and type(run_on["cut_sample"]) is int
        and run_on["cut_sample"] > 0
    )
