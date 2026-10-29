"""The narration entry point: its model snapshot, buffers, requests, reuse and refusals."""

import hashlib
import json
import wave
from pathlib import Path
from types import SimpleNamespace

import mlx.core as mx
import numpy as np
import pytest

import filmkit.narration.group_generation as narration_group_generation
import filmkit.narration.synthesis as narration_synthesis
import filmkit.narration.thought_groups as narration_thought_groups
import filmkit.repository as repository
from filmkit.narration.voice_model import NATIVE_DECODER

RATE = 24000
GROUPS = ["先核验实际工作。", "再说明结论和限度。"]
ARGUMENTS = ["--script", "script.json", "--cast", "cast.json", "--folder", "audio"]
ARGUMENTS += ["--receipt", "receipt.json"]
GOLDEN = json.loads((Path(__file__).parent / "golden/receipts.json").read_text())


def sha256(data: bytes | str) -> str:
    return hashlib.sha256(data.encode() if isinstance(data, str) else data).hexdigest()


def write_sources(root, segments, **cast_changes) -> dict:
    """Write a script of grouped segments, its contract, a reference and its cast."""
    reference = root / "reference.wav"
    reference.write_bytes(b"approved synthetic reference")
    contract = {"normalization": []}
    repository.write(
        root / "contract.json",
        {"pronunciation": {"languages": {"Chinese": contract, "English": contract}}},
    )
    script = {
        "pronunciation_contract": "contract.json",
        "segments": [
            {"id": sid, "text": "".join(groups), "utterance_groups": groups}
            for sid, groups in segments.items()
        ],
    }
    repository.write(root / "script.json", script)
    cast = {
        "reference_audio": "reference.wav",
        "reference_sha256": sha256(reference.read_bytes()),
        "reference_text": "看清事实，作出判断。",
        "narration_language": "Chinese",
        "full_narration_seed": 4677,
        **cast_changes,
    }
    repository.write(root / "cast.json", cast)
    return cast


class Voice:
    """A model double that yields one take per thought and records each request."""

    sample_rate = RATE

    def __init__(self) -> None:
        self.calls = []

    def generate(self, **request):
        self.calls.append(request)
        yield SimpleNamespace(audio=np.full(2 * RATE, 0.11 * len(self.calls), dtype=np.float32))


@pytest.fixture
def voice(tmp_path, monkeypatch):
    """Load a voice double from its checked snapshot and record what reaches the vendor."""
    model = Voice()
    model.snapshots = []
    snapshot = SimpleNamespace(
        folder="voice-snapshot", verify=lambda: model.snapshots.append("verified")
    )

    def load_model(path):
        assert path == str(tmp_path / "voice-snapshot")
        return model

    monkeypatch.setattr(repository, "ROOT", tmp_path)
    monkeypatch.setattr(narration_group_generation, "VOICE", snapshot)
    monkeypatch.setattr(narration_group_generation, "load_model", load_model)
    previous = mx.set_cache_limit(0)
    mx.set_cache_limit(previous)
    yield model
    mx.set_cache_limit(previous)
    mx.clear_cache()


def files(root) -> dict:
    return {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}


def test_local_narration_bounds_retained_gpu_buffer_cache(tmp_path, voice, monkeypatch):
    write_sources(tmp_path, {"01": ["判断要有依据。", "证据先行。"]})
    retained = []

    def generate(**request):
        voice.calls.append(request)
        # A long decode frees many distinctly sized buffers before it yields.
        for megabytes in range(64, 256, 8):
            block = mx.zeros((megabytes << 20,), dtype=mx.uint8)
            mx.eval(block)
            retained.append(mx.get_cache_memory())
            del block
        yield SimpleNamespace(audio=np.full(2 * RATE, 0.1, dtype=np.float32))

    monkeypatch.setattr(voice, "generate", generate)
    narration_synthesis.main(ARGUMENTS)
    # MLX may recycle one freed block before the next allocation reclaims it.
    assert max(retained) <= (2 << 30) + (248 << 20)
    assert voice.snapshots == ["verified"]


