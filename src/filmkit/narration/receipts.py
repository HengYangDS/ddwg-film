"""A narration receipt's records, read only while they still match what they record.

Alignment, transcription and auditions read a receipt's recordings; each record must still
name its recording's exact bytes, its text's SHA-256 and the language they are read in.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import filmkit.repository as repository

if TYPE_CHECKING:
    from pathlib import Path


def bound_records(receipt: str | Path, language: str) -> list[dict]:
    """The receipt's records, each still bound to its recording, text and language.

    A record without a language is read in the requested one.
    """
    records = repository.read(receipt)["records"]
    for record in records:
        if repository.sha(record["path"]) != record["wav_sha256"]:
            msg = f"{record['id']}: the recording differs from its receipt"
            raise ValueError(msg)
        if repository.content_sha(record["text"]) != record["text_sha256"]:
            msg = "Recording text binding differs"
            raise ValueError(msg)
        if record.get("language", language) != language:
            msg = f"{record['id']}: the recording language differs"
            raise ValueError(msg)
    return records
