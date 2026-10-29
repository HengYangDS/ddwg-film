"""Assemble each edition's soundtrack from the selected recordings.

The selected recordings are bound to the script, decoded, and shaped in turn: the pauses inside
each thought are capped and lengthened, every thought boundary is measured, each thought join
takes its designed quiet, each thought and chapter is leveled, and the clips are laid out with
the designed gaps at one program level. The timeline, the captions and the receipt record the
result.
"""

from __future__ import annotations

import dataclasses
import json
import wave
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

import ddwg_film.repository as repository
from ddwg_film.captions.documents import subtitle_files
from ddwg_film.captions.phrasing import segment_caption_phrases
from ddwg_film.captions.timing import caption_receipt_fields, timed_caption_cues
from ddwg_film.narration.selection import validate_aligned_recording
from ddwg_film.narration.spoken_units import aligned_lookup
from ddwg_film.narration.thought_groups import validate_group_inputs
from ddwg_film.repository import read, run, sha, write
from ddwg_film.soundtrack.level import (
    apply_gain,
    chapter_level_gains,
    correct_narration_level,
    fade_narration_boundaries,
    level_thoughts,
    measure_program_level,
    program_gain,
)
from ddwg_film.soundtrack.pauses import (
    allocate_designed_gaps,
    design_thought_pauses,
    gap_kinds,
    gap_pause_targets,
    thought_joins,
    thought_pause_targets,
)
from ddwg_film.soundtrack.policy import designed_pause_policy, segment_releases
from ddwg_film.soundtrack.quiet import (
    cap_inner_quiet,
    clip_end,
    clip_start,
    heard_before,
    lengthen_inner_quiet,
    release_tail,
    thought_inner_quiet,
)
from ddwg_film.specification import CREDITS_DURATION, DURATION, PROGRAM_LEVEL, RATE

if TYPE_CHECKING:
    from pathlib import Path

    from ddwg_film.production import Edition

# A segment's picture starts this share of its gap before its voice.
PICTURE_LEAD = 0.6
ALIGNMENT_LIMITS = (
    "Model-aligned words on unchanged native speech; human listening remains separate."
)


class AssemblyError(ValueError):
    """Selected recordings that cannot be assembled exactly as bound and declared."""


@dataclass(frozen=True)
class ShapedRecording:
    """A recording with its inner pauses capped and lengthened, and its moved alignment."""

    samples: np.ndarray
    items: list[dict]
    capped: list[dict]
    lengthened: list[dict]


@dataclass(frozen=True)
class Clip:
    """A segment's designed recording, trimmed to its voice, with what its receipt records."""

    segment: dict
    record: dict
    samples: np.ndarray
    items: list[dict]
    trim_start: float
    trim_end: float
    edits: list[dict]
    fades: dict
    thought_levels: list[dict]
    level_gain_db: float
    capped: list[dict]
    lengthened: list[dict]
    chapter_gain_db: float = 0.0


def _bound_inputs(script: dict, edition: Edition) -> tuple[dict, dict]:
    """The selected recording and alignment of each segment, bound to its exact script text."""
    records = {r["id"]: r for r in read(edition.narration_selected)["records"]}
    alignments = {r["id"]: r for r in read(edition.alignment_selected)["records"]}
    for segment in script["segments"]:
        record = records[segment["id"]]
        if record["text"] != segment["text"]:
            msg = f"Selected recording text differs: {segment['id']}"
            raise AssemblyError(msg)
        if sha(record["path"]) != record["wav_sha256"]:
            msg = f"Selected recording waveform differs: {segment['id']}"
            raise AssemblyError(msg)
        validate_group_inputs(record, root=repository.ROOT, section=segment)
        validate_aligned_recording(record, alignments[segment["id"]])
        segment_caption_phrases(segment, edition.code)
    return records, alignments


def _decode(record: dict, source: Path) -> np.ndarray:
    """Decode a selected recording through FFmpeg to 16-bit stereo at the film's rate."""
    run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-i",
            str(repository.ROOT / record["path"]),
            "-ar",
            str(RATE),
            "-ac",
            "2",
            "-c:a",
            "pcm_s16le",
            str(source),
        ]
    )
    with wave.open(str(source)) as wave_file:
        return (
            np.frombuffer(wave_file.readframes(wave_file.getnframes()), dtype="<i2")
            .reshape(-1, 2)
            .copy()
        )


