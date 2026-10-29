"""Measure the current editions objectively for an independent review.

Speaking rate, pause distribution and hierarchy, the heard ratio of each thought
boundary to the quiet inside the thoughts beside it, quiet edges, level continuity, the
chapter profile of rate, pitch and level, thought endings, recognition differences,
loudness, captions and the picture checks. The review scores the audio from these
measurements and its own analysis; taste remains its judgment, and human listening is
a later acceptance. Thought endings are measured by `ddwg_film.review.endings`, on the takes
the current narration receipts bind and, as delivered, on the soundtrack.

It loads no speech runtime, so it runs without a Metal device. Each measurement reads the
current records it measures and refuses one that is not bound to the current timeline,
composition or staged picture with `ReviewError`, which the command reports.

Usage: python -m ddwg_film.review.measurement --out <round-directory>/measurements.json
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import statistics
from itertools import pairwise
from pathlib import Path

import numpy as np

import ddwg_film.media as media
import ddwg_film.narration.recognition as narration_recognition
import ddwg_film.production as production
import ddwg_film.repository as repository
import ddwg_film.review.endings as review_endings
import ddwg_film.soundtrack.level as soundtrack_level
from ddwg_film.picture.rendering import COMPOSITION_SCRIPT
from ddwg_film.picture.sync_audit import SUMMARY_KEYS
from ddwg_film.review import ReviewError
from ddwg_film.review.support import thought_spans, wav_frames

SCOPE = (
    "Automated measurements of the delivered media for the review; taste remains the "
    "reviewer's judgment."
)
STRUCTURE_METHOD = (
    "10 ms RMS of the mean of both channels; quiet below -50 dBFS; thoughts from "
    "aligned words; F0 by normalized autocorrelation (120-400 Hz) over 40 ms windows "
    "every 20 ms of articulation; acoustic syllables are intensity-peak nuclei (de "
    "Jong and Wempe 2009: 40 ms Hann windows every 10 ms, peaks above the "
    "99th-percentile level minus 25 dB with a 2 dB dip to the next peak, voiced) per "
    "second of aligned word time, a text-independent rate; articulated seconds are the "
    "summed aligned word durations"
)
RATIO_METHOD = (
    "longest quiet heard from 20 ms before a thought ends to 20 ms after the next "
    "begins, over the longest quiet inside either thought; designed minus heard "
    "compares the assembly's designed quiet at the same boundary"
)
LEVEL_METHOD = "ITU-R BS.1770-4 gated integrated loudness of each thought's aligned speech"
# A 10 ms frame below this level is heard as quiet.
QUIET_DBFS = -50


def units(text: str, code: str) -> list[str]:
    """Spoken units: Chinese characters, or English words."""
    if code == "zh":
        return re.findall(r"[\u4e00-\u9fff]", text)
    return re.findall(r"[A-Za-z0-9']+", text.lower())


def spread(values: list[float]) -> dict:
    values = sorted(values)
    if not values:
        return {"count": 0}
    return {
        "count": len(values),
        "min": round(values[0], 3),
        "median": round(statistics.median(values), 3),
        "max": round(values[-1], 3),
    }


def dbfs(part: np.ndarray) -> float:
    """RMS level in dBFS of samples scaled to [-1, 1); -120 for no samples."""
    if not len(part):
        return -120.0
    return float(20 * np.log10(np.sqrt(np.mean(part**2)) + 1e-12))


def soundtrack_loudness(path: Path) -> dict:
    """Integrated loudness, loudness range and true peak of a soundtrack, as reviewers read them."""
    level = media.loudness(path, timeout=600)
    return {
        "integrated_lufs": level["integrated_lufs"],
        "loudness_range_lu": level["loudness_range_lu"],
        "true_peak_dbfs": level["true_peak_dbtp"],
    }


def frame_levels(mono: np.ndarray, rate: int) -> np.ndarray:
    """10 ms RMS levels in dBFS."""
    step = round(0.01 * rate)
    count = len(mono) // step
    rms = np.sqrt(np.mean(mono[: count * step].reshape(count, step) ** 2, axis=1))
    return 20 * np.log10(rms + 1e-12)


def pitch_track(mono: np.ndarray, rate: int, starts: list[int]) -> np.ndarray:
    """F0 in Hz of the 40 ms windows at the given sample starts; NaN where unvoiced.

    F0 is the normalized-autocorrelation peak over 120-400 Hz; a window whose peak is at
    most 0.6 is unvoiced.
    """
    size = round(0.04 * rate)
    lags = np.arange(round(rate / 400), round(rate / 120) + 1)
    out = np.full(len(starts), np.nan)
    for begin in range(0, len(starts), 2048):
        chunk = np.asarray(starts[begin : begin + 2048])
        frames = np.stack([mono[a : a + size] for a in chunk])
        frames = frames - frames.mean(axis=1, keepdims=True)
        spectrum = np.fft.rfft(frames, n=2 * size, axis=1)
        auto = np.fft.irfft(np.abs(spectrum) ** 2, axis=1)[:, :size]
        norm = auto[:, lags] / np.maximum(auto[:, :1], 1e-12)
        best = np.argmax(norm, axis=1)
        voiced = norm[np.arange(len(chunk)), best] > 0.6
        out[begin : begin + len(chunk)] = np.where(voiced, rate / lags[best], np.nan)
    return out


def syllable_nuclei(mono: np.ndarray, rate: int, timeline: dict) -> np.ndarray:
    """Acoustic syllable nuclei after de Jong and Wempe (2009): peaks inside words.

    Intensity is the dB level of 40 ms Hann windows every 10 ms. A nucleus is a local
    peak inside an aligned word above the 99th-percentile level minus 25 dB, separated
    from the next peak by a dip of at least 2 dB, and voiced at its frame (normalized
    autocorrelation above 0.6 at 75-400 Hz). Returns nucleus times in centiseconds.
    """
    hop, size = round(0.01 * rate), round(0.04 * rate)
    count = (len(mono) - size) // hop
    frames = np.lib.stride_tricks.sliding_window_view(mono, size)[::hop][:count]
    level = 10 * np.log10(np.mean((frames * np.hanning(size)) ** 2, axis=1) + 1e-9)
    inside = np.zeros(count, bool)
    for segment in timeline["segments"]:
        for word in segment["words"]:
            inside[int(word["start"] * 100) : int(word["end"] * 100) + 1] = True
    threshold = np.percentile(level[inside], 99) - 25
    middle = level[1:-1]
    local = (
        np.flatnonzero(
            inside[1:-1] & (middle > threshold) & (middle >= level[:-2]) & (middle > level[2:])
        )
        + 1
    )
    lags = np.arange(round(rate / 400), round(rate / 75))
    nuclei = []
    for k, i in enumerate(local):
        if k + 1 < len(local) and level[i] - level[i : local[k + 1] + 1].min() < 2:
            continue
        frame = frames[i] - frames[i].mean()
        auto = np.correlate(frame, frame, "full")[size - 1 :]
        if auto[0] > 0 and (auto[lags] / auto[0]).max() > 0.6:
            nuclei.append(i)
    return np.array(nuclei)


def quiet_runs(quiet: np.ndarray, start: float, end: float) -> np.ndarray:
    """Seconds of each run of quiet 10 ms frames between two times."""
    part = quiet[int(start * 100) : int(end * 100)]
    edges = np.diff(np.r_[False, part, False].astype(np.int8))
    return (np.flatnonzero(edges == -1) - np.flatnonzero(edges == 1)) / 100


def longest(runs: np.ndarray) -> float:
    return float(runs.max()) if len(runs) else 0.0


def thought_quiet(quiet: np.ndarray, segment: dict) -> tuple[list, list, list[float]]:
    """A segment's thought spans, the quiet runs inside each, and each boundary's quiet.

    A boundary's quiet is the longest run heard from 20 ms before one thought ends to
    20 ms after the next begins.
    """
    spans = thought_spans(segment)
    inner = [quiet_runs(quiet, start, end) for start, end in spans]
    heard = [
        longest(quiet_runs(quiet, end - 0.02, after + 0.02))
        for (_, end), (after, _) in pairwise(spans)
    ]
    return spans, inner, heard


def boundary_ratios(quiet: np.ndarray, segments: list[dict], assembly: dict) -> dict:
    """Heard quiet at each thought boundary against the quiet inside its thoughts.

    The ratio divides the boundary's quiet by the longest quiet inside either thought;
    the assembly's designed quiet at the boundary is compared with the heard quiet. The
    six lowest ratios are listed, and the boundaries heard below the edition's declared
    ratio are counted.
    """
    declared = assembly["designed_pause_policy"]["boundary_ratio"]
    designed = {
        (record["id"], pause["thought_group_index"]): pause["designed_quiet_seconds"]
        for record in assembly["records"]
        for pause in record["designed_thought_pauses"]
    }
    rows, gaps = [], []
    for segment in segments:
        name = segment["id"]
        _, inner, heard = thought_quiet(quiet, segment)
        for index, boundary in enumerate(heard):
            beside = max(longest(inner[index]), longest(inner[index + 1]))
            rows.append(
                {
                    "boundary": f"{name}.{index + 1}>{name}.{index + 2}",
                    "ratio": round(boundary / beside, 2) if beside else None,
                    "heard_seconds": boundary,
                    "inner_seconds": beside,
                }
            )
            if (name, index + 1) in designed:
                gaps.append(round(designed[name, index + 1] - boundary, 3))
    judged = sorted(
        (row for row in rows if row["ratio"] is not None),
        key=lambda row: (row["ratio"], row["boundary"]),
    )
    return {
        "method": RATIO_METHOD,
        "boundaries": len(rows),
        "lowest": judged[:6],
        "declared_ratio": declared,
        "below_declared_ratio": sum(row["ratio"] < declared for row in judged),
        "designed_minus_heard_seconds": {
            "count": len(gaps),
            "median": round(float(np.median(gaps)), 4),
            "p90": round(float(np.percentile(gaps, 90)), 4),
            "max": max(gaps),
        }
        if gaps
        else {"count": 0},
    }


def designed_hierarchy(assembly: dict) -> dict:
    """The assembly's designed thought pauses against the inner quiet each one follows."""
    joins = [p for r in assembly["records"] for p in r["designed_thought_pauses"]]
    with_inner = [p for p in joins if "inner_quiet_seconds" in p]
    measured = [
        p["designed_quiet_seconds"] / p["inner_quiet_seconds"]
        for p in with_inner
        if p["inner_quiet_seconds"] > 0.1
    ]
    return {
        "joins": len(joins),
        "longer_than_inner_quiet": sum(
            p["designed_quiet_seconds"] > p["inner_quiet_seconds"] for p in with_inner
        ),
        "measured_inner_quiet": len(with_inner),
        "median_ratio_to_inner_quiet": round(statistics.median(measured), 2) if measured else None,
    }


