"""What the review measurements share: a soundtrack's samples and each thought's aligned span."""

from __future__ import annotations

import wave
from typing import TYPE_CHECKING

import numpy as np

import filmkit.narration.spoken_units as spoken_units
from filmkit.review import ReviewError

if TYPE_CHECKING:
    from pathlib import Path


def wav_frames(path: Path) -> tuple[np.ndarray, int]:
    """16-bit PCM of a WAV file as samples by channels, and its sample rate."""
    with wave.open(str(path)) as audio:
        pcm = np.frombuffer(audio.readframes(audio.getnframes()), dtype="<i2")
        return pcm.reshape(-1, audio.getnchannels()), audio.getframerate()


def thought_spans(segment: dict) -> list[tuple[float, float]]:
    """Start and end of each thought: the first and last aligned words of its utterance group."""
    words = segment["words"]
    try:
        spans = spoken_units.thought_spans(segment["text"], words, segment["utterance_groups"])
    except spoken_units.AlignmentError as error:
        msg = f"{segment['id']}: {error}"
        raise ReviewError(msg) from error
    return [(words[span.first]["start"], words[span.last]["end"]) for span in spans]