def test_complete_thought_narration_preserves_source_native_tails_and_provenance(tmp_path, voice):
    """Dense narration can reset by thought without isolated cuts or hidden drift."""
    write_sources(tmp_path, {"26": GROUPS})
    narration_synthesis.main(ARGUMENTS)
    record = repository.read("receipt.json")["records"][0]
    assert [call["text"] for call in voice.calls] == GROUPS
    assert [call["stream"] for call in voice.calls] == [False, False]
    assert [call["ref_audio"] for call in voice.calls] == [str(tmp_path / "reference.wav")] * 2
    assert record["text"] == "".join(GROUPS)
    assert record["spoken_text"] == "".join(GROUPS)
    assert record["duration"] == 4.3
    assert record["post_pitch_transform"] is False
    assert record["post_tempo_transform"] is False
    assert record["utterance_groups"]["listening_accepted"] is False
    with wave.open(str(tmp_path / record["path"])) as audio:
        joined = np.frombuffer(audio.readframes(audio.getnframes()), dtype="<i2")
    for child in record["utterance_groups"]["records"]:
        with wave.open(str(tmp_path / child["path"])) as audio:
            source = np.frombuffer(audio.readframes(audio.getnframes()), dtype="<i2")
        start = child["start_sample"]
        assert np.array_equal(joined[start : start + len(source)], source)
    # Reuse verifies children and does not ask the model to repeat recordings.
    narration_synthesis.main(ARGUMENTS)
    assert len(voice.calls) == 2
    child_path = tmp_path / record["utterance_groups"]["records"][0]["path"]
    child_path.write_bytes(b"changed retained recording")
    with pytest.raises(RuntimeError, match="Retained utterance input changed"):
        narration_synthesis.main(ARGUMENTS)
    assert len(voice.calls) == 2


@pytest.mark.usefixtures("voice")
def test_a_written_receipt_keeps_the_retained_key_order(tmp_path):
    write_sources(tmp_path, {"26": GROUPS}, icl_repetition_penalty=None)
    narration_synthesis.main(ARGUMENTS)
    record = repository.read("receipt.json")["records"][0]
    golden = GOLDEN["en"]["record"]
    assert list(record) == list(golden)
    assert list(record["utterance_groups"]) == list(golden["utterance_groups"])
    assert [list(child) for child in record["utterance_groups"]["records"]] == [
        list(child) for child in golden["utterance_groups"]["records"][:2]
    ]
    assert repository.read(Path(record["path"]).with_suffix(".json")) == record
    assert repository.read(Path(record["path"]).with_suffix(".request.json")) == {
        "id": "26",
        "state": "received",
        "fingerprint": record["fingerprint"],
        "wav_sha256": record["wav_sha256"],
    }


def test_narration_entrypoint_preserves_vendor_decoder(tmp_path, voice, capsys):
    """Exercise the supported native call and its retained input/output binding."""
    write_sources(
        tmp_path,
        {"26": ["A complete spoken thought.", " Another complete thought."]},
        reference_text="A retained reference thought.",
        reference_language="English",
        narration_language="English",
    )

    class Tokenizer:
        def decode(self, _codes):
            msg = "Vendor decoder must remain untouched"
            raise AssertionError(msg)

    voice.speech_tokenizer = Tokenizer()
    narration_synthesis.main([*ARGUMENTS, "--dry-run"])
    plan = json.loads(capsys.readouterr().out)
    assert plan["decoder"] == NATIVE_DECODER
    assert plan["stream"] is False
    assert "streaming_interval" not in plan
    narration_synthesis.main(ARGUMENTS)
    result = repository.read("receipt.json")["records"][0]
    assert [call["ref_text"] for call in voice.calls] == ["A retained reference thought."] * 2
    assert all("streaming_interval" not in call for call in voice.calls)
    assert result["duration"] == 4.3
    assert result["decoder"] == plan["decoder"]
    assert result["stream"] is False
    assert "streaming_interval" not in result
    assert result["chunks"] == 2
    assert result["wav_sha256"] == sha256((tmp_path / result["path"]).read_bytes())
    assert voice.speech_tokenizer.decode.__func__ is Tokenizer.decode