def heard_hierarchy(quiet: np.ndarray, segments: list[dict]) -> dict:
    """The quiet heard at each thought boundary against the quiet heard inside the thoughts."""
    boundary, inside, worse = [], [], 0
    for segment in segments:
        _, inner, heard = thought_quiet(quiet, segment)
        for runs in inner:
            inside += [float(v) for v in runs if v >= 0.12]
        boundary += heard
        worse += sum(value <= longest(runs) for value, runs in zip(heard, inner[:-1], strict=True))
    return {
        "thought_boundaries": len(boundary),
        "boundary_not_longer_than_longest_inner_quiet": worse,
        "boundary_quiet_seconds": spread(boundary),
        "inner_quiet_of_at_least_120_ms_seconds": spread(inside),
    }


def quiet_edges(pcm: np.ndarray, mono: np.ndarray, rate: int) -> dict:
    """How the narration enters and leaves each run of digital zero of 20 ms or more.

    The 5 ms beside each run also count a fast onset that rises from zero; a step is judged
    on the 1 ms beside the zero itself.
    """
    zero = np.all(pcm == 0, axis=1)
    edges = np.diff(np.r_[False, zero, False].astype(np.int8))
    starts, stops = np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)
    keep = stops - starts >= round(0.02 * rate)
    window, step = round(0.005 * rate), round(0.001 * rate)
    before = [dbfs(mono[max(0, a - window) : a]) for a in starts[keep]]
    after = [dbfs(mono[b : b + window]) for b in stops[keep]]
    return {
        "digital_zero_runs_of_20_ms_or_more": int(keep.sum()),
        "edge_window_ms": 5,
        "entered_above_minus_45_dbfs": sum(v > -45 for v in before),
        "left_above_minus_45_dbfs": sum(v > -45 for v in after),
        "step_window_ms": 1,
        "entered_with_a_step_above_minus_45_dbfs": sum(
            dbfs(mono[max(0, a - step) : a]) > -45 for a in starts[keep]
        ),
        "left_with_a_step_above_minus_45_dbfs": sum(
            dbfs(mono[b : b + step]) > -45 for b in stops[keep]
        ),
    }


