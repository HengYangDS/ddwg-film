"""Select the narration recordings and validate their voice, text and alignment."""

from __future__ import annotations

import functools
import json
from pathlib import Path
from typing import TYPE_CHECKING

import ddwg_film.repository as repository
from ddwg_film.narration.pronunciation import pronunciation_contract, pronunciation_text
from ddwg_film.narration.thought_groups import validate_group_inputs
from ddwg_film.repository import read, sha, write

if TYPE_CHECKING:
    from ddwg_film.production import Edition


class SelectionError(ValueError):
    """A recording or alignment differs from the script, cast or receipt it must match."""


def validate_voice_record(record: dict, cast: dict) -> None:
    """Bind a recording to the cast's narrator reference: its audio, transcript and treatment.

    The reference recording's SHA-256 is computed once for each state of its file, so a run
    that checks every recording of a cast reads the reference once.
    """
    reference = repository.ROOT / cast["reference_audio"]
    status = reference.stat()
    state = (status.st_dev, status.st_ino, status.st_size, status.st_mtime_ns, status.st_ctime_ns)
    if not _reference_matches(reference, cast["reference_sha256"], state):
        msg = f"{cast['reference_audio']}: the narrator reference differs from the cast's SHA-256"
        raise SelectionError(msg)
    expected = {
        "reference_audio": cast["reference_audio"],
        "reference_sha256": cast["reference_sha256"],
        "reference_text_sha256": repository.content_sha(cast["reference_text"]),
        "reference_treatment": cast.get("reference_treatment"),
    }
    if any(record.get(key) != value for key, value in expected.items()):
        msg = f"{record['id']}: the recording's narrator reference differs from the cast"
        raise SelectionError(msg)


@functools.lru_cache(maxsize=16)
def _reference_matches(path: Path, sha256: str, _state: tuple[int, ...]) -> bool:
    return sha(path) == sha256


def validate_aligned_recording(record: dict, aligned: dict) -> None:
    """Bind word timing to the exact selected paragraph and waveform."""
    if aligned.get("id") != record["id"]:
        msg = f"Selected alignment identity differs: {record['id']}"
        raise SelectionError(msg)
    if aligned.get("wav_sha256") != record["wav_sha256"]:
        msg = f"Selected alignment waveform differs: {record['id']}"
        raise SelectionError(msg)
    expected = repository.content_sha(record["text"])
    if record.get("text_sha256") != expected or aligned.get("text_sha256") != expected:
        msg = f"Selected alignment text differs: {record['id']}"
        raise SelectionError(msg)


def select(edition: Edition) -> None:
    """Bind the edition's declared recordings and alignment to its current script."""
    script = read(edition.script)
    cast = read(edition.cast)
    performance = cast.get("performance_recording")
    if not performance:
        msg = "A current declared performance recording is required"
        raise SelectionError(msg)
    candidates = {record["id"]: record for record in read(performance["receipt"])["records"]}
    contract, _ = pronunciation_contract(script, edition.language)
    records = []
    for segment in script["segments"]:
        record = dict(candidates[segment["id"]])
        _check_recording(record, segment, contract)
        record["path"] = _root_relative(record["path"])
        validate_voice_record(record, cast)
        records.append(record)
    alignment = read(performance["alignment"])
    aligned = {record["id"]: record for record in alignment["records"]}
    for record in records:
        validate_aligned_recording(record, aligned[record["id"]])
    write(
        edition.narration_selected,
        {
            "records": records,
            "script_sha256": sha(edition.script),
            "cast_sha256": sha(edition.cast),
            "selection": "Current paragraph text; original generation retained",
            "listening_acceptance": "Separate review required",
        },
    )
    write(edition.alignment_selected, alignment)
    print(json.dumps({"selected": len(records), "seconds": sum(r["duration"] for r in records)}))


def _check_recording(record: dict, segment: dict, contract: dict) -> None:
    """Check a recording's text, speech, waveform and thoughts against the current segment."""
    if record["text"] != segment["text"]:
        msg = f"Recording text differs: {segment['id']}"
        raise SelectionError(msg)
    if record.get("spoken_text", record["text"]) != pronunciation_text(segment, contract):
        msg = f"Recording spoken text differs: {segment['id']}"
        raise SelectionError(msg)
    if sha(record["path"]) != record["wav_sha256"]:
        msg = f"Recording waveform differs: {segment['id']}"
        raise SelectionError(msg)
    validate_group_inputs(record, root=repository.ROOT, section=segment)


def _root_relative(path: str) -> str:
    """A recording's path relative to the production root, which must hold it."""
    source = Path(path)
    resolved = (repository.ROOT / source).resolve()
    if (not source.is_absolute() and ".." in source.parts) or not resolved.is_relative_to(
        repository.ROOT.resolve()
    ):
        msg = "Selected recording must belong to the production root"
        raise SelectionError(msg)
    return resolved.relative_to(repository.ROOT.resolve()).as_posix()
