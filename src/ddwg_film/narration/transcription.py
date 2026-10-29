"""Transcribe a narration receipt's recordings with the pinned, locally cached ASR model.

Each recording's unit error rate is the edit distance between the recognition units of its
text and of its transcript over the text's unit count. Recognition is a proxy for
pronunciation, not certification or listening.

Usage: python -m ddwg_film.narration.transcription
    --receipt FILE --output FILE --language Chinese|English
Paths are relative to the repository root. Every recording must still match the
SHA-256, text and language its receipt records.
"""

import argparse
import json
from pathlib import Path

from huggingface_hub import snapshot_download
from mlx_audio.stt.utils import load_model

import ddwg_film.repository as repository
from ddwg_film.narration.receipts import bound_records
from ddwg_film.narration.recognition import recognition_units, unit_distance

ASR_MODEL = "mlx-community/Qwen3-ASR-0.6B-bf16"
# The hub revision of the locally cached snapshot, read without any download.
ASR_REVISION = "eae2b51f96265328f1e7beced788adb0e4536f92"
ASR_FILES = ["*.json", "*.txt", "*.safetensors", "*.model", "*.tiktoken", "README.md"]
SCOPE = "Automatic transcription proxy; not pronunciation certification or listening."


def load_asr():
    """Load the pinned ASR snapshot from the local cache without downloading anything."""
    return load_model(
        snapshot_download(
            ASR_MODEL, revision=ASR_REVISION, local_files_only=True, allow_patterns=ASR_FILES
        )
    )


def transcribe(model, path: Path, language: str) -> str:
    """The model's transcript of one recording."""
    return model.generate(str(path), language=language).text


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Transcribe a narration receipt's recordings.")
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--language", choices=("Chinese", "English"), required=True)
    options = parser.parse_args(argv)
    records = bound_records(options.receipt, options.language)
    model = load_asr()
    results = []
    for record in records:
        heard = transcribe(model, repository.ROOT / record["path"], options.language)
        expected = recognition_units(record["text"])
        rate = round(unit_distance(expected, recognition_units(heard)) / max(1, len(expected)), 4)
        results.append(
            {
                "id": record["id"],
                "path": record["path"],
                "wav_sha256": record["wav_sha256"],
                "heard": heard,
                "unit_error_rate": rate,
            }
        )
        print(json.dumps({"id": record["id"], "unit_error_rate": rate}), flush=True)
    repository.write(
        options.output,
        {
            "model": ASR_MODEL,
            "revision": ASR_REVISION,
            "language": options.language,
            "scope": SCOPE,
            "records": results,
        },
    )


if __name__ == "__main__":
    main()