def level_continuity(pcm: np.ndarray, rate: int, segments: list[dict]) -> dict:
    """The loudness of each thought's aligned speech, and the steps between thoughts."""
    levels = []
    for segment in segments:
        for index, (start, end) in enumerate(thought_spans(segment), 1):
            lufs = soundtrack_level.loudness_lufs(
                pcm[round(start * rate) : round(end * rate)], rate
            )
            if lufs is not None:
                levels.append((f"{segment['id']}.{index}", lufs))
    steps = [(b[0], round(b[1] - a[1], 2)) for a, b in pairwise(levels)]
    return {
        "method": LEVEL_METHOD,
        "thoughts": len(levels),
        "median_absolute_step_lu": round(statistics.median(abs(v) for _, v in steps), 2),
        "p90_absolute_step_lu": round(float(np.percentile([abs(v) for _, v in steps], 90)), 2),
        "largest_steps": sorted(steps, key=lambda step: -abs(step[1]))[:5],
    }


def chapter_measures(code: str, mono: np.ndarray, rate: int, chapter: dict) -> dict:
    """One chapter's rate, pitch and level from its gathered units, words and frames."""
    f0 = pitch_track(mono, rate, chapter["starts"])
    f0 = f0[~np.isnan(f0)]
    return {
        "units_per_articulated_second": round(chapter["units"] / chapter["articulated"], 2),
        "acoustic_syllables_per_articulated_second": round(
            chapter["nuclei"] / chapter["articulated"], 2
        ),
        # Chinese characters are written syllables, so their ratio validates the
        # acoustic count.
        **(
            {"acoustic_per_written_syllable": round(chapter["nuclei"] / chapter["units"], 3)}
            if code == "zh"
            else {}
        ),
        "median_f0_hz": round(float(np.median(f0)), 1),
        "f0_p10_p90_semitones": round(
            float(12 * np.log2(np.percentile(f0, 90) / np.percentile(f0, 10))), 1
        ),
        "median_level_dbfs": round(float(np.median(chapter["levels"])), 1),
    }


