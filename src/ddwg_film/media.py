"""Read media files through FFmpeg: stream metadata, frame cadence, complete decodes, loudness.

Every command runs from the repository root with its input closed and a deadline. A file
that does not meet what a check requires raises `MediaError`.
"""

from __future__ import annotations

import json
import re
import subprocess
from fractions import Fraction
from typing import TYPE_CHECKING

import ddwg_film.repository as repository

if TYPE_CHECKING:
    from pathlib import Path


class MediaError(ValueError):
    """A media file differs from what its check requires."""


def probe(path: Path) -> dict:
    """The file's streams, format and chapters as FFprobe reports them."""
    command = ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-show_chapters"]
    return json.loads(repository.run([*command, "-of", "json", str(path)], timeout=240).stdout)


def video_cadence(path: Path, expected_frames: int, fps: int) -> dict:
    """Qualify every presentation time of the first video stream, including internal splices.

    Each frame must start within one tick of its place on the fps grid and last one frame.
    """
    data = json.loads(
        repository.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_packets",
                "-show_streams",
                "-show_entries",
                "stream=time_base:packet=pts,duration",
                "-of",
                "json",
                str(path),
            ],
            timeout=240,
        ).stdout
    )
    time_base = Fraction(data["streams"][0]["time_base"])
    step = Fraction(1, fps) / time_base
    packets = sorted(data["packets"], key=lambda packet: int(packet["pts"]))
    if len(packets) != expected_frames:
        msg = f"Unexpected presentation frame count: {len(packets)}"
        raise MediaError(msg)
    for frame, packet in enumerate(packets):
        if abs(Fraction(int(packet["pts"])) - frame * step) > 1:
            msg = f"Presentation cadence differs at frame {frame}: {packet['pts']} ticks"
            raise MediaError(msg)
        if abs(Fraction(int(packet["duration"])) - step) > 1:
            msg = f"Frame duration differs at frame {frame}: {packet['duration']} ticks"
            raise MediaError(msg)
    return {
        "frames": len(packets),
        "time_base": str(time_base),
        "fps": fps,
        "presentation_start": 0,
        "presentation_end": expected_frames / fps,
        "every_frame_checked": True,
    }


def decoded_video_frames(path: Path, expected_frames: int, timeout: int) -> int:
    """Decode the complete first video and audio streams and count the decoded frames.

    Any decoder message or exit status refuses the file, as does a count other than the
    expected one.
    """
    decode = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-xerror",
            "-nostdin",
            "-i",
            str(path),
            "-map",
            "0:v:0",
            "-map",
            "0:a:0",
            "-progress",
            "pipe:1",
            "-f",
            "null",
            "-",
        ],
        cwd=repository.ROOT,
        capture_output=True,
        check=False,
        stdin=subprocess.DEVNULL,
        timeout=timeout,
    )
    if decode.returncode != 0 or decode.stderr:
        msg = f"Decoding failed: {decode.stderr.decode()[:600]}"
        raise MediaError(msg)
    counts = re.findall(rb"(?m)^frame=(\d+)$", decode.stdout)
    if not counts or int(counts[-1]) != expected_frames:
        msg = f"Decoded {int(counts[-1]) if counts else 0} of {expected_frames} frames"
        raise MediaError(msg)
    return expected_frames


def decoded_audio_frames(path: Path) -> int:
    """Decode the first audio stream to 16-bit stereo and count its sample frames."""
    pcm = repository.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(path),
            "-map",
            "0:a:0",
            "-f",
            "s16le",
            "-acodec",
            "pcm_s16le",
            "-",
        ],
        timeout=240,
    ).stdout
    return len(pcm) // 4


def loudness(path: Path, timeout: int) -> dict:
    """Integrated loudness, loudness range and true peak by FFmpeg's EBU R128 meter."""
    log = repository.run(
        ["ffmpeg", "-nostats", "-i", str(path), "-af", "ebur128=peak=true", "-f", "null", "-"],
        timeout=timeout,
    ).stderr.decode()
    summary = log[log.rfind("Summary:") :]
    level = {}
    for key, label in (
        ("integrated_lufs", "I"),
        ("loudness_range_lu", "LRA"),
        ("true_peak_dbtp", "Peak"),
    ):
        found = re.search(label + r":\s+(-?[\d.]+)", summary)
        if found is None:
            msg = f"Loudness measurement returned no {key}"
            raise MediaError(msg)
        level[key] = float(found[1])
    return level


# Two durations agree when they differ by less than this many seconds.
DURATION_TOLERANCE = 1e-6


def video_stream(info: dict) -> dict:
    """The probed file's video stream: the first one that is not an attached cover picture."""
    for stream in info.get("streams", []):
        cover = stream.get("disposition", {}).get("attached_pic")
        if stream.get("codec_type") == "video" and not cover:
            return stream
    msg = "The file holds no video stream besides a cover picture"
    raise MediaError(msg)


def require_video(
    info: dict, *, frames: int, fps: int, size: tuple[int, int], duration: float
) -> dict:
    """The probed file's video stream, refused unless it meets the video contract.

    The stream must hold `frames` frames at `fps` and `size`, and both the stream and the
    container must last `duration` within `DURATION_TOLERANCE` seconds.
    """
    video, container = video_stream(info), info.get("format", {})
    seconds = {
        "stream duration": _parsed(float, video.get("duration")),
        "container duration": _parsed(float, container.get("duration")),
    }
    held = {
        "frame count": _parsed(int, video.get("nb_frames")) == frames,
        "frame rate": _parsed(Fraction, video.get("avg_frame_rate")) == fps,
        "frame size": (video.get("width"), video.get("height")) == tuple(size),
    } | {
        name: value is not None and abs(value - duration) < DURATION_TOLERANCE
        for name, value in seconds.items()
    }
    differing = [name for name, met in held.items() if not met]
    if differing:
        name = container.get("filename", "the file")
        msg = f"Video differs from its contract in {name}: {', '.join(differing)}"
        raise MediaError(msg)
    return video


def _parsed(kind: type, value: object) -> object | None:
    """A probe field read as `kind`, or None when it is absent or not of that kind."""
    try:
        return kind(value)
    except (TypeError, ValueError, ZeroDivisionError):
        return None
