"""Measure sound-picture sync: when each label is legible against when it is spoken.

Reads a label trace written by frame-audit.mjs (TRACE=<file>) and the timeline it ran
on. A label is legible from the first frame its contrast reaches 3:1. Labels and their
" · " parts whose letters occur verbatim in their scene's words are matched to the
spoken occurrence nearest that frame (within 8 s). A label is out of sync when it is
legible more than 0.3 s before the clause that speaks it begins, more than 1.5 s ahead
of its words within that clause, or more than 0.5 s after its words end. Labels with no
verbatim spoken match are listed and counted, not judged. The report also lists speech that runs
over 1.0 s without a legible name, and thoughts that keep the previous picture over 1.0 s.
Given the mark trace that frame-audit.mjs writes (MARKS=<file>), it also lists seats: a
mark that stands in speech for more than 0.6 s before a name is legible at it. A segment
whose aligned words do not spell its text raises `PictureError`.

Usage: python -m filmkit.picture.sync_audit <timeline.json> <trace.tsv> [--out report.json]
    [--tolerance 0.3] [--step 0.0333333] [--bind source-timeline.json] [--marks marks.tsv]
--step is the trace's sampling step, as given to frame-audit.mjs. --bind records the
SHA-256 of the production timeline the audited timeline derives from, and of the
composition script whose frames the trace samples.
"""

from __future__ import annotations

import argparse
import bisect
import json
from pathlib import Path
from typing import TYPE_CHECKING

import filmkit.narration.spoken_units as spoken_units
import filmkit.repository as repository
from filmkit.picture.rendering import COMPOSITION_SCRIPT, PictureError

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

# Chinese commas close a clause; English commas mostly separate list items, so only
# stops and colons close one.
BOUNDARY = set("，。；：！？.;:!?")
# A label is legible from the first frame its contrast reaches this ratio.
LEGIBLE_CONTRAST = 3
# Seconds a label may lead its words within their clause, and trail their end.
AHEAD_IN_CLAUSE = 1.5
AFTER_WORDS = 0.5
# A spoken match farther than this many seconds from its label names something else.
FAR_FROM_WORDS = 8
# Seconds into a thought within which the previous picture gives way.
HOLD_WINDOW = 4
# The verdicts of a label out of sync, and the report's counts that reviews read.
VERDICTS = ("before-clause", "ahead-in-clause", "after-words")
SUMMARY_KEYS = ("tolerance", "labels_judged", "labels_unmatched", "out_of_sync", *VERDICTS)


def units(text: str) -> str:
    """A text's letters and digits, lowercased: the units labels and words are matched by."""
    return "".join(ch for ch in text if ch.isalnum()).lower()


def spoken_index(segment: dict) -> tuple[str, list[float], list[float], list[int]]:
    """A scene's normalized words, each unit's start and end, and its clause opening.

    A clause opens after each stop in the segment text, so the words must spell its text.
    """
    joined, starts, ends = [], [], []
    for word in segment["words"]:
        u = units(word["text"])
        joined.append(u)
        starts.extend([word["start"]] * len(u))
        ends.extend([word["end"]] * len(u))
    spoken = "".join(joined)
    opens, current, k = [], 0, 0
    for ch in segment.get("text", ""):
        if ch in BOUNDARY:
            current = k
        elif ch.isalnum():
            opens.append(current)
            k += 1
    if len(opens) != len(spoken) or spoken != units(segment.get("text", "")):
        msg = f"{segment['id']}: the aligned words do not cover the segment text"
        raise PictureError(msg)
    return spoken, starts, ends, opens


def occurrences(haystack: str, needle: str) -> list[int]:
    """Every start of `needle` in `haystack`, overlapping ones included."""
    found, at = [], haystack.find(needle)
    while at >= 0:
        found.append(at)
        at = haystack.find(needle, at + 1)
    return found


def trace_rows(lines: Iterable[str], width: int) -> Iterator[tuple[float, str, list[str]]]:
    """Each trace line's time, scene and remaining tab-separated fields.

    A label row continues with its contrast, a field this audit does not read and its text;
    a mark row with its box and whether a name stands at it. A line with fewer than `width`
    fields, such as a partial last line, is skipped.
    """
    for line in lines:
        parts = line.rstrip("\n").split("\t")
        if len(parts) >= width:
            yield float(parts[0]), parts[1], parts[2:]


def legible_labels(trace_lines: Iterable[str]) -> dict[tuple[str, str], float]:
    """The first legible time of each label of each scene, whole and by its " · " parts."""
    first = {}
    for t, scene, fields in trace_rows(trace_lines, 5):
        contrast, text = float(fields[0]), fields[2]
        if contrast < LEGIBLE_CONTRAST:
            continue
        # A label is judged whole and by its " · " parts; spacing is not part of a name.
        pieces = {text.strip()} | {p.strip() for p in text.split("·") if p.strip()}
        for piece in sorted(pieces):
            key = (scene, piece)
            if key not in first or t < first[key]:
                first[key] = t
    return first


