"""Time each edition's caption cues to its narration and set their display copy.

A cue is bound to the exact aligned words of its phrase, never crosses a thought, and never
changes the waveform. The declared caption timing gives a cue's tail after its last word, the
early start a brief cue that ends a line may take, and, for English, the full-interval hold. A
brief cue then joins its sentence or holds into the quiet after it.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from itertools import pairwise

from ddwg_film.captions import CaptionError
from ddwg_film.captions.phrasing import segment_caption_phrases
from ddwg_film.narration.spoken_units import (
    CLOSING_MARKS,
    LINE_ENDS,
    SENTENCE_ENDS,
    aligned_lookup,
    thought_ends,
    units,
)
from ddwg_film.specification import CAPTION_LIMITS

# How the assembly receipt describes the cues it counts.
CAPTION_TIMING = (
    "Nonoverlapping exact word-bound semantic cues with declared bounded display edges; "
    "waveform unchanged"
)
# A cue that ends a sentence, after any closing marks and spaces.
SENTENCE_END = re.compile(rf"[{re.escape(SENTENCE_ENDS)}][{re.escape(CLOSING_MARKS)}]*\s*$")
# A cue that ends a line: at a sentence end or a semicolon.
_LINE_END = re.compile(rf"[{re.escape(LINE_ENDS)}][ \t]*$")
# A cue shown for less than this is brief.
BRIEF_CUE_SECONDS = 1.0
# A brief cue joins its neighbour only across less quiet than this.
CUE_JOIN_QUIET_SECONDS = 0.25


def typeset(text: str) -> str:
    """Display copy: an apostrophe is set as a typographic right single quote."""
    return text.replace("'", "\u2019")


def shown_text(cue: dict) -> str:
    """The text a caption cue shows: its display copy when it is set differently."""
    return cue.get("display_text", cue["text"])


def caption_receipt_fields(timeline: dict) -> dict:
    """The assembly receipt's caption fields: the number of cues and how they are timed."""
    return {"caption_count": len(timeline["captions"]), "caption_timing": CAPTION_TIMING}


@dataclass(frozen=True)
class CaptionTiming:
    """A timeline's declared cue edges, in seconds.

    `tail` is held after a cue's last word, `lead` is the early start a brief cue that ends a
    line may take, and `full_interval` holds every cue until the next cue of its segment.
    """

    tail: float
    lead: float
    full_interval: bool


def _caption_timing(timeline: dict, code: str) -> CaptionTiming:
    """The timeline's declared caption timing, within its bounds."""
    policy = timeline.get("caption_timing")
    if not policy:
        msg = "Caption timing requires a declared caption_timing policy"
        raise CaptionError(msg)
    hold_mode = policy.get("hold_mode")
    if "hold_mode" in policy and (hold_mode != "full-interval" or code != "en"):
        msg = "Caption hold mode must be full-interval for English"
        raise CaptionError(msg)
    for key, maximum in (("tail_seconds", 0.25), ("short_cue_lead_seconds", 0.1)):
        value = policy.get(key, 0)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or not 0 <= value <= maximum
        ):
            msg = "Caption reading edges require finite bounded seconds"
            raise CaptionError(msg)
    return CaptionTiming(
        policy.get("tail_seconds", 0),
        policy.get("short_cue_lead_seconds", 0),
        hold_mode == "full-interval",
    )


def _segment_cues(
    segment: dict, timing: CaptionTiming, code: str
) -> tuple[list[dict], list[tuple[float, float]]]:
    """A segment's cues on its exact aligned words, and the speech span each one may show.

    A cue starts on its first word, within the voice, and holds the declared tail after its
    last word, but not into the next word or past the segment. A cue's span runs from the end
    of the word before it to the end of its own last word.
    """
    stream, times = aligned_lookup(
        segment["text"],
        [
            {"text": word["text"], "start_time": word["start"], "end_time": word["end"]}
            for word in segment["words"]
        ],
    )
    ends = thought_ends(segment["text"], segment["utterance_groups"])
    display = typeset(segment["text"])
    cues, spans, position, offset = [], [], 0, 0
    for phrase in segment_caption_phrases(segment, code):
        length = len(units(phrase))
        if stream[position : position + length] != units(phrase):
            msg = "Caption differs from its exact aligned word range"
            raise CaptionError(msg)
        if any(position < end < position + length for end in ends):
            msg = f"Caption crosses a thought-group boundary: {segment['id']}"
            raise CaptionError(msg)
        last_word_end = times[position + length - 1][1]
        next_word_start = (
            times[position + length][0] if position + length < len(times) else segment["end"]
        )
        cue = {
            "start": max(segment["voice_start"], times[position][0]),
            "end": min(last_word_end + timing.tail, next_word_start, segment["end"]),
            "text": phrase,
            "segment": segment["id"],
        }
        if display[offset : offset + len(phrase)] != phrase:
            cue["display_text"] = display[offset : offset + len(phrase)]
        cues.append(cue)
        before = times[position - 1][1] if position else segment["voice_start"]
        spans.append((max(segment["voice_start"], before), last_word_end))
        position += length
        offset += len(phrase)
    return cues, spans