def chapter_profile(
    code: str, mono: np.ndarray, rate: int, levels: np.ndarray, timeline: dict
) -> dict:
    """Each chapter's speaking rate, acoustic syllable rate, pitch and voiced level."""
    nuclei = syllable_nuclei(mono, rate, timeline)
    chapters = {}
    for segment in timeline["segments"]:
        chapter = chapters.setdefault(
            segment["chapter"],
            {"units": 0, "articulated": 0.0, "nuclei": 0, "starts": [], "levels": []},
        )
        chapter["units"] += len(units(segment["text"], code))
        chapter["articulated"] += sum(w["end"] - w["start"] for w in segment["words"])
        for word in segment["words"]:
            chapter["nuclei"] += int(
                ((nuclei >= word["start"] * 100) & (nuclei < word["end"] * 100)).sum()
            )
            chapter["starts"] += range(
                round(word["start"] * rate),
                round(word["end"] * rate) - round(0.04 * rate),
                round(0.02 * rate),
            )
        voice = levels[int(segment["voice_start"] * 100) : int(segment["voice_end"] * 100)]
        chapter["levels"] += [v for v in voice if v > QUIET_DBFS]
    return {name: chapter_measures(code, mono, rate, chapter) for name, chapter in chapters.items()}


def audio_structure(code: str, soundtrack: Path, timeline: dict, assembly: dict) -> dict:
    """The automated structure of the delivered narration.

    The designed and heard pause hierarchy, boundary ratios, quiet edges, level
    continuity and the chapter profile of rate, pitch and level.
    """
    pcm, rate = wav_frames(soundtrack)
    mono = pcm.astype(np.float64).mean(axis=1) / 32768
    levels = frame_levels(mono, rate)
    quiet = levels < QUIET_DBFS
    return {
        "method": STRUCTURE_METHOD,
        "designed_pause_hierarchy": designed_hierarchy(assembly),
        "heard_pause_hierarchy": heard_hierarchy(quiet, timeline["segments"]),
        "boundary_to_inner_quiet_ratio": boundary_ratios(quiet, timeline["segments"], assembly),
        "quiet_edges": quiet_edges(pcm, mono, rate),
        "level_continuity": level_continuity(pcm, rate, timeline["segments"]),
        "chapter_profile": chapter_profile(code, mono, rate, levels, timeline),
    }


