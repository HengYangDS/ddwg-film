"""Still pictures in a rendered film, measured as the independent reviewers measure them.

The film is decoded at 10 fps to 480x270 grey. A frame is still when at most 12 pixels of
the content band, rows 30-225, change by more than 24 levels from the frame before; the
coarser measure compares frames 0.2 s apart and calls a pair still when under 0.05 % of
the band changes that much. Each run of still frames is reported with the speech it
carries, from the timeline's aligned words. A 10 fps sample can land either side of a mark
that moves for one frame, so the film is read twice, 0.05 s apart, and the worse reading
decides. The specification allows no 3.5 s of speech over a still picture; the scan refuses
a draft before the final render and confirms the final film before it is reviewed.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from typing import TYPE_CHECKING

import numpy as np

import ddwg_film.repository as repository

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator
    from pathlib import Path

FPS, WIDTH, HEIGHT = 10, 480, 270
# Sixty-fps frames into each 0.1 s sample at which the two phases are read.
PHASES = (0, 3)
BAND = slice(30, 226)
LEVEL = 24
FINE_PIXELS = 12
COARSE_SHARE = 0.0005
# Runs that carry less speech than this are left out of the report.
REPORTED_SPEECH_SECONDS = 1.0
LIMIT_SECONDS = 3.5
FINE_RULE = f"at most {FINE_PIXELS} band pixels change by more than {LEVEL} levels in 0.1 s"
COARSE_RULE = f"under {COARSE_SHARE:.2%} of the band changes by more than {LEVEL} levels in 0.2 s"


class StillScanError(RuntimeError):
    """The film could not be read, so the scan has not judged it."""


def runs(still: list[bool], step: float) -> list[tuple[float, float]]:
    """Each run of still frames, from the frame before its first to its last, in seconds."""
    found, start = [], None
    for i, flag in enumerate(still):
        if flag and start is None and i:
            start = (i - 1) * step
        if not flag and start is not None:
            found.append((start, (i - 1) * step))
            start = None
    if start is not None:
        found.append((start, (len(still) - 1) * step))
    return found


def speech(words: np.ndarray, start: float, end: float) -> float:
    """Seconds of aligned speech between `start` and `end`."""
    if not len(words):
        return 0.0
    return float(
        np.clip(np.minimum(words[:, 1], end) - np.maximum(words[:, 0], start), 0, None).sum()
    )


def scan(frames: Iterable[np.ndarray], timeline: dict) -> dict:
    """Both measures over grey frames at FPS: each still run with the speech it carries."""
    fine, coarse, previous, key = [False], [False], None, None
    for k, frame in enumerate(frames):
        band = frame[BAND].astype(np.int16)
        if previous is not None:
            fine.append(int((np.abs(band - previous) > LEVEL).sum()) <= FINE_PIXELS)
        if k % 2 == 0:
            if key is not None:
                coarse.append(float((np.abs(band - key) > LEVEL).mean()) < COARSE_SHARE)
            key = band
        previous = band
    if previous is None:
        msg = "The scan read no frames, so it cannot judge the film"
        raise StillScanError(msg)
    words = np.array(
        [(w["start"], w["end"]) for s in timeline["segments"] for w in s["words"]]
    ).reshape(-1, 2)

    def report(still: list[bool], step: float) -> list[dict]:
        found = [(a, b, speech(words, a, b)) for a, b in runs(still, step)]
        return [
            {"start": round(a, 2), "end": round(b, 2), "speech": round(s, 2)}
            for a, b, s in found
            if s >= REPORTED_SPEECH_SECONDS
        ]

    fine_runs = report(fine, 1 / FPS)
    return {
        "fps": FPS,
        "frames": len(fine),
        "fine": {
            "rule": FINE_RULE,
            "runs": fine_runs,
        },
        "coarse": {
            "rule": COARSE_RULE,
            "runs": report(coarse, 2 / FPS),
        },
        "longest_fine_speech": max((run["speech"] for run in fine_runs), default=0),
    }


def worst(reports: list[dict]) -> dict:
    """The phase whose fine measure finds the most speech over a still picture."""
    chosen = max(reports, key=lambda report: report["longest_fine_speech"])
    return {**chosen, "phases": len(reports)}


def over_limit(report: dict, limit: float = LIMIT_SECONDS) -> list[dict]:
    """The fine measure's still runs that carry at least `limit` seconds of speech."""
    return [run for run in report["fine"]["runs"] if run["speech"] >= limit]


def frame_rate(movie: Path) -> int:
    """The movie's video frame rate, which must be a whole multiple of FPS."""
    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=r_frame_rate",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(movie),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    numerator, _, denominator = probe.stdout.strip().partition("/")
    if probe.returncode or not numerator.isdigit():
        msg = f"FFmpeg read no frames from {movie} (ffprobe exit {probe.returncode})"
        raise StillScanError(msg)
    rate = int(numerator) / int(denominator or 1)
    if rate != round(rate) or round(rate) % FPS:
        msg = f"{movie} runs at {rate} fps, not a whole multiple of {FPS}"
        raise StillScanError(msg)
    return round(rate)


def decode(movie: Path, phase: int = 0) -> Iterator[np.ndarray]:
    """The movie's frames at FPS as 480x270 grey arrays, from its frame `phase` on.

    A 60 fps film is read at every sixth frame and a 10 fps draft at every frame, so its two
    phases differ only on a film fast enough to have a frame between its samples.
    """
    every = frame_rate(movie) // FPS
    sample = f"select='eq(mod(n\\,{every})\\,{phase % every})',"
    command = [
        "ffmpeg",
        "-v",
        "error",
        "-i",
        str(movie),
        "-an",
        "-vf",
        f"{sample}scale={WIDTH}:{HEIGHT}:flags=area,format=gray",
        "-fps_mode",
        "passthrough",
        "-f",
        "rawvideo",
        "-",
    ]
    size, read = WIDTH * HEIGHT, 0
    with subprocess.Popen(command, stdout=subprocess.PIPE) as process:
        while len(buffer := process.stdout.read(size)) == size:
            read += 1
            yield np.frombuffer(buffer, np.uint8).reshape(HEIGHT, WIDTH)
    if process.returncode or not read:
        msg = f"FFmpeg read no frames from {movie} (exit {process.returncode})"
        raise StillScanError(msg)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Report still pictures with speech in a rendered film."
    )
    parser.add_argument("movie")
    parser.add_argument("timeline")
    parser.add_argument("--out", required=True)
    parser.add_argument(
        "--limit", type=float, default=LIMIT_SECONDS, help="Fail a still run with this much speech"
    )
    options = parser.parse_args(argv)
    timeline = repository.read(options.timeline)
    movie = repository.ROOT / options.movie
    report = worst([scan(decode(movie, phase), timeline) for phase in PHASES])
    failing = over_limit(report, options.limit)
    # The record names the film and timeline it judged, so its result stays bound to them.
    subjects = {
        "movie": {"path": options.movie, "sha256": repository.sha(movie)},
        "timeline": {
            "path": options.timeline,
            "sha256": repository.sha(repository.ROOT / options.timeline),
        },
    }
    repository.write(
        options.out,
        {**subjects, **report, "limit_seconds": options.limit, "over_limit": failing},
    )
    print(
        json.dumps(
            {"longest_fine_speech": report["longest_fine_speech"], "over_limit": len(failing)}
        )
    )
    if failing:
        sys.exit(1)


if __name__ == "__main__":
    main()