def _lead_short_sentence_ends(
    cues: list[dict], spans: list[tuple[float, float]], lead: float
) -> None:
    """Start each brief cue that ends a line a little before its first word, in place.

    It starts up to the declared lead early, but not before the word before it ends, and only
    as far as a second before its own end. A previous cue still shown then ends there; when
    that cue's own words reach past the new start, the brief cue keeps its start instead.
    """
    for index, cue in enumerate(cues):
        shown = cue["end"] - cue["start"]
        if shown >= BRIEF_CUE_SECONDS - 1e-9 or not _LINE_END.search(cue["text"]):
            continue
        original = cue["start"]
        onset = max(spans[index][0], original - lead, min(original, cue["end"] - BRIEF_CUE_SECONDS))
        if index and cues[index - 1]["end"] > onset:
            if spans[index - 1][1] > onset:
                continue
            cues[index - 1]["end"] = onset
        cue["start"] = onset


def _hold_full_interval(cues: list[dict], segments: list[dict]) -> None:
    """Hold each cue until the next cue of its segment, or to the segment's end, in place."""
    segment_ends = {segment["id"]: segment["end"] for segment in segments}
    for index, cue in enumerate(cues):
        following = cues[index + 1] if index + 1 < len(cues) else None
        cue["end"] = (
            following["start"]
            if following and following["segment"] == cue["segment"]
            else segment_ends[cue["segment"]]
        )


def timed_caption_cues(timeline: dict, code: str) -> list[dict]:
    """Bind an edition's exact semantic cues to current words without changing the waveform."""
    timing = _caption_timing(timeline, code)
    cues, spans = [], []
    for segment in timeline["segments"]:
        segment_cues, segment_spans = _segment_cues(segment, timing, code)
        cues.extend(segment_cues)
        spans.extend(segment_spans)
    for cue, following in pairwise(cues):
        cue["end"] = min(cue["end"], following["start"])
    _lead_short_sentence_ends(cues, spans, timing.lead)
    if timing.full_interval:
        _hold_full_interval(cues, timeline["segments"])
    cues = steady_short_cues(cues, CAPTION_LIMITS[code])
    if any(cue["end"] <= cue["start"] for cue in cues):
        msg = "Caption alignment must have a positive readable interval"
        raise CaptionError(msg)
    return cues


def steady_short_cues(
    cues: list[dict], limit: int, minimum: float = BRIEF_CUE_SECONDS
) -> list[dict]:
    """Give every caption time to be read: join a brief cue to its sentence or hold it.

    A cue shorter than ``minimum`` joins an adjacent cue of the same segment and thought
    when no sentence ends between them and the joined line still fits; otherwise it
    holds into the quiet before the following cue of the segment, which still starts on
    its first word.
    """
    result = [dict(cue) for cue in cues]
    index = 0
    while index < len(result):
        cue = result[index]
        if cue["end"] - cue["start"] >= minimum - 1e-9:
            index += 1
            continue
        for left, right in ((index - 1, index), (index, index + 1)):
            if left < 0 or right >= len(result):
                continue
            first, second = result[left], result[right]
            if (
                first["segment"] == second["segment"]
                and second["start"] - first["end"] < CUE_JOIN_QUIET_SECONDS
                and not SENTENCE_END.search(first["text"])
                and len(first["text"] + second["text"]) <= limit
                and len(shown_text(first) + shown_text(second)) <= limit
            ):
                joined = {
                    "start": first["start"],
                    "end": second["end"],
                    "text": first["text"] + second["text"],
                    "segment": first["segment"],
                }
                if "display_text" in first or "display_text" in second:
                    joined["display_text"] = shown_text(first) + shown_text(second)
                result[left : right + 1] = [joined]
                index = left
                break
        else:
            following = result[index + 1] if index + 1 < len(result) else None
            if following and following["segment"] == cue["segment"]:
                quiet = max(0.0, following["start"] - cue["end"])
                cue["end"] += min(minimum - (cue["end"] - cue["start"]), quiet)
            index += 1
    return result
