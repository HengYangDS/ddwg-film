"""Align each narration recording against its exact text with the pinned forced aligner.

The aligner is the pinned `snapshots.ALIGNER` snapshot. A model folder that is not that
snapshot is refused before it loads, and every alignment records the aligner. Each
recording's alignment is cached under its waveform and the aligner revision, and a cache is
reused only while it still binds the recording, its text and the aligner.

Usage: python -m filmkit.narration.alignment --model DIR --receipt FILE --output FILE
    [--language Chinese|English]
Paths are relative to the repository root.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
from pathlib import Path

from mlx_audio.stt.utils import load_model

import filmkit.repository as repository
from filmkit.narration.alignment_records import alignment_record
from filmkit.narration.receipts import bound_records
from filmkit.narration.snapshots import ALIGNER
from filmkit.narration.thought_groups import validate_group_inputs


def verify_aligner(folder: Path) -> dict:
    """Refuse a model folder that is not the pinned aligner snapshot.

    Returns:
        The aligner's identity: its hub repository, revision and weights SHA-256.
    """
    ALIGNER.verify(folder)
    return {
        "repo": ALIGNER.repo,
        "revision": ALIGNER.revision,
        "weights_sha256": ALIGNER.weights["model.safetensors"],
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Align narration recordings to their text.")
    parser.add_argument("--model", type=Path, required=True, help="The pinned aligner's folder")
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--language", choices=("Chinese", "English"), default="Chinese")
    options = parser.parse_args(argv)
    records = bound_records(options.receipt, options.language)
    for record in records:
        validate_group_inputs(record, root=repository.ROOT)
    folder = repository.ROOT / options.model
    aligner = verify_aligner(folder)
    model = load_model(str(folder))
    results = []
    for record in records:
        aligned = _aligned(model, record, aligner, options.language)
        results.append(aligned)
        print(json.dumps({"id": record["id"], "items": len(aligned["items"])}), flush=True)
    repository.write(
        options.output,
        {
            "records": results,
            "model": "Qwen3-ForcedAligner-0.6B",
            "language": options.language,
            "scope": "Waveform alignment, not pronunciation certification",
            "aligner": aligner,
        },
    )


def _aligned(model, record: dict, aligner: dict, language: str) -> dict:
    """The record's alignment from its bound cache, or from the aligner and then cached."""
    path = repository.ROOT / alignment_record(
        language, record["id"], record["wav_sha256"], aligner["revision"]
    )
    if path.exists():
        aligned = repository.read(path)
        if aligned["text_sha256"] != record["text_sha256"]:
            msg = "Cached alignment text binding differs"
            raise ValueError(msg)
        if aligned["wav_sha256"] != record["wav_sha256"] or aligned["id"] != record["id"]:
            msg = "Cached alignment recording binding differs"
            raise ValueError(msg)
        if aligned.get("aligner") != aligner:
            msg = "Cached alignment aligner binding differs"
            raise ValueError(msg)
        return aligned
    generated = model.generate(
        str(repository.ROOT / record["path"]), text=record["text"], language=language
    )
    aligned = {
        "id": record["id"],
        "items": [dataclasses.asdict(item) for item in generated.items],
        "wav_sha256": record["wav_sha256"],
        "text_sha256": record["text_sha256"],
        "aligner": aligner,
    }
    repository.write(path, aligned)
    return aligned


if __name__ == "__main__":
    main()