def test_declared_penalty_and_thought_retakes_bind_through_reuse(tmp_path, voice, monkeypatch):
    """A declared penalty and a text-bound retake seed reach the vendor generator."""
    retakes = {"26": {"groups": {"2": {"seed": 9999, "text_sha256": sha256(GROUPS[1])}}}}
    write_sources(tmp_path, {"26": GROUPS}, icl_repetition_penalty=1.05, retakes=retakes)
    calls, seeds, references = [], [], []

    def generate(**_):
        msg = "A declared penalty must not pass through the floor"
        raise AssertionError(msg)

    def generate_icl(**request):
        calls.append(request)
        yield SimpleNamespace(audio=np.full(2 * RATE, 0.11 * len(calls), dtype=np.float32))

    def load_audio(path, *, sample_rate):
        references.append((path, sample_rate))
        return np.zeros(8)

    monkeypatch.setattr(voice, "generate", generate)
    monkeypatch.setattr(voice, "_generate_icl", generate_icl, raising=False)
    monkeypatch.setattr(narration_group_generation, "load_audio", load_audio)
    monkeypatch.setattr(narration_group_generation.mx.random, "seed", seeds.append)
    narration_synthesis.main(ARGUMENTS)
    record = repository.read("receipt.json")["records"][0]
    assert [call["text"] for call in calls] == GROUPS
    assert [call["repetition_penalty"] for call in calls] == [1.05, 1.05]
    assert [call["language"] for call in calls] == ["Chinese", "Chinese"]
    assert references == [(str(tmp_path / "reference.wav"), RATE)] * 2
    assert seeds == [4677 + 26, 9999]
    children = record["utterance_groups"]["records"]
    assert [child["seed"] for child in children] == [4677 + 26, 9999]
    assert record["icl_repetition_penalty"] == 1.05
    script = repository.read("script.json")
    narration_thought_groups.validate_group_inputs(
        record, root=tmp_path, section=script["segments"][0]
    )
    narration_synthesis.main(ARGUMENTS)
    assert len(calls) == 2
    receipt = tmp_path / children[1]["receipt"]
    retained = json.loads(receipt.read_text())
    receipt.write_text(json.dumps({**retained, "seed": 4677 + 26}))
    with pytest.raises(RuntimeError, match="Retained utterance"):
        narration_thought_groups.validate_group_inputs(record, root=tmp_path)


@pytest.mark.parametrize(
    ("cast_changes", "error", "message"),
    [
        ({"icl_repetition_penalty": 1.5}, ValueError, "ICL repetition penalty"),
        ({"icl_repetition_penalty": 0.9}, ValueError, "ICL repetition penalty"),
        ({"icl_repetition_penalty": 1}, ValueError, "ICL repetition penalty"),
        ({"reference_sha256": "0" * 64}, RuntimeError, "Reference identity changed"),
        ({"reference_text_sha256": "0" * 64}, RuntimeError, "Reference transcript identity"),
        ({"reference_mode": "x_vector"}, ValueError, "ICL mode"),
        ({"provider": "edge"}, ValueError, "local MLX voice model"),
        ({"provider": "dmxapi"}, ValueError, "local MLX voice model"),
    ],
)
def test_a_cast_is_refused_before_any_effect(tmp_path, voice, cast_changes, error, message):
    write_sources(tmp_path, {"01": GROUPS}, **cast_changes)
    before = files(tmp_path)
    with pytest.raises(error, match=message):
        narration_synthesis.main(ARGUMENTS)
    assert files(tmp_path) == before
    assert voice.snapshots == []


def test_the_local_mlx_provider_is_admitted(tmp_path, voice):
    write_sources(tmp_path, {"01": GROUPS}, provider="mlx")
    narration_synthesis.main(ARGUMENTS)
    assert len(voice.calls) == 2


def test_an_unknown_segment_id_is_refused(tmp_path, voice):
    write_sources(tmp_path, {"01": GROUPS})
    with pytest.raises(ValueError, match="Unknown section ID"):
        narration_synthesis.main([*ARGUMENTS, "--ids", "01,99"])
    assert voice.calls == []


@pytest.mark.parametrize(
    "arguments",
    [ARGUMENTS[2:], ARGUMENTS[:2] + ARGUMENTS[4:], ARGUMENTS[:4] + ARGUMENTS[6:], ARGUMENTS[:6]],
    ids=["no-script", "no-cast", "no-folder", "no-receipt"],
)
def test_every_source_and_destination_is_named(tmp_path, voice, arguments):
    write_sources(tmp_path, {"01": GROUPS})
    with pytest.raises(SystemExit):
        narration_synthesis.main(arguments)
    assert voice.calls == []


def dry_run(capsys, arguments=ARGUMENTS) -> list[dict]:
    capsys.readouterr()
    narration_synthesis.main([*arguments, "--dry-run"])
    return [json.loads(line) for line in capsys.readouterr().out.splitlines()]


