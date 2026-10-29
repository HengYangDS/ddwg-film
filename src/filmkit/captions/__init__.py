"""Phrase and time the subtitles of each edition.

A caption that cannot keep the exact narration in readable one-line cues bound to its aligned
words raises `CaptionError`.
"""


class CaptionError(ValueError):
    """Captions that cannot keep the exact narration within readable, word-bound cues."""
