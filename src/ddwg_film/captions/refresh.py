"""Refresh an edition's caption cues against its current script, keeping the assembled audio.

A refresh runs on an assembled edition. Its receipt must be bound to the current script, or
become bound: a script that changed only in presentation records a caption revision. A script
whose copy or performance changed needs a new assembly, so the refresh refuses it. The cues are
then timed again on the unchanged words and waveform, and the subtitle documents rewritten.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ddwg_film.captions import CaptionError
from ddwg_film.captions.documents import subtitle_files
from ddwg_film.captions.timing import caption_receipt_fields, timed_caption_cues
from ddwg_film.repository import read, sha, write

if TYPE_CHECKING:
    from ddwg_film.production import Edition

# Segment fields generated into a timeline, which a script never holds.
GENERATED_SEGMENT_FIELDS = frozenset(
    {
        "start",
        "end",
        "voice_start",
        "voice_end",
        "gap_before",
        "gap_kind",
        "cues",
        "words",
        "thought_spans",
        "visual_event_spans",
        "picture_event_spans",
    }
)
PRESENTATION_SCOPE = (
    "Only authored visual and caption presentation changed; source copy, words and PCM preserved"
)


def caption_source(timeline: dict) -> dict:
    """Project the source copy from an assembled timeline for caption-only edits."""
    return {
        **{
            key: value
            for key, value in timeline.items()
            if key not in {"segments", "captions", "timing_state", "caption_timing"}
        },
        "segments": [
            {
                key: value
                for key, value in segment.items()
                if key not in GENERATED_SEGMENT_FIELDS | {"caption_phrases"}
            }
            for segment in timeline["segments"]
        ],
    }


def narration_source(timeline: dict) -> dict:
    """Keep recorded language and performance distinct from visual presentation."""
    source = caption_source(timeline)
    return {
        **{key: value for key, value in source.items() if key != "proposed_visual_coverage"},
        "segments": [
            {
                key: value
                for key, value in segment.items()
                if key not in {"visual_events", "picture_events"}
            }
            for segment in source["segments"]
        ],
    }


@dataclass(frozen=True)
class _Hashes:
    """The SHA-256 of each file a refresh binds, as it found them."""

    script: str
    timeline: str
    receipt: str
    soundtrack: str


def _record_presentation_revision(receipt: dict, hashes: _Hashes) -> None:
    """Bind the receipt to a script changed only in presentation, recording what it replaces."""
    if receipt["soundtrack_sha256"] != hashes.soundtrack:
        msg = "Caption revision requires the exact assembled waveform"
        raise CaptionError(msg)
    receipt["caption_revision"] = {
        "previous_script_sha256": receipt["script_sha256"],
        "previous_timeline_sha256": hashes.timeline,
        "previous_audio_assembly_sha256": hashes.receipt,
        "script_sha256": hashes.script,
        "soundtrack_sha256": receipt["soundtrack_sha256"],
        "scope": PRESENTATION_SCOPE,
    }
    receipt["script_sha256"] = hashes.script


def _require_current_binding(timeline: dict, script: dict, receipt: dict, hashes: _Hashes) -> None:
    """Refuse a receipt or timeline that is not bound to the current script and waveform."""
    if (
        receipt["script_sha256"] != hashes.script
        or receipt["soundtrack_sha256"] != hashes.soundtrack
        or [(s["id"], s["text"]) for s in timeline["segments"]]
        != [(s["id"], s["text"]) for s in script["segments"]]
    ):
        msg = "Caption refresh requires the exact current script and waveform"
        raise CaptionError(msg)


def _rebound_selection(edition: Edition, script: dict, script_sha256: str) -> dict | None:
    """The edition's narration selection bound to the current script, if it has one."""
    if not edition.narration_selected.is_file():
        return None
    selected = read(edition.narration_selected)
    if [(record["id"], record["text"]) for record in selected["records"]] != [
        (segment["id"], segment["text"]) for segment in script["segments"]
    ] or selected["cast_sha256"] != sha(edition.cast):
        msg = "Selected narration differs from the current script or cast"
        raise CaptionError(msg)
    return {**selected, "script_sha256": script_sha256}


def _adopt_caption_authoring(timeline: dict, script: dict) -> None:
    """Give the timeline the script's authored cue phrases and caption timing, in place."""
    for timed, source in zip(timeline["segments"], script["segments"], strict=True):
        if source.get("caption_phrases") is not None:
            timed["caption_phrases"] = source["caption_phrases"]
        else:
            timed.pop("caption_phrases", None)
    if "caption_timing" in script:
        timeline["caption_timing"] = script["caption_timing"]
    else:
        timeline.pop("caption_timing", None)


def refresh_captions(edition: Edition) -> None:
    """Refresh picture/subtitle cues while preserving the selected assembled audio."""
    timeline = read(edition.timeline)
    script = read(edition.script)
    receipt = read(edition.audio_assembly)
    hashes = _Hashes(
        script=sha(edition.script),
        timeline=sha(edition.timeline),
        receipt=sha(edition.audio_assembly),
        soundtrack=sha(edition.soundtrack),
    )
    if receipt["script_sha256"] != hashes.script and narration_source(script) == narration_source(
        timeline
    ):
        _record_presentation_revision(receipt, hashes)
    _require_current_binding(timeline, script, receipt, hashes)
    selected = _rebound_selection(edition, script, hashes.script)
    _adopt_caption_authoring(timeline, script)
    timeline["captions"] = timed_caption_cues(timeline, edition.code)
    write(edition.timeline, timeline)
    receipt.update(caption_receipt_fields(timeline))
    write(edition.audio_assembly, receipt)
    subtitle_files(timeline, edition)
    if selected is not None and selected != read(edition.narration_selected):
        write(edition.narration_selected, selected)
    print(
        json.dumps(
            {
                "language": edition.code,
                "caption_count": len(timeline["captions"]),
                "soundtrack_sha256": receipt["soundtrack_sha256"],
            }
        )
    )