def test_named_segments_replace_theirs_in_the_receipt(tmp_path, voice, capsys):
    write_sources(tmp_path, {"01": GROUPS, "02": ["只改这一段。", "其余照旧。"], "03": GROUPS})
    previous = [{"id": "01", "kept": True}, {"id": "02", "kept": False}, {"id": "03", "kept": True}]
    repository.write("receipt.json", {"records": previous})
    narration_synthesis.main([*ARGUMENTS, "--ids", "02"])
    capsys.readouterr()
    records = repository.read("receipt.json")["records"]
    assert [record["id"] for record in records] == ["01", "02", "03"]
    assert [records[0], records[2]] == [previous[0], previous[2]]
    assert records[1]["text"] == "只改这一段。其余照旧。"
    assert [call["text"] for call in voice.calls] == ["只改这一段。", "其余照旧。"]


def test_an_attempt_that_started_and_wrote_nothing_is_generated_again(tmp_path, voice, capsys):
    write_sources(tmp_path, {"01": GROUPS})
    (plan,) = dry_run(capsys)
    assert plan["state"] == "generate"
    attempt = (tmp_path / plan["path"]).with_suffix(".request.json")
    repository.write(attempt, {"id": "01", "state": "started", "fingerprint": plan["fingerprint"]})
    narration_synthesis.main(ARGUMENTS)
    assert [call["text"] for call in voice.calls] == GROUPS
    assert repository.read(attempt)["state"] == "received"
    assert dry_run(capsys)[0]["state"] == "reuse"


@pytest.mark.parametrize(
    "leftover",
    [
        lambda path, _plan: path.write_bytes(b"orphaned recording"),
        lambda path, _plan: path.with_suffix(".json").write_text("{}"),
        lambda path, plan: path.with_suffix(".request.json").write_text(
            json.dumps({"state": "received", "fingerprint": plan["fingerprint"]})
        ),
        lambda path, _plan: path.with_suffix(".request.json").write_text(
            json.dumps({"state": "started", "fingerprint": "0" * 64})
        ),
    ],
    ids=["recording", "receipt", "received-attempt", "foreign-attempt"],
)
def test_an_unresolved_recording_is_refused_before_any_effect(tmp_path, voice, capsys, leftover):
    write_sources(tmp_path, {"01": GROUPS})
    (plan,) = dry_run(capsys)
    path = tmp_path / plan["path"]
    path.parent.mkdir(parents=True, exist_ok=True)
    leftover(path, plan)
    before = files(tmp_path)
    (refused,) = dry_run(capsys)
    assert refused["state"] == "refuse"
    assert refused["refusal"].startswith("An unresolved recording exists")
    with pytest.raises(RuntimeError, match="An unresolved recording exists"):
        narration_synthesis.main(ARGUMENTS)
    assert files(tmp_path) == before
    assert voice.calls == []
    assert voice.snapshots == []


def test_a_changed_reference_treatment_refuses_reuse(tmp_path, voice, capsys):
    write_sources(tmp_path, {"01": GROUPS})
    narration_synthesis.main(ARGUMENTS)
    cast = repository.read("cast.json")
    repository.write("cast.json", {**cast, "reference_treatment": {"pitch_shift": 0}})
    with pytest.raises(RuntimeError, match="Reference treatment differs from retained receipt"):
        narration_synthesis.main(ARGUMENTS)
    assert dry_run(capsys)[0]["refusal"] == "Reference treatment differs from retained receipt"
    assert len(voice.calls) == 2


@pytest.mark.parametrize("code", sorted(GOLDEN))
def test_the_speech_plan_reproduces_the_retained_requests(code):
    golden = GOLDEN[code]
    segment = golden["segment"]
    request = narration_synthesis.Request(
        cast=golden["cast"],
        language=golden["language"],
        contract={"normalization": golden["normalization"]},
        contract_path=golden["pronunciation_contract"],
        contract_sha256=golden["pronunciation_contract_sha256"],
        segments=[segment],
        folder=repository.ROOT / Path(golden["record"]["path"]).parent,
        receipt=repository.ROOT / "receipt.json",
        merge=False,
        dry_run=True,
    )
    (job,) = narration_synthesis.speech_plan(request)
    assert job.fingerprint == golden["record"]["fingerprint"]
    assert job.path == repository.ROOT / golden["record"]["path"]
    assert [thought.get("seed") for thought in job.plan] == [
        child["seed"] if child["seed"] != golden["record"]["seed"] else None
        for child in golden["record"]["utterance_groups"]["records"]
    ]
