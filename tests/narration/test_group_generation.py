"""Native thought recordings generated, reused, joined and recovered through the voice model."""

import json
from types import SimpleNamespace

import numpy as np
import pytest

import ddwg_film.narration.group_generation as narration_group_generation
import ddwg_film.narration.thought_groups as narration_thought_groups
import ddwg_film.repository as repository

RATE = 24000


@pytest.mark.parametrize(
    ("field", "value"), [("text", "Changed."), ("seed", 999), ("frames", True), ("index", 2)]
)
def test_received_utterance_drift_refuses_before_recovery(
    retained_group_record, monkeypatch, field, value
):
    root, record, plans, settings = retained_group_record
    monkeypatch.setattr(repository, "ROOT", root)
    child = record["utterance_groups"]["records"][0]
    receipt = root / child["receipt"]
    body = json.loads(receipt.read_text())
    body[field] = value
    receipt.write_text(json.dumps(body))
    before = {p: p.read_bytes() for p in (root / "build").rglob("*") if p.is_file()}
    with pytest.raises(RuntimeError, match="Retained utterance"):
        narration_group_generation.generate_native_groups(
            SimpleNamespace(sample_rate=RATE),
            plans,
            root / record["path"],
            {"parent_fingerprint": record["fingerprint"], **settings},
        )
    assert before == {p: p.read_bytes() for p in (root / "build").rglob("*") if p.is_file()}


def test_received_utterances_reuse_and_pending_child_refuses(retained_group_record, monkeypatch):
    root, record, plans, settings = retained_group_record
    monkeypatch.setattr(repository, "ROOT", root)
    children = record["utterance_groups"]["records"]
    assert narration_thought_groups.validate_group_inputs(record, root=root) == {
        record["path"],
        *(child["path"] for child in children),
        *(child["receipt"] for child in children),
        *(child["path"].removesuffix(".wav") + ".request.json" for child in children),
    }
    audio, chunks, grouped = narration_group_generation.generate_native_groups(
        SimpleNamespace(sample_rate=RATE),
        plans,
        root / record["path"],
        {"parent_fingerprint": record["fingerprint"], **settings},
    )
    assert grouped == {
        "policy": "Source-exact native complete thoughts; preserve all tails; quiet minimum 0.30s",
        "records": children,
        "joins": record["utterance_groups"]["joins"],
        "listening_accepted": False,
    }
    assert chunks == 2
    assert np.array_equal(
        audio, np.concatenate([np.full(48000, 1000), np.zeros(7200), np.full(48000, 2000)])
    )
    request = (root / children[1]["path"]).with_suffix(".request.json")
    request.write_text(json.dumps({"state": "started", "fingerprint": children[1]["fingerprint"]}))
    with pytest.raises(RuntimeError, match="Unresolved native utterance"):
        narration_group_generation.generate_native_groups(
            SimpleNamespace(sample_rate=RATE),
            plans,
            root / record["path"],
            {"parent_fingerprint": record["fingerprint"], **settings},
        )


def test_grouped_recovery_preflights_every_child_before_effect(retained_group_record, monkeypatch):
    root, record, plans, settings = retained_group_record
    monkeypatch.setattr(repository, "ROOT", root)
    first, second = record["utterance_groups"]["records"]
    first_path = root / first["path"]
    for path in (
        first_path,
        first_path.with_suffix(".json"),
        first_path.with_suffix(".request.json"),
    ):
        path.unlink()
    second_request = (root / second["path"]).with_suffix(".request.json")
    second_request.write_text(
        json.dumps({"state": "started", "fingerprint": second["fingerprint"]})
    )
    before = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
    model = SimpleNamespace(
        sample_rate=RATE,
        generate=lambda **_: pytest.fail("No model call before complete preflight"),
    )
    with pytest.raises(RuntimeError, match="Unresolved native utterance"):
        narration_group_generation.generate_native_groups(
            model,
            plans,
            root / record["path"],
            {"parent_fingerprint": record["fingerprint"], **settings},
        )
    assert {path: path.read_bytes() for path in root.rglob("*") if path.is_file()} == before


