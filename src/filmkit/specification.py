"""The delivery format of both editions: duration, rates, levels, limits, tags and credits."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import filmkit.repository as repository
from filmkit.production import CODES, Edition

if TYPE_CHECKING:
    from collections.abc import Callable


def declared(key: str, read: Callable[[Any], Any]) -> Any:
    """The value that both editions' scripts declare alike for a key, as `read` takes it."""
    scripts = [json.loads((repository.ROOT / Edition(code).script).read_text()) for code in CODES]
    values = {read(script[key]) for script in scripts}
    if len(values) != 1:
        message = f"The editions' scripts declare different {key} values: {sorted(values)}"
        raise ValueError(message)
    return values.pop()


def rendered_rate(fps: int) -> int:
    """A script's frame rate, refused unless it is the 60 fps the engine renders and encodes."""
    if fps != 60:
        message = f"The engine renders 60 fps films, not the {fps} fps the scripts declare"
        raise ValueError(message)
    return fps


RATE = 48000
DURATION: int = declared("duration", int)
# The H.264 levels below are set for this frame rate.
FPS: int = declared("fps", lambda fps: rendered_rate(int(fps)))
CREDITS_DURATION: int = declared("credits_duration", int)
# The films' author, artist and copyright holder.
AUTHOR: str = declared("author", str)
# The films' chapter count; each edition titles the chapters in its own language.
CHAPTERS: int = declared("chapters", len)
CAPTION_LIMITS = {"zh": 33, "en": 66}
# ISO 639-2 tags of each edition's drawn captions and narration.
ISO_LANGUAGES = {"zh": "zho", "en": "eng"}
# Both editions play at one spoken-word level; a single gain reaches it without dynamics
# processing, and the true-peak ceiling caps that gain.
PROGRAM_LEVEL = {"integrated_lufs": -16.5, "true_peak_ceiling_dbtp": -1.0}
# The picture's chapter card is fully shown 0.15 s after its scene starts and holds
# until the voice begins, so a chapter marker lands on the card, past the previous
# running head.
CHAPTER_CARD_SHOWN = 0.25
# H.264 level_idc by picture height for 60 fps delivery.
H264_LEVELS = {2160: 52, 1080: 42}