def nearest_match(
    index: tuple[str, list[float], list[float], list[int]], needle: str, shown: float
) -> tuple[list[tuple[float, float, float]], tuple[float, float, float] | None]:
    """The spoken occurrences of a label's units, and the one that starts nearest its frame.

    Each occurrence is its start, its end and the start of its clause in the scene's spoken
    index; without one, the nearest is None.
    """
    spoken, starts, ends, opens = index
    matches = [
        (starts[h], ends[h + len(needle) - 1], starts[opens[h]])
        for h in occurrences(spoken, needle)
    ]
    return matches, min(matches, key=lambda match: abs(shown - match[0]), default=None)


def verdict(shown: float, start: float, end: float, clause: float, tolerance: float) -> str:
    """Whether a label legible at `shown` anticipates its clause, or leads or trails its words.

    Before its clause begins, a label anticipates the voice; after its words end, it trails
    them.
    """
    if shown < clause - tolerance:
        return "before-clause"
    if shown - start < -AHEAD_IN_CLAUSE:
        return "ahead-in-clause"
    if shown > end + AFTER_WORDS:
        return "after-words"
    return "in-sync"


def summarize(judged: list[dict], far: list[dict], unmatched: list[dict], tolerance: float) -> dict:
    """An audit's report: its counts, the labels out of sync, unspoken and far from words.

    A label counts as unmatched when it is listed as unspoken or as far from its words.
    """
    out = [row for row in judged if row["verdict"] != "in-sync"]
    return {
        "tolerance": tolerance,
        "labels_judged": len(judged),
        "labels_unmatched": len(unmatched) + len(far),
        "out_of_sync": len(out),
        **{name: sum(row["verdict"] == name for row in out) for name in VERDICTS},
        "findings": out,
        "unmatched": unmatched,
        "far_from_words": far,
        "by_scene": {
            scene: sum(1 for row in out if row["scene"] == scene)
            for scene in sorted({row["scene"] for row in out})
        },
    }


def audit(
    timeline: dict, trace_lines: Iterable[str], tolerance: float = 0.3
) -> tuple[dict, list[dict]]:
    """Judge each legible label of a trace against its spoken words; return a report."""
    index = {segment["id"]: spoken_index(segment) for segment in timeline["segments"]}
    labels = sorted(legible_labels(trace_lines).items(), key=lambda kv: (kv[0][0], kv[1], kv[0][1]))
    judged, far, unmatched = [], [], []
    for (scene, label), shown in labels:
        needle = units(label)
        # A label grown part by part is judged by its parts, each at its own first
        # legible frame.
        if scene not in index or len(needle) < 2 or "·" in label:
            continue
        matches, nearest = nearest_match(index[scene], needle, shown)
        if nearest is None:
            unmatched.append({"scene": scene, "label": label, "legible": round(shown, 3)})
            continue
        start, end, clause = nearest
        # A spoken match more than 8 s away names something else: a recap, a heading
        # or another reference. It is listed, because a cue taken from an earlier
        # occurrence of its words shows the same way.
        if abs(shown - start) > FAR_FROM_WORDS:
            spoken = [round(match[0], 3) for match in matches]
            far.append(
                {"scene": scene, "label": label, "legible": round(shown, 3), "spoken": spoken}
            )
            continue
        judged.append(
            {
                "scene": scene,
                "label": label,
                "legible": round(shown, 3),
                "spoken": round(start, 3),
                "spoken_end": round(end, 3),
                "clause_start": round(clause, 3),
                "delta": round(shown - start, 3),
                "occurrences": len(matches),
                "verdict": verdict(shown, start, end, clause, tolerance),
            }
        )
    return summarize(judged, far, unmatched, tolerance), judged


def thought_spans(segment: dict) -> list[tuple[str, float, float]]:
    """Each thought of a segment as "<id>.<n>", the start of its first word and the end of its last.

    A segment without utterance groups is one thought.
    """
    words = segment["words"]
    groups = segment.get("utterance_groups", [segment["text"]])
    try:
        spans = spoken_units.thought_spans(segment["text"], words, groups)
    except spoken_units.AlignmentError as error:
        msg = f"{segment['id']}: {error}"
        raise PictureError(msg) from error
    return [
        (f"{segment['id']}.{index}", words[span.first]["start"], words[span.last]["end"])
        for index, span in enumerate(spans, 1)
    ]


