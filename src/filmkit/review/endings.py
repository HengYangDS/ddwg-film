"""How each thought and phrase ends: on the takes the narration receipt binds, and as delivered.

A take may end abruptly and still be delivered naturally, because the assembly may release its
tail into the digital silence that follows; a released thought is also judged where its release
began, so a voice cut at full level and then released is listed as cut while voiced. A phrase
that ends before a heard pause inside its thought is judged by the same fall as a thought's end.
"""

from __future__ import annotations

from itertools import pairwise
from typing import TYPE_CHECKING

import numpy as np

import filmkit.narration.spoken_units as spoken_units
import filmkit.repository as repository
from filmkit.narration.run_on import ALIGNER_STEP_SECONDS
from filmkit.narration.take_edges import decay, ending, phrase_ends
from filmkit.review.support import thought_spans, wav_frames

if TYPE_CHECKING:
    from pathlib import Path

    import filmkit.production as production

ENDING = (
    "final 30 ms RMS <= 0.01, or <= 0.02 with final 10 ms <= 0.12 of the last-300 ms "
    "peak; and the 20 ms ending 10 ms before the take's last nonzero sample is "
    "unvoiced (autocorrelation < 0.6, 90-400 Hz) or at least 15 dB below the take's "
    "speech median, and the 10 ms ending at that sample is at most -55 dBFS; and a "
    "voiced final (autocorrelation >= 0.8 over the 15 ms before it) does not fall "
    "from -40 to -65 dBFS in under 6 ms, taken as the median over every sample phase "
    "of the 1 ms frame grid, on the take's scale and with both bounds lowered by each "
    "whole decibel up to 6 dB, which covers the program gain with the thought and "
    "chapter leveling; a delivered thought is judged on the takes' scale and at "
    "program level"
)
PHRASE_ENDING = (
    "every phrase-final unit inside a thought (one followed by a clause, phrase or "
    "sentence mark) whose aligned end lies in, or within 0.1 s before, a run of at least "
    "80 ms of 10 ms frames at or below -55 dBFS on the takes' scale is heard; its voiced "
    "last syllable must not fall from -40 to -65 dBFS in under 6 ms, judged as a "
    "delivered thought's final fall is"
)

# A run of digital zero this long after a thought's last word ends the thought as delivered.
DELIVERED_STOP_SECONDS = 0.01
# The assembly releases a voice still heard where it meets digital silence over its last 60 ms.
# A released thought still voiced (normalized autocorrelation at least 0.6) and within 6 dB of
# its speech median where that release begins was cut at full voice, whatever the release
# leaves at its end.
RELEASE_WINDOW_SECONDS = 0.06
CUT_VOICING = 0.6
CUT_DROP_DB = -6.0


def thought_endings(edition: production.Edition) -> dict:
    """The natural endings of every thought take bound by the narration receipt."""
    receipt = repository.read(edition.ear_first / "narration-receipt.json")
    thoughts, abrupt = 0, []
    for record in receipt["records"]:
        for group in record["utterance_groups"]["records"]:
            pcm, rate = wav_frames(repository.ROOT / group["path"])
            thoughts += 1
            if not ending(pcm[:, 0], rate)["natural"]:
                abrupt.append(f"{record['id']}.{group['index']}")
    return {
        "criterion": ENDING,
        "thoughts": thoughts,
        "natural": thoughts - len(abrupt),
        "abrupt": abrupt,
    }


def released_thoughts(assembly: dict, timeline: dict) -> set[str]:
    """The thoughts whose tails the assembly released: at their join, or at their clip's end."""
    counts = {segment["id"]: len(segment["utterance_groups"]) for segment in timeline["segments"]}
    released = {
        f"{record['id']}.{edit['thought_group_index']}"
        for record in assembly["records"]
        for edit in record["designed_thought_pauses"]
        if edit.get("released_tail_samples")
    }
    return released | {
        f"{record['id']}.{counts[record['id']]}"
        for record in assembly["records"]
        if record.get("boundary_fades", {}).get("released_tail_samples")
    }


