"""Narration alignment against the exact waveform with the pinned forced aligner."""

import dataclasses
import hashlib
import json

import pytest

import filmkit.narration.alignment as narration_alignment
import filmkit.repository as repository
from filmkit.narration.snapshots import ALIGNER

REPO = "mlx-community/Qwen3-ForcedAligner-0.6B-bf16"
REVISION = "53c8c0e46733eec430e4b53dd6471d0e5dee45f8"
WEIGHTS = b"pinned aligner weights"


def sha256(data: bytes | str) -> str:
    return hashlib.sha256(data.encode() if isinstance(data, str) else data).hexdigest()


@dataclasses.dataclass
class Item:
    text: str
    start_time: float
    end_time: float


class Aligner:
    """An aligner double that records each recording, text and language it aligns."""

    def __init__(self) -> None:
        self.calls = []
        self.loads = []

    def generate(self, audio, *, text, language):
        self.calls.append((audio, text, language))
        return type("Alignment", (), {"items": [Item(text, 0.0, 1.0)]})()


@pytest.fixture
def aligner(tmp_path, monkeypatch):
    """One recording's receipt and an aligner snapshot whose weights stand in for the pin."""
    monkeypatch.setattr(repository, "ROOT", tmp_path)
    (tmp_path / "record.wav").write_bytes(b"test waveform")
    record = {
        "id": "01",
        "path": "record.wav",
        "wav_sha256": sha256(b"test waveform"),
        "text": "记录",
        "text_sha256": sha256("记录"),
        "language": "Chinese",
    }
    repository.write("record.json", {"records": [record]})
    folder = tmp_path / "aligner"
    download = folder / ".cache/huggingface/download"
    download.mkdir(parents=True)
    (folder / "model.safetensors").write_bytes(WEIGHTS)
    (download / "model.safetensors.metadata").write_text(
        f"{REVISION}\n{sha256(WEIGHTS)}\n1792709337.748203\n"
    )
    pinned = dataclasses.replace(ALIGNER, weights={"model.safetensors": sha256(WEIGHTS)})
    monkeypatch.setattr(narration_alignment, "ALIGNER", pinned)
    model = Aligner()

    def load_model(path):
        model.loads.append(path)
        return model

    monkeypatch.setattr(narration_alignment, "load_model", load_model)
    model.folder = folder
    model.arguments = ["--model", str(folder), "--receipt", "record.json"]
    model.arguments += ["--output", "result.json"]
    return model


def test_alignment_binds_waveform_and_reuses_exact_cache(tmp_path, aligner):
    narration_alignment.main(aligner.arguments)
    assert repository.read("result.json")["records"][0]["wav_sha256"] == sha256(b"test waveform")
    assert aligner.calls == [(str(tmp_path / "record.wav"), "记录", "Chinese")]
    narration_alignment.main(aligner.arguments)
    assert len(aligner.calls) == 1
    cache = next((tmp_path / "build/evidence/alignment-records/chinese").glob("*.json"))
    original_cache = cache.read_bytes()
    original_result = (tmp_path / "result.json").read_bytes()
    stale = json.loads(original_cache)
    stale["text_sha256"] = sha256("旧稿")
    cache.write_text(json.dumps(stale))
    stale_cache = cache.read_bytes()
    with pytest.raises(ValueError, match="Cached alignment text binding differs"):
        narration_alignment.main(aligner.arguments)
    assert cache.read_bytes() == stale_cache
    assert (tmp_path / "result.json").read_bytes() == original_result
    cache.write_bytes(original_cache)
    manifest = repository.read("record.json")
    manifest["records"][0]["text"] = "修订后的记录"
    repository.write("record.json", manifest)
    with pytest.raises(ValueError, match="Recording text binding differs"):
        narration_alignment.main(aligner.arguments)
    assert len(aligner.calls) == 1
    assert (tmp_path / "result.json").read_bytes() == original_result


def test_a_changed_recording_is_refused_before_the_aligner_loads(tmp_path, aligner):
    (tmp_path / "record.wav").write_bytes(b"changed waveform")
    with pytest.raises(ValueError, match="01: the recording differs from its receipt"):
        narration_alignment.main(aligner.arguments)
    assert aligner.loads == []
    assert not (tmp_path / "result.json").exists()


def test_alignment_records_the_pinned_aligner(aligner):
    narration_alignment.main(aligner.arguments)
    identity = {"repo": REPO, "revision": REVISION, "weights_sha256": sha256(WEIGHTS)}
    result = repository.read("result.json")
    assert result["aligner"] == identity
    assert result["records"][0]["aligner"] == identity
    assert result["model"] == "Qwen3-ForcedAligner-0.6B"
    assert aligner.loads == [str(aligner.folder)]


def metadata(folder):
    return folder / ".cache/huggingface/download/model.safetensors.metadata"


@pytest.mark.parametrize(
    ("tamper", "message"),
    [
        (
            lambda folder: (folder / "model.safetensors").write_bytes(b"other weights"),
            "aligner weights differ from the pinned SHA-256",
        ),
        (
            lambda folder: metadata(folder).write_text(f"{'0' * 40}\n{sha256(WEIGHTS)}\n0\n"),
            f"aligner snapshot is not hub revision {REVISION}",
        ),
        (lambda folder: metadata(folder).unlink(), "does not record its hub revision"),
    ],
    ids=["weights", "revision", "unrecorded"],
)
def test_an_aligner_that_is_not_the_pinned_snapshot_is_refused(tmp_path, aligner, tamper, message):
    tamper(aligner.folder)
    with pytest.raises(ValueError, match=message):
        narration_alignment.main(aligner.arguments)
    assert aligner.loads == []
    assert not (tmp_path / "result.json").exists()


def test_a_cached_alignment_from_another_aligner_is_not_reused(tmp_path, aligner):
    unbound = tmp_path / "build/evidence/alignment-records/chinese/01-{}.json".format(
        sha256(b"test waveform")[:12]
    )
    repository.write(
        unbound,
        {
            "id": "01",
            "items": [],
            "wav_sha256": sha256(b"test waveform"),
            "text_sha256": sha256("记录"),
        },
    )
    retained = unbound.read_bytes()
    narration_alignment.main(aligner.arguments)
    assert len(aligner.calls) == 1
    assert unbound.read_bytes() == retained
    (cache,) = (path for path in unbound.parent.glob("*.json") if path != unbound)
    bound = json.loads(cache.read_text())
    cache.write_text(json.dumps({**bound, "aligner": {**bound["aligner"], "revision": "0" * 40}}))
    with pytest.raises(ValueError, match="Cached alignment aligner binding differs"):
        narration_alignment.main(aligner.arguments)


@pytest.mark.parametrize("missing", ["--model", "--receipt", "--output"])
def test_every_aligner_input_and_output_is_named(aligner, missing):
    at = aligner.arguments.index(missing)
    with pytest.raises(SystemExit):
        narration_alignment.main(aligner.arguments[:at] + aligner.arguments[at + 2 :])
    assert aligner.loads == []
