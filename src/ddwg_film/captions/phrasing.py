"""Give each segment its caption phrases: authored cue boundaries, or the edition's own.

A script may author a segment's cue boundaries; otherwise the Chinese or English phrasing
sets them. Either way the phrases must hold the exact narration, each on one readable line,
and no English phrase may cross the end of a caption sentence.
"""

from __future__ import annotations

from ddwg_film.captions import CaptionError
from ddwg_film.captions.chinese import caption_phrases
from ddwg_film.captions.english import english_caption_phrases, english_caption_sentences
from ddwg_film.specification import CAPTION_LIMITS


def _crosses_sentence(text: str, phrases: list[str], limit: int) -> bool:
    """Whether a phrase's words cross the end of a caption sentence."""
    boundaries, position = [], 0
    for sentence in english_caption_sentences(text, limit):
        boundaries.append(position + len(sentence.rstrip()))
        position += len(sentence)
    position = 0
    for phrase in phrases:
        start = position + len(phrase) - len(phrase.lstrip())
        end = position + len(phrase.rstrip())
        if any(start < boundary < end for boundary in boundaries):
            return True
        position += len(phrase)
    return False


def segment_caption_phrases(segment: dict, code: str) -> list[str]:
    """Keep authored cue boundaries and preserve the complete spoken copy of an edition."""
    automatic = english_caption_phrases if code == "en" else caption_phrases
    phrases = segment.get("caption_phrases") or automatic(segment["text"])
    if not phrases or "".join(phrases) != segment["text"]:
        msg = "Authored captions must preserve the complete exact narration"
        raise CaptionError(msg)
    limit = CAPTION_LIMITS[code]
    if any("\n" in phrase or len(phrase) > limit for phrase in phrases):
        msg = "Authored captions require readable single-line semantic cues"
        raise CaptionError(msg)
    if code == "en" and _crosses_sentence(segment["text"], phrases, limit):
        msg = "Authored English captions cross a thought-group boundary"
        raise CaptionError(msg)
    return phrases