def legible_frames(trace_lines: Iterable[str]) -> dict[float, dict[str, set[str]]]:
    """The names legible at each sampled time by scene: labels of 3:1 contrast with a letter."""
    frames = {}
    for t, scene, fields in trace_rows(trace_lines, 5):
        contrast, text = float(fields[0]), fields[2]
        if contrast < LEGIBLE_CONTRAST or not any(ch.isalpha() for ch in text):
            continue
        frames.setdefault(round(t, 3), {}).setdefault(scene, set()).add(text)
    return frames


def nearest_frame(
    frames: dict[float, dict[str, set[str]]], times: list[float], t: float, step: float
) -> dict[str, set[str]]:
    """The names legible at the sample nearest `t`; none without a sample within half a step."""
    i = bisect.bisect_left(times, t)
    near = min(
        (times[j] for j in (i - 1, i) if 0 <= j < len(times)),
        default=None,
        key=lambda v: abs(v - t),
    )
    return frames[near] if near is not None and abs(near - t) <= step / 2 + 1e-9 else {}


def unnamed_runs(
    frames: dict[float, dict[str, set[str]]],
    times: list[float],
    scene: str,
    span: tuple[float, float],
    step: float,
    limit: float,
) -> list[tuple[float, float]]:
    """The runs of a thought's samples longer than `limit` at which its scene shows no name."""
    a, b = span
    runs, run = [], None
    for t in (round(a + k * step, 3) for k in range(int((b - a) / step) + 1)):
        if nearest_frame(frames, times, t, step).get(scene):
            if run and run[1] - run[0] > limit:
                runs.append(run)
            run = None
        else:
            run = (run[0] if run else t, t)
    if run and run[1] - run[0] > limit:
        runs.append(run)
    return runs