def _shape_inner_quiet(
    segment: dict, samples: np.ndarray, items: list[dict], policy: dict
) -> ShapedRecording:
    """Cap the native pauses inside each thought, then lengthen them to their floors.

    Capping comes first, so every later measure sees the capped recording; a sentence end,
    clause mark or comma inside a thought then reaches its declared floor, so punctuation is
    heard as graded breaks.
    """
    text, groups = segment["text"], segment["utterance_groups"]
    samples, items, capped = cap_inner_quiet(
        samples, items, text, groups, RATE, policy["inner_cap"], policy["inner_caps"]
    )
    samples, items, lengthened = lengthen_inner_quiet(
        samples, items, text, groups, RATE, policy["inner_floors"], policy["inner_breath"]
    )
    return ShapedRecording(samples, items, capped, lengthened)


def _boundary_measures(
    segments: list[dict], shaped: dict[str, ShapedRecording]
) -> tuple[dict[str, list[float]], dict[str, list[float]]]:
    """The heard quiet inside each thought and the unheard overhead of each thought join.

    Every thought boundary is measured against the pauses inside its thought before any
    pause is designed.
    """
    inner, overhead = {}, {}
    for segment in segments:
        current = shaped[segment["id"]]
        text, groups = segment["text"], segment["utterance_groups"]
        inner[segment["id"]] = thought_inner_quiet(
            current.samples, current.items, text, groups, RATE
        )
        overhead[segment["id"]] = [
            join.overhead
            for join in thought_joins(current.samples, current.items, text, groups, RATE)
        ]
    return inner, overhead


def _record_gain(record: dict) -> float:
    """The level correction a recording declares, bound to its evidence; 0 without one."""
    level = record.get("level_correction", {})
    gain_db = level.get("gain_db", 0)
    if level:
        if sha(level["evidence"]) != level["evidence_sha256"]:
            msg = "Narration level evidence binding differs"
            raise AssemblyError(msg)
        observed = read(level["evidence"])
        if observed["recording_sha256"] != record["wav_sha256"] or observed["gain_db"] != gain_db:
            msg = "Narration level correction differs from its recording"
            raise AssemblyError(msg)
    return gain_db


def _designed_clip(
    segment: dict,
    record: dict,
    shaped: ShapedRecording,
    policy: dict,
    *,
    targets: list[float],
    releases: dict[int, float],
    inner: list[float],
) -> Clip:
    """Level a segment's thoughts, design its thought joins and trim it to its voice.

    `targets` are the segment's designed thought pauses, `releases` its declared releases
    and `inner` the heard quiet inside each of its thoughts.
    """
    text, groups = segment["text"], segment["utterance_groups"]
    samples, thought_levels = level_thoughts(
        shaped.samples, shaped.items, text, groups, RATE, policy["level_tolerance"]
    )
    designed, items, edits = design_thought_pauses(
        samples,
        shaped.items,
        text,
        groups,
        RATE,
        targets=targets,
        releases=releases,
    )
    for edit in edits:
        index = edit["thought_group_index"]
        edit["inner_quiet_seconds"] = inner[index - 1]
        edit["next_inner_quiet_seconds"] = inner[index]
    _, times = aligned_lookup(text, items)
    start = clip_start(designed, times[0][0], RATE)
    if start is None:
        msg = f"Narration is heard from its first sample: {segment['id']}"
        raise AssemblyError(msg)
    trim_start = start / RATE
    # The clip ends in the recording's own quiet after its tail guard, so its last syllable dies
    # away inside it.
    trim_end = clip_end(designed, times[-1][1], policy["tail_guard"], RATE) / RATE
    clip = designed[round(trim_start * RATE) : round(trim_end * RATE)].copy()
    # A last recording still heard where the voice ends is released into the gap.
    released = release_tail(clip, len(clip), RATE) if heard_before(clip, len(clip), RATE) else 0
    level_gain_db = _record_gain(record)
    clip, fades = fade_narration_boundaries(correct_narration_level(clip, level_gain_db))
    fades["released_tail_samples"] = released
    return Clip(
        segment,
        record,
        clip,
        items,
        trim_start,
        trim_end,
        edits,
        fades,
        thought_levels,
        level_gain_db,
        shaped.capped,
        shaped.lengthened,
    )