def test_new_thoughts_join_with_only_the_quiet_they_lack(retained_group_record, monkeypatch):
    root, _, plans, settings = retained_group_record
    monkeypatch.setattr(repository, "ROOT", root)
    voiced = np.full(36000, 0.1, dtype=np.float32)
    takes = {
        "First thought.": np.concatenate([voiced, np.zeros(2400, dtype=np.float32)]),
        " Second thought.": np.concatenate([np.zeros(1200, dtype=np.float32), voiced]),
    }
    calls, seeds = [], []

    class Model:
        sample_rate = RATE

        def generate(self, **request):
            calls.append(request)
            yield SimpleNamespace(audio=takes[request["text"]])

    monkeypatch.setattr(narration_group_generation.mx.random, "seed", seeds.append)
    path = root / "build/fresh/26-000000000000.wav"
    retaken = [plans[0], {**plans[1], "seed": 7}]
    audio, chunks, grouped = narration_group_generation.generate_native_groups(
        Model(), retaken, path, {"parent_fingerprint": "f" * 64, **settings}
    )
    assert [call["text"] for call in calls] == ["First thought.", " Second thought."]
    assert all(call["ref_audio"] == str(root / "reference.wav") for call in calls)
    assert all(call["ref_text"] == "Reference." for call in calls)
    assert seeds == [1, 7]
    assert grouped["joins"] == [
        {
            "after_group": 1,
            "source_sample": 38400,
            "native_quiet_frames": 3600,
            "added_quiet_frames": 3600,
            "removed_samples": 0,
            "listening_accepted": False,
        }
    ]
    first, second = grouped["records"]
    assert (first["start_sample"], second["start_sample"]) == (0, 42000)
    assert (first["seed"], second["seed"]) == (1, 7)
    assert chunks == 2
    assert len(audio) == 42000 + 37200
    assert not np.any(audio[38400:42000])
    for child in grouped["records"]:
        receipt = root / child["receipt"]
        assert repository.read(receipt) == {
            key: value
            for key, value in child.items()
            if key not in ("receipt", "receipt_sha256", "start_sample")
        }
        assert repository.read(receipt.with_suffix("").with_suffix(".request.json")) == {
            "state": "received",
            "fingerprint": child["fingerprint"],
        }


def dying_float(seconds: float) -> np.ndarray:
    """A float voice that holds and then dies away over its last 0.3 s."""
    n, tail = round(seconds * RATE), round(0.3 * RATE)
    envelope = np.concatenate([np.ones(n - tail), np.exp(-np.arange(tail) / (0.03 * RATE))])
    return (np.sin(2 * np.pi * 180 * np.arange(n) / RATE) * 0.3 * envelope).astype(np.float32)


def run_on_take(retained_group_record, monkeypatch, cut: int):
    """Narrate the fixture's thoughts with a run-on on the second, cut at the given sample."""
    root, _, plans, settings = retained_group_record
    monkeypatch.setattr(repository, "ROOT", root)
    following = np.full(19200, 0.1, dtype=np.float32)
    takes = {
        "First thought.": np.full(36000, 0.1, dtype=np.float32),
        " Second thought. Next words.": np.concatenate(
            [dying_float(1.0), np.zeros(2400, dtype=np.float32), following]
        ),
    }
    calls = []

    class Model:
        sample_rate = RATE

        def generate(self, **request):
            calls.append(request["text"])
            yield SimpleNamespace(audio=takes[request["text"]])

    monkeypatch.setattr(narration_group_generation.mx.random, "seed", lambda _: None)
    run_on = {"spoken_text": " Next words.", "cut_sample": cut}
    retaken = [plans[0], {**plans[1], "seed": 7, "run_on": run_on}]
    path = root / "build/fresh/26-000000000000.wav"
    result = narration_group_generation.generate_native_groups(
        Model(), retaken, path, {"parent_fingerprint": "f" * 64, **settings}
    )
    return result, calls, run_on


def test_a_run_on_thought_is_narrated_into_what_follows_and_kept_up_to_its_cut(
    retained_group_record, monkeypatch
):
    (audio, _, grouped), calls, run_on = run_on_take(retained_group_record, monkeypatch, 25200)
    assert calls == ["First thought.", " Second thought. Next words."]
    second = grouped["records"][1]
    assert (second["frames"], second["native_frames"], second["run_on"]) == (25200, 45600, run_on)
    assert len(audio) == second["start_sample"] + 25200


def test_a_run_on_cut_inside_the_voice_records_nothing(retained_group_record, monkeypatch):
    with pytest.raises(RuntimeError, match="run-on take does not end naturally"):
        run_on_take(retained_group_record, monkeypatch, 12000)
    root = retained_group_record[0]
    assert not list((root / "build/fresh").rglob("02-*.wav"))
