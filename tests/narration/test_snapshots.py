"""The pinned speech model snapshots and their check."""

import re

import pytest

import filmkit.repository as repository
from filmkit.narration.snapshots import (
    ALIGNER,
    DOWNLOAD_RECORDS,
    RECOGNIZER,
    VOICE,
    Snapshot,
    SnapshotError,
)


def placed(folder, weights=b"weights", revision="a" * 40):
    """A one-file snapshot placed as a local-folder download records it, and its pins."""
    (folder / "model.safetensors").parent.mkdir(parents=True, exist_ok=True)
    (folder / "model.safetensors").write_bytes(weights)
    digest = repository.content_sha(weights)
    record = folder / DOWNLOAD_RECORDS / "model.safetensors.metadata"
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text(f"{revision}\n{digest}\n1761700000.0\n")
    weights = {"model.safetensors": digest}
    return Snapshot("voice", "org/voice", "a" * 40, ("*.safetensors",), str(folder), weights)


def test_a_placed_snapshot_verifies(tmp_path):
    placed(tmp_path).verify()


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (
            lambda folder: (folder / "model.safetensors").write_bytes(b"other"),
            "The voice weights differ from the pinned SHA-256: model.safetensors",
        ),
        (
            lambda folder: (folder / DOWNLOAD_RECORDS / "model.safetensors.metadata").unlink(),
            "The voice snapshot does not record its hub revision",
        ),
        (
            lambda folder: placed(folder, revision="b" * 40),
            "The voice snapshot is not hub revision a{40}",
        ),
    ],
)
def test_a_snapshot_that_is_not_its_pin_is_refused(tmp_path, change, message):
    snapshot = placed(tmp_path)
    change(tmp_path)
    with pytest.raises(SnapshotError, match=message):
        snapshot.verify()


def test_each_model_is_pinned_below_the_tool_cache():
    for snapshot in (VOICE, RECOGNIZER, ALIGNER):
        assert snapshot.folder.startswith("build/runtime/tool-cache/narration-")
        assert re.fullmatch(r"[0-9a-f]{40}", snapshot.revision)
        assert snapshot.weights
        assert all(re.fullmatch(r"[0-9a-f]{64}", digest) for digest in snapshot.weights.values())
