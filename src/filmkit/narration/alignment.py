"""Align each narration recording against its exact text with the pinned forced aligner.

The aligner is `ALIGNER_REPO` at hub revision `ALIGNER_REVISION`, whose weights have the
SHA-256 `ALIGNER_WEIGHTS_SHA256`. A model folder that is not that snapshot is refused before
it loads, and every alignment records the aligner. Each recording's alignment is cached under
its waveform and the aligner revision, and a cache is reused only while it still binds the
recording, its text and the aligner.

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
from filmkit.narration.thought_groups import validate_group_inputs

ALIGNER_REPO = "mlx-community/Qwen3-ForcedAligner-0.6B-bf16"
ALIGNER_REVISION = "53c8c0e46733eec430e4b53dd6471d0e5dee45f8"
ALIGNER_WEIGHTS_SHA256 = "9d0728e17e28ee122c366bfaa9748ccbbb8fc3df4c0ce09dd8a5eac8202989e8"
# A Hugging Face download into a folder records each file's hub revision and hash here.
DOWNLOAD_RECORD = ".cache/huggingface/download/model.safetensors.metadata"


def verify_aligner(folder: Path) -> dict:
    """Refuse a model folder that is not the pinned aligner snapshot.

    Returns:
        The aligner's identity: its hub repository, revision and weights SHA-256.
    """
    if repository.sha(folder / "model.safetensors") != ALIGNER_WEIGHTS_SHA256:
        msg = "The aligner weights differ from the pinned SHA-256"
        raise ValueError(msg)
    download = folder / DOWNLOAD_RECORD
    if not download.is_file():
        msg = "The aligner snapshot does not record its hub revision"
        raise ValueError(msg)
    if download.read_text().splitlines()[:2] != [ALIGNER_REVISION, ALIGNER_WEIGHTS_SHA256]:
        msg = f"The aligner snapshot is not hub revision {ALIGNER_REVISION}"
        raise ValueError(msg)
    return {
        "repo": ALIGNER_REPO,
        "revision": ALIGNER_REVISION,
        "weights_sha256": ALIGNER_WEIGHTS_SHA256,
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
