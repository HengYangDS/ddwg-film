"""The fixed delivery format of both editions: duration, rates, levels, limits and tags."""

from __future__ import annotations

import json

import ddwg_film.repository as repository
from ddwg_film.production import CODES, Edition


def _declared(key: str) -> int:
    """A whole-number value that both editions' scripts declare alike."""
    values = {
        int(json.loads((repository.ROOT / Edition(code).script).read_text())[key]) for code in CODES
    }
    if len(values) != 1:
        message = f"The editions' scripts declare different {key} values: {sorted(values)}"
        raise ValueError(message)
    return values.pop()


RATE = 48000
DURATION = _declared("duration")
FPS = 60
CREDITS_DURATION = _declared("credits_duration")
# The films' author, artist and copyright holder.
AUTHOR = "Yang HENG"
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