def recognition(edition: production.Edition) -> dict:
    """Recognized units of each selected recording against its script text."""
    records = repository.read(edition.narration_selected)["records"]
    selected = {record["id"]: record for record in records}
    asr = repository.read(edition.ear_first / "asr.json")
    joiner = "" if edition.code == "zh" else " "
    differences, script_units, differing = [], 0, 0
    for record in asr["records"]:
        chosen = selected[record["id"]]
        if record["wav_sha256"] != chosen["wav_sha256"]:
            msg = f"Recognition does not bind the selected recording: {record['id']}"
            raise ReviewError(msg)
        expected = narration_recognition.recognition_units(chosen["text"])
        heard = narration_recognition.recognition_units(record["heard"])
        script_units += len(expected)
        differing += round(record["unit_error_rate"] * len(expected))
        matcher = difflib.SequenceMatcher(None, expected, heard, autojunk=False)
        differences += [
            {
                "segment": record["id"],
                "kind": tag,
                "script": joiner.join(expected[i1:i2]),
                "heard": joiner.join(heard[j1:j2]),
            }
            for tag, i1, i2, j1, j2 in matcher.get_opcodes()
            if tag != "equal"
        ]
    return {
        "model": asr["model"],
        "scope": asr["scope"],
        "script_units": script_units,
        "differing_units": differing,
        "unit_error_rate": round(differing / script_units, 4),
        "differences": differences,
    }


def picture_sync(edition: production.Edition, timeline_sha256: str) -> dict:
    """The sound-picture sync audit (`ddwg_film.picture.sync_audit`) of the current timeline.

    Its continuity checks list speech without a legible name, a previous picture held into
    a thought, and the seats: marks that stand before their names. The audit must be bound
    to the current timeline and to the composition script whose frames its trace samples.
    """
    report = repository.read(edition.picture_sync)
    if report.get("bound_timeline", {}).get("sha256") != timeline_sha256:
        msg = f"{edition.code}: the sync audit is not bound to the current timeline"
        raise ReviewError(msg)
    if report.get("composition_sha256") != repository.sha(repository.ROOT / COMPOSITION_SCRIPT):
        msg = f"{edition.code}: the sync audit is not bound to the current composition"
        raise ReviewError(msg)
    return {
        **{key: report[key] for key in SUMMARY_KEYS},
        "findings": report["findings"],
        "continuity": report["continuity"],
    }