def held_over(
    frames: dict[float, dict[str, set[str]]],
    times: list[float],
    span: tuple[float, float],
    step: float,
    limit: float,
) -> float | None:
    """How long a thought keeps the picture it began under, when that is longer than `limit`.

    The picture gives way at the first sample, within `HOLD_WINDOW` seconds and the thought,
    that has lost at least half the names it began under and shows a new one.
    """
    a, b = span
    before = set().union(*nearest_frame(frames, times, a, step).values())
    if not before:
        return None
    later = times[
        bisect.bisect_right(times, a + step / 2) : bisect.bisect_right(
            times, min(b, a + HOLD_WINDOW)
        )
    ]
    for v in later:
        now = set().union(*frames[v].values())
        if len(before - now) >= max(1, len(before) // 2) and now - before:
            return round(v - a, 2) if v - a > limit else None
    return None


def continuity(
    timeline: dict, trace_lines: Iterable[str], step: float = 1 / 30, limit: float = 1.0
) -> dict:
    """Speech left without a legible name, and a previous picture held into a thought.

    The trace samples the film every `step` seconds and lists only frames that paint a
    label, so a sample with no legible name in its scene is absent. A run of a thought's
    speech longer than `limit` without a legible name of its scene is unnamed speech. A
    thought that begins under names that at least half give way to new ones more than
    `limit` into it, within 4 s and the thought, holds the previous picture over.
    """
    frames = legible_frames(trace_lines)
    times = sorted(frames)
    unnamed, held = [], []
    for segment in timeline["segments"]:
        for key, a, b in thought_spans(segment):
            unnamed += [
                {"thought": key, "from": start, "to": end}
                for start, end in unnamed_runs(frames, times, segment["id"], (a, b), step, limit)
            ]
            seconds = held_over(frames, times, (a, b), step, limit)
            if seconds is not None:
                held.append({"thought": key, "held": seconds})
    return {"unnamed_speech": unnamed, "held_over": held}


def overlap(a: list[int], b: list[int]) -> float:
    """The intersection of two boxes over their union, counting their edge pixels.

    Counting edge pixels lets a ruled row of no height be followed too.
    """
    w = max(0, min(a[2], b[2]) - max(a[0], b[0]) + 1)
    h = max(0, min(a[3], b[3]) - max(a[1], b[1]) + 1)
    areas = [(r[2] - r[0] + 1) * (r[3] - r[1] + 1) for r in (a, b)]
    return w * h / (sum(areas) - w * h)


def seats(
    timeline: dict, mark_lines: Iterable[str], step: float = 1 / 30, limit: float = 0.6
) -> list[dict]:
    """Marks that stand in speech before a name is legible at them.

    Each mark row is one firm mark of a voiced frame: its time, scene, box and whether a
    legible name stands at it. A mark is followed from frame to frame by its overlapping
    box. A mark that stands more than `limit` before its name arrives waits for the name
    in its place: a seat. A mark that is never named is an illustration, not a seat.
    """
    spans = [span for segment in timeline["segments"] for span in thought_spans(segment)]
    frames = {}
    for t, scene, fields in trace_rows(mark_lines, 7):
        box = [int(v) for v in fields[:4]]
        frames.setdefault(round(t, 3), []).append((scene, box, fields[4] == "1"))
    live, ended = [], []
    for t in sorted(frames):
        ended += [mark for mark in live if t - mark["last"] > step * 1.5]
        live = [mark for mark in live if t - mark["last"] <= step * 1.5]
        for scene, box, named in frames[t]:
            known = [m for m in live if m["scene"] == scene and m["last"] < t]
            mark = max(known, key=lambda m: overlap(m["box"], box), default=None)
            if mark is None or overlap(mark["box"], box) <= 0.4:
                mark = {"scene": scene, "first": t, "named": None}
                live.append(mark)
            mark.update(last=t, box=box)
            if named and mark["named"] is None:
                mark["named"] = t
    found = []
    for mark in ended + live:
        if mark["named"] is not None and mark["named"] - mark["first"] > limit + 1e-9:
            thought = next(
                (key for key, a, b in spans if a - 0.3 <= mark["first"] <= b + 0.3), None
            )
            found.append(
                {
                    "thought": thought,
                    "at": round(mark["first"], 3),
                    "lag": round(mark["named"] - mark["first"], 2),
                    "box": mark["box"],
                }
            )
    return sorted(found, key=lambda row: (row["at"], row["box"]))


def print_report(report: dict) -> None:
    """Print the report's counts as JSON, then one line per finding."""
    lists = ("findings", "far_from_words", "continuity")
    summary = {k: v for k, v in report.items() if k not in lists}
    counts = {k: len(v) for k, v in report["continuity"].items()}
    print(json.dumps({**summary, "far_from_words": len(report["far_from_words"]), **counts}))
    for row in report["findings"]:
        print(
            f"{row['scene']}  {row['verdict']:15s} {row['delta']:+.2f}s"
            f"  legible {row['legible']:.2f}  spoken {row['spoken']:.2f}"
            f"  {row['label']}"
        )
    for row in report["far_from_words"]:
        spoken = ", ".join(f"{t:.2f}" for t in row["spoken"])
        print(
            f"{row['scene']}  far-from-words  legible {row['legible']:.2f}"
            f"  spoken {spoken}  {row['label']}"
        )
    for row in report["continuity"]["unnamed_speech"]:
        print(f"{row['thought']}  unnamed-speech  {row['from']:.2f}-{row['to']:.2f}")
    for row in report["continuity"]["held_over"]:
        print(f"{row['thought']}  held-over  {row['held']:.2f}s")
    for row in report["continuity"].get("seats", []):
        print(f"{row['thought']}  seat  {row['at']:.2f}  waits {row['lag']:.2f}s  {row['box']}")


def read_trace(path: Path) -> list[str]:
    """The lines of a trace that frame-audit.mjs wrote."""
    with path.open(encoding="utf-8") as handle:
        return handle.readlines()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("timeline", type=Path, help="the timeline the trace ran on")
    parser.add_argument("trace", type=Path, help="the label trace frame-audit.mjs wrote")
    parser.add_argument("--out", type=Path, metavar="FILE", help="the report to write")
    parser.add_argument("--tolerance", type=float, default=0.3, metavar="SECONDS")
    parser.add_argument(
        "--step", type=float, default=1 / 30, metavar="SECONDS", help="the trace's sampling step"
    )
    parser.add_argument(
        "--bind", metavar="FILE", help="the production timeline the audited timeline derives from"
    )
    parser.add_argument("--marks", type=Path, metavar="FILE", help="the mark trace to judge")
    options = parser.parse_args(argv)
    timeline = json.loads(options.timeline.read_text(encoding="utf-8"))
    lines = read_trace(options.trace)
    try:
        report, judged = audit(timeline, lines, options.tolerance)
    except PictureError as error:
        msg = f"sync audit: {error}"
        raise SystemExit(msg) from None
    report["continuity"] = continuity(timeline, lines, options.step)
    if options.marks is not None:
        report["continuity"]["seats"] = seats(timeline, read_trace(options.marks), options.step)
    if options.bind is not None:
        bound = repository.sha(Path(options.bind).resolve())
        report["bound_timeline"] = {"path": options.bind, "sha256": bound}
        report["composition_sha256"] = repository.sha(repository.ROOT / COMPOSITION_SCRIPT)
    if options.out is not None:
        with options.out.open("w", encoding="utf-8") as handle:
            json.dump({**report, "judged": judged}, handle, ensure_ascii=False, indent=1)
    print_report(report)


if __name__ == "__main__":
    main()
