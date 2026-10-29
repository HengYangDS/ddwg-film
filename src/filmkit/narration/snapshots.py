"""The pinned speech models: each snapshot's hub repository, revision, files and weights.

The supply task places each snapshot in its folder below the repository root through
huggingface_hub, which records every downloaded file's hub revision and hash beside it. A
snapshot whose weights or recorded revision differ from its pins is refused before a model
loads from it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import filmkit.repository as repository

if TYPE_CHECKING:
    from pathlib import Path

# Where a download into a folder records each file's hub revision and hash, below that folder.
DOWNLOAD_RECORDS = ".cache/huggingface/download"


class SnapshotError(ValueError):
    """A model folder is not its pinned snapshot."""


@dataclass(frozen=True)
class Snapshot:
    """A model at one hub revision: the files to fetch, its folder and each weights' SHA-256."""

    name: str
    repo: str
    revision: str
    files: tuple[str, ...]
    folder: str
    weights: dict[str, str]

    def verify(self, folder: Path | None = None) -> None:
        """Refuse a folder whose weights or recorded revision differ from the pins.

        The folder is the snapshot's own unless another is named.
        """
        folder = repository.ROOT / (folder or self.folder)
        for name, digest in self.weights.items():
            weights = folder / name
            if not weights.is_file() or repository.sha(weights) != digest:
                msg = f"The {self.name} weights differ from the pinned SHA-256: {name}"
                raise SnapshotError(msg)
            record = folder / DOWNLOAD_RECORDS / f"{name}.metadata"
            if not record.is_file():
                msg = f"The {self.name} snapshot does not record its hub revision"
                raise SnapshotError(msg)
            if record.read_text().splitlines()[:2] != [self.revision, digest]:
                msg = f"The {self.name} snapshot is not hub revision {self.revision}"
                raise SnapshotError(msg)


VOICE = Snapshot(
    "voice",
    "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-bf16",
    "a6eb4f68e4b056f1215157bb696209bc82a6db48",
    ("*.json", "*.txt", "*.safetensors", "README.md"),
    "build/runtime/tool-cache/narration-voice",
    {
        "model.safetensors": "81fb76175ff74e69be25fef2cc3e54f016df3034f1514c8e1c89da06a3510cff",
        "speech_tokenizer/model.safetensors": (
            "836b7b357f5ea43e889936a3709af68dfe3751881acefe4ecf0dbd30ba571258"
        ),
    },
)
RECOGNIZER = Snapshot(
    "recognizer",
    "mlx-community/Qwen3-ASR-0.6B-bf16",
    "eae2b51f96265328f1e7beced788adb0e4536f92",
    ("*.json", "*.txt", "*.safetensors", "*.model", "*.tiktoken", "README.md"),
    "build/runtime/tool-cache/narration-recognizer",
    {"model.safetensors": "a6e635fd9c8dfd5cdd7465db9bd8c947ab30737b90b83b6b09c304e836bb8a7f"},
)
ALIGNER = Snapshot(
    "aligner",
    "mlx-community/Qwen3-ForcedAligner-0.6B-bf16",
    "53c8c0e46733eec430e4b53dd6471d0e5dee45f8",
    ("*",),
    "build/runtime/tool-cache/narration-aligner",
    {"model.safetensors": "9d0728e17e28ee122c366bfaa9748ccbbb8fc3df4c0ce09dd8a5eac8202989e8"},
)