def picture_geometry(edition: production.Edition) -> dict:
    """The real-browser geometry check, which must have checked the current staged document."""
    geometry = repository.read(edition.picture_geometry)
    staged = edition.picture_stage / "index.html"
    if not staged.is_file() or geometry.get("index_sha256") != repository.sha(staged):
        msg = f"{edition.code}: the picture geometry does not check the current stage"
        raise ReviewError(msg)
    return {
        "geometry_frames_checked": geometry["checked"],
        "step_frames": geometry["step_frames"],
        "findings": len(geometry["findings"]),
        "errors": len(geometry["errors"]),
        "browser": geometry["browser"],
        "index_sha256": geometry["index_sha256"],
    }


def measure_edition(code: str) -> dict:
    """Every measurement of one edition's current media and production records."""
    edition = production.Edition(code)
    timeline = repository.read(edition.timeline)
    timeline_sha256 = repository.sha(edition.timeline)
    sync = picture_sync(edition, timeline_sha256)
    picture = picture_geometry(edition)
    heard = recognition(edition)
    assembly = repository.read(edition.audio_assembly)
    soundtrack = edition.soundtrack
    segments = timeline["segments"]
    count = sum(len(units(s["text"], code)) for s in segments)
    voiced = sum(s["voice_end"] - s["voice_start"] for s in segments)
    articulated = sum(w["end"] - w["start"] for s in segments for w in s["words"])
    thought = [
        p["designed_quiet_seconds"]
        for r in assembly["records"]
        for p in r["designed_thought_pauses"]
    ]
    gaps = {}
    for gap in assembly["gaps"]:
        gaps.setdefault(gap["kind"], []).append(gap["seconds"])
    captions = timeline["captions"]
    return {
        "soundtrack": {
            "path": str(soundtrack.relative_to(repository.ROOT)),
            "sha256": assembly["soundtrack_sha256"],
            **soundtrack_loudness(soundtrack),
        },
        "speaking_rate": {
            "unit": "characters" if code == "zh" else "words",
            "spoken_units": count,
            "per_minute_over_film": round(count / timeline["duration"] * 60, 1),
            "per_minute_over_voiced_segments": round(count / voiced * 60, 1),
            "per_second_while_articulating": round(count / articulated, 2),
            "voiced_seconds": round(voiced, 1),
        },
        "pauses_seconds": {
            "thought_and_question": spread(thought),
            **{kind: spread(values) for kind, values in gaps.items()},
            "closing": assembly["closing_seconds"],
        },
        "thought_endings": review_endings.endings(edition, timeline, assembly),
        "recognition": heard,
        "captions": {
            "count": len(captions),
            "max_characters": max(len(c.get("display_text", c["text"])) for c in captions),
            "single_line": all("\n" not in c["text"] for c in captions),
        },
        "audio_structure": audio_structure(code, soundtrack, timeline, assembly),
        "picture": picture,
        "picture_sync": sync,
        "timeline_sha256": timeline_sha256,
    }


def measure() -> dict:
    """Every measurement of both editions, Chinese first."""
    return {
        "scope": SCOPE,
        "editions": {code: measure_edition(code) for code in production.CODES},
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--out",
        type=Path,
        required=True,
        metavar="FILE",
        help="measurements JSON to write, normally <round-directory>/measurements.json",
    )
    options = parser.parse_args(argv)
    try:
        report = measure()
    except ReviewError as error:
        msg = f"measurement: {error}"
        raise SystemExit(msg) from None
    out = options.out.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    summary = {}
    for code, data in report["editions"].items():
        ratios = data["audio_structure"]["boundary_to_inner_quiet_ratio"]
        summary[code] = {
            "speaking_rate": data["speaking_rate"],
            "pauses_seconds": data["pauses_seconds"],
            "boundary_to_inner_quiet_ratio": {
                key: value for key, value in ratios.items() if key not in ("method", "lowest")
            },
        }
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