def delivered_endings(
    soundtrack: Path, timeline: dict, gain_db: float = 0.0, released: set[str] | None = None
) -> dict:
    """The natural endings of every thought as the soundtrack delivers it.

    A thought is delivered from its first word to where its sound stops: the first run of
    digital zero after its last word, or one aligner step before the next thought's aligned
    first word, which may begin that much earlier, but not before its own last word. A take
    whose own ending is abrupt may be released into that zero by the assembly, so the
    delivered ending is judged on the soundtrack itself, by the same criterion as the takes,
    with the program gain taken out so its quiet is measured on the takes' scale, and its
    final fall is judged on that scale and at program level, where a listener hears it. Each
    thought the assembly released is also judged where its release began, so a voice cut at
    full level and then released is listed as cut while voiced; a thought that dies away by
    itself has no release to judge.
    """
    pcm, rate = wav_frames(soundtrack)
    mono = pcm[:, 0] * 10 ** (-gain_db / 20)
    released = released or set()
    named = [
        (f"{segment['id']}.{k}", span)
        for segment in timeline["segments"]
        for k, span in enumerate(thought_spans(segment), 1)
    ]
    stops = [
        max(end, start - ALIGNER_STEP_SECONDS) for (_, (_, end)), (_, (start, _)) in pairwise(named)
    ]
    stops.append(len(mono) / rate)
    run, abrupt, voiced = round(DELIVERED_STOP_SECONDS * rate), [], []
    release = round(RELEASE_WINDOW_SECONDS * rate)
    for (name, (start, end)), following in zip(named, stops, strict=True):
        first, last, limit = round(start * rate), round(end * rate), round(following * rate)
        heard = mono[last:limit] != 0
        # The first sample that begins a run of digital zero, or the next thought's start.
        zero_runs = np.convolve(~heard, np.ones(run, dtype=int), "valid") == run
        stop = last + int(np.argmax(zero_runs)) if zero_runs.any() else limit
        if not ending(mono[first:stop], rate, (0.0, gain_db))["natural"]:
            abrupt.append(name)
        if name not in released:
            continue
        before = decay(mono[first : max(first, stop - release)], rate)
        if before["tail_voicing"] >= CUT_VOICING and before["tail_drop_db"] >= CUT_DROP_DB:
            voiced.append(name)
    return {
        "thoughts": len(named),
        "natural": len(named) - len(abrupt),
        "abrupt": abrupt,
        "released": [name for name, _ in named if name in released],
        "cut_while_voiced": voiced,
    }


def phrase_endings(soundtrack: Path, timeline: dict, gain_db: float = 0.0) -> dict:
    """The heard phrase ends inside every thought as delivered, and those cut while voiced.

    A phrase ends at an aligned word that a clause, phrase or sentence mark follows inside its
    thought. It is judged on the soundtrack with the program gain taken out, on that scale
    and at program level, as a delivered thought's end is, where heard quiet follows it.
    """
    pcm, rate = wav_frames(soundtrack)
    mono = np.round(pcm[:, 0] * 10 ** (-gain_db / 20)).astype(np.int64)
    named, ends = [], []
    for segment in timeline["segments"]:
        words = segment["words"]
        for join in spoken_units.phrase_joins(segment["text"], words, segment["utterance_groups"]):
            word = words[join.left]
            named.append((f"{segment['id']}.{join.thought + 1}", word["text"] + join.marks))
            ends.append(round(word["end"] * rate))
    heard = {end["end_sample"]: end for end in phrase_ends(mono, rate, ends, (0.0, gain_db))}
    return {
        "criterion": PHRASE_ENDING,
        "heard": len(heard),
        "stopped": [
            {
                "thought": thought,
                "word": word,
                "end": round(sample / rate, 3),
                "fall_ms": heard[sample]["final_fall_ms"],
                "gain_db": heard[sample]["final_fall_gain_db"],
            }
            for (thought, word), sample in zip(named, ends, strict=True)
            if sample in heard and heard[sample]["stops"]
        ],
    }


def endings(edition: production.Edition, timeline: dict, assembly: dict) -> dict:
    """The take endings of one edition, with its thought and phrase endings as delivered."""
    gain = assembly["program_level"]["gain_db"]
    return {
        **thought_endings(edition),
        "delivered": delivered_endings(
            edition.soundtrack, timeline, gain, released_thoughts(assembly, timeline)
        ),
        "phrase_endings": phrase_endings(edition.soundtrack, timeline, gain),
    }