def _chapter_gains(clips: list[Clip], tolerance_db: float | None) -> dict[str, float]:
    """The static gain of each chapter, from its leveled thoughts and its peak.

    Each chapter's leveled thoughts are brought within the declared tolerance of the
    film's median thought by one static gain, so no chapter, the coda included, stands
    louder or softer than the film.
    """
    levels: dict[str, list[float]] = {}
    peaks: dict[str, float] = {}
    for clip in clips:
        chapter = clip.segment["chapter"]
        levels.setdefault(chapter, []).extend(
            level["loudness_lufs"] + level["gain_db"] + clip.level_gain_db
            for level in clip.thought_levels
            if level["loudness_lufs"] is not None
        )
        peak = float(np.abs(clip.samples.astype(np.int32)).max(initial=0)) / 32768
        peaks[chapter] = max(peaks.get(chapter, 0.0), peak)
    return chapter_level_gains(levels, peaks, tolerance_db)


def _timed_segment(clip: Clip, gap: int, kind: str, begin: float, end: float) -> dict:
    """The timeline segment of a laid-out clip: its picture and voice times and its words.

    The segment after the opening gap starts the film's picture; a later segment's picture
    starts within its gap, before its voice.
    """
    return {
        **clip.segment,
        "start": 0.0 if kind == "opening" else begin - PICTURE_LEAD * gap / RATE,
        "voice_start": begin,
        "voice_end": end,
        "gap_before": gap / RATE,
        "gap_kind": kind,
        "words": [
            {
                "text": item["text"],
                "start": max(begin, min(end, begin + item["start_time"] - clip.trim_start)),
                "end": max(begin, min(end, begin + item["end_time"] - clip.trim_start)),
            }
            for item in clip.items
        ],
    }


def _assembly_record(clip: Clip, start_sample: int) -> dict:
    """The receipt record of a laid-out clip."""
    return {
        "id": clip.segment["id"],
        "path": clip.record["path"],
        "source_sha256": clip.record["wav_sha256"],
        "trim_start": clip.trim_start,
        "trim_end": clip.trim_end,
        "start_sample": start_sample,
        "frames": len(clip.samples),
        "designed_thought_pauses": clip.edits,
        "capped_inner_pauses": clip.capped,
        "lengthened_inner_pauses": clip.lengthened,
        "boundary_fades": clip.fades,
        "thought_levels": clip.thought_levels,
        "level_gain_db": clip.level_gain_db,
        "chapter_gain_db": clip.chapter_gain_db,
        "speech_tempo_ratio": 1.0,
        "pitch_shift": 0,
    }


def _lay_out(
    clips: list[Clip], gaps: list[int], kinds: list[str]
) -> tuple[np.ndarray, list[dict], list[dict]]:
    """Place each clip after its gap: the soundtrack, its timeline segments and records.

    A segment's picture ends where the next one's starts, and the last ends with the
    narration, before the credits.
    """
    soundtrack = np.zeros((RATE * DURATION, 2), dtype=np.int16)
    segments, records, cursor = [], [], 0
    for index, clip in enumerate(clips):
        cursor += gaps[index]
        soundtrack[cursor : cursor + len(clip.samples)] = clip.samples
        begin, end = cursor / RATE, (cursor + len(clip.samples)) / RATE
        segments.append(_timed_segment(clip, gaps[index], kinds[index], begin, end))
        records.append(_assembly_record(clip, cursor))
        cursor += len(clip.samples)
        print(json.dumps({"id": clip.segment["id"], "start": begin, "end": end}), flush=True)
    for index, segment in enumerate(segments):
        segment["end"] = (
            segments[index + 1]["start"]
            if index + 1 < len(segments)
            else float(DURATION - CREDITS_DURATION)
        )
    return soundtrack, segments, records


def _write_pcm(path: Path, samples: np.ndarray) -> None:
    """Write 16-bit stereo samples at the film's rate as a WAV file."""
    with wave.open(str(path), "wb") as file:
        file.setnchannels(2)
        file.setsampwidth(2)
        file.setframerate(RATE)
        file.writeframes(samples.tobytes())


def _reach_program_level(soundtrack: np.ndarray, target: Path) -> tuple[np.ndarray, dict, int]:
    """Bring the whole soundtrack to the program level by one linear gain, and write it.

    Return the leveled soundtrack, its program-level record and its peak.
    """
    _write_pcm(target, soundtrack)
    before = measure_program_level(target)
    gain_db = program_gain(before)
    soundtrack = apply_gain(soundtrack, gain_db, "Program level")
    peak = int(np.abs(soundtrack.astype(np.int32)).max())
    if peak >= 32767:
        msg = "Narration clips; repair owning recording before assembly"
        raise AssemblyError(msg)
    _write_pcm(target, soundtrack)
    level = {
        "policy": PROGRAM_LEVEL,
        "measurement": "FFmpeg ebur128 (ITU-R BS.1770) with true peak",
        "before": before,
        "gain_db": gain_db,
        "after": measure_program_level(target),
    }
    return soundtrack, level, peak


def _receipt(
    edition: Edition,
    policy: dict,
    timeline: dict,
    *,
    kinds: list[str],
    gaps: list[int],
    closing: int,
    records: list[dict],
    frames: int,
    peak: int,
    program_level: dict,
) -> dict:
    """The assembly receipt: the policy, the gaps, each record and the program level.

    The gaps before the segments and the closing quiet are given in samples.
    """
    captions = caption_receipt_fields(timeline)
    return {
        "script_sha256": sha(edition.script),
        "assembly_mode": "native-speech-designed-pauses",
        "designed_pause_policy": policy,
        "gaps": [
            {"kind": kind, "seconds": gap / RATE} for kind, gap in zip(kinds, gaps, strict=True)
        ],
        "closing_seconds": closing / RATE,
        "records": records,
        "sample_rate": RATE,
        "channels": 2,
        "samples_per_channel": frames,
        "duration": DURATION,
        "peak_pcm": peak,
        "program_level": program_level,
        "stereo_mode": "Centered mono narration in two channels",
        "pitch_shift": 0,
        "music": False,
        "soundtrack_sha256": sha(edition.soundtrack),
        "caption_count": captions["caption_count"],
        "alignment_limits": ALIGNMENT_LIMITS,
        "caption_timing": captions["caption_timing"],
    }


def assemble(edition: Edition) -> None:
    """Lay out the edition's selected recordings with designed pauses at program level."""
    script = read(edition.script)
    policy = designed_pause_policy(script.get("voice_performance", {}))
    segments = script["segments"]
    records, alignments = _bound_inputs(script, edition)
    work = repository.ROOT / "build/runtime/work/audio-assembly" / edition.code
    work.mkdir(parents=True, exist_ok=True)
    edition.artifacts.mkdir(parents=True, exist_ok=True)
    decoded = {
        segment["id"]: _decode(records[segment["id"]], work / f"{segment['id']}-source.wav")
        for segment in segments
    }
    shaped = {
        segment["id"]: _shape_inner_quiet(
            segment, decoded.pop(segment["id"]), alignments[segment["id"]]["items"], policy
        )
        for segment in segments
    }
    inner, overhead = _boundary_measures(segments, shaped)
    targets = thought_pause_targets(segments, policy, inner, overhead)
    releases = segment_releases(policy, segments)
    clips = [
        _designed_clip(
            segment,
            records[segment["id"]],
            shaped.pop(segment["id"]),
            policy,
            targets=targets[segment["id"]],
            releases=releases[segment["id"]],
            inner=inner[segment["id"]],
        )
        for segment in segments
    ]
    gains = _chapter_gains(clips, policy["chapter_level_tolerance"])
    clips = [
        dataclasses.replace(
            clip,
            samples=correct_narration_level(clip.samples, gains[clip.segment["chapter"]]),
            chapter_gain_db=gains[clip.segment["chapter"]],
        )
        for clip in clips
    ]
    kinds = gap_kinds(segments)
    total = (DURATION - CREDITS_DURATION) * RATE
    speech = sum(len(clip.samples) for clip in clips)
    gaps, closing = allocate_designed_gaps(
        kinds, speech, policy, RATE, total, bases=gap_pause_targets(segments, policy)
    )
    soundtrack, timeline_segments, audio_records = _lay_out(clips, gaps, kinds)
    if sum(gaps) + speech + closing != total:
        msg = "Designed assembly failed exact sample accounting"
        raise AssemblyError(msg)
    soundtrack, program_level, peak = _reach_program_level(soundtrack, edition.soundtrack)
    timeline = {
        **script,
        "segments": timeline_segments,
        "timing_state": "Actual waveform alignment with designed native-speech pauses",
    }
    timeline["captions"] = timed_caption_cues(timeline, edition.code)
    write(edition.timeline, timeline)
    receipt = _receipt(
        edition,
        policy,
        timeline,
        kinds=kinds,
        gaps=gaps,
        closing=closing,
        records=audio_records,
        frames=len(soundtrack),
        peak=peak,
        program_level=program_level,
    )
    write(edition.audio_assembly, receipt)
    subtitle_files(timeline, edition)
