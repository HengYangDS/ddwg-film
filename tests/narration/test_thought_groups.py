"""Retained native narration groups: their partition, requests, PCM, joins and dependencies."""

import hashlib
import wave

import numpy as np
import pytest

import ddwg_film.narration.thought_groups as narration_thought_groups

RATE = 24000


def parent_pcm(root, record) -> np.ndarray:
    with wave.open(str(root / record["path"])) as audio:
        return np.frombuffer(audio.readframes(audio.getnframes()), dtype="<i2")


def rewrite_parent(root, record, pcm, *, rate=RATE, channels=1) -> None:
    """Replace the parent recording and rebind its hash, so only the tampered fact differs."""
    path = root / record["path"]
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(channels)
        audio.setsampwidth(2)
        audio.setframerate(rate)
        audio.writeframes(np.asarray(pcm, dtype="<i2").tobytes())
    record["wav_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()


def first_join(_root, record) -> dict:
    return record["utterance_groups"]["joins"][0]


def set_join(field, value):
    return lambda root, record: first_join(root, record).update({field: value})


def voice_in_added_quiet(root, record) -> None:
    pcm = parent_pcm(root, record).copy()
    pcm[48000 + 100] = 500
    rewrite_parent(root, record, pcm)


def longer_parent(root, record) -> None:
    rewrite_parent(root, record, np.concatenate([parent_pcm(root, record), np.zeros(10, "<i2")]))


def stereo_parent(root, record) -> None:
    rewrite_parent(root, record, np.repeat(parent_pcm(root, record), 2), channels=2)


def changed_parent_bytes(root, record) -> None:
    retained = record["wav_sha256"]
    pcm = parent_pcm(root, record).copy()
    pcm[0] += 1
    rewrite_parent(root, record, pcm)
    record["wav_sha256"] = retained


def faster_parent(root, record) -> None:
    rewrite_parent(root, record, parent_pcm(root, record), rate=2 * RATE)
    record["sample_rate"] = 2 * RATE


def child(index, field, value):
    def tamper(_root, record):
        record["utterance_groups"]["records"][index][field] = value

    return tamper


def field(name, value):
    return lambda _root, record: record.update({name: value})


@pytest.mark.parametrize(
    ("tamper", "message"),
    [
        (field("text", "Changed. Second thought."), "Retained utterance text differs"),
        (field("spoken_text", "Changed."), "Retained utterance text differs"),
        (field("sample_rate", "24000"), "Retained parent PCM metadata differs"),
        (field("seed", "1"), "Retained utterance settings differ"),
        (field("temperature", float("nan")), "Retained utterance settings differ"),
        (child(0, "max_tokens", 0), "Retained utterance settings differ"),
        (child(0, "reference_text", 5), "Retained utterance reference text differs"),
        (child(0, "reference_text", "Other."), "Retained utterance reference text differs"),
        (field("temperature", 0.5), "Retained utterance parent fingerprint differs"),
        (stereo_parent, "Retained parent PCM metadata differs"),
        (changed_parent_bytes, "Retained parent waveform changed"),
        (lambda _root, record: record["utterance_groups"].update(joins=[]), "joins differ"),
        (child(0, "receipt", "../receipt.json"), "Retained utterance path differs"),
        (child(0, "receipt_sha256", "0" * 64), "Retained utterance input changed"),
        (child(0, "frames", 47999), "Retained utterance receipt differs"),
        (faster_parent, "Retained utterance sample rate differs"),
        (child(1, "start_sample", 55201), "Retained utterance PCM differs from parent"),
        (set_join("after_group", 2), "Retained utterance join differs"),
        (set_join("source_sample", 48001), "Retained utterance join differs"),
        (set_join("removed_samples", 1), "Retained utterance join differs"),
        (set_join("native_quiet_frames", 0.0), "Retained utterance join differs"),
        (set_join("added_quiet_frames", 7199), "Retained utterance join differs"),
        (voice_in_added_quiet, "Retained utterance join differs"),
        (set_join("native_quiet_frames", 10), "Retained utterance quiet accounting differs"),
        (longer_parent, "Retained utterance parent extent differs"),
    ],
)
def test_a_tampered_record_is_refused_with_its_difference(retained_group_record, tamper, message):
    root, record, _, _ = retained_group_record
    tamper(root, record)
    with pytest.raises(RuntimeError, match=message):
        narration_thought_groups.validate_group_inputs(record, root=root)


def test_a_retained_record_depends_on_every_recording_receipt_and_request(retained_group_record):
    root, record, _, _ = retained_group_record
    children = record["utterance_groups"]["records"]
    requests = [child["path"].removesuffix(".wav") + ".request.json" for child in children]
    assert narration_thought_groups.validate_group_inputs(record, root=root) == {
        record["path"],
        *(child["path"] for child in children),
        *(child["receipt"] for child in children),
        *requests,
    }


def test_a_record_without_thought_groups_has_no_dependencies(retained_group_record):
    root, record, _, _ = retained_group_record
    record.pop("utterance_groups")
    assert narration_thought_groups.validate_group_inputs(record, root=root) == set()


@pytest.mark.parametrize("children", [None, [], [{}]])
def test_grouped_records_require_complete_children(retained_group_record, children):
    root, record, _, _ = retained_group_record
    record["utterance_groups"]["records"] = children
    with pytest.raises(RuntimeError, match="Retained utterance records differ"):
        narration_thought_groups.validate_group_inputs(record, root=root)


def test_grouped_record_requires_current_authored_partition(retained_group_record):
    root, record, plans, _ = retained_group_record
    section = {
        "text": record["text"],
        "spoken_text": record["spoken_text"],
        "utterance_groups": [plan["text"] for plan in plans],
    }
    narration_thought_groups.validate_group_inputs(record, root=root, section=section)
    for groups in (None, [], [record["text"]]):
        with pytest.raises(RuntimeError, match="Retained utterance source groups differ"):
            narration_thought_groups.validate_group_inputs(
                record, root=root, section={**section, "utterance_groups": groups}
            )
    with pytest.raises(RuntimeError, match="Retained utterance source groups differ"):
        narration_thought_groups.validate_group_inputs(
            record, root=root, section={"text": record["text"]}
        )


def test_a_run_on_thought_validates_with_the_run_on_its_request_names(run_on_record):
    root, record, plans, _ = run_on_record()
    assert narration_thought_groups.recorded_plan(record) == plans
    narration_thought_groups.validate_group_inputs(record, root=root)


def test_a_run_on_thought_whose_run_on_changed_is_refused(run_on_record):
    root, record, _, _ = run_on_record()
    record["utterance_groups"]["records"][1]["run_on"]["cut_sample"] = 47000
    with pytest.raises(RuntimeError, match="Retained utterance"):
        narration_thought_groups.validate_group_inputs(record, root=root)


def test_a_retained_run_on_take_that_is_cut_while_voiced_is_refused(run_on_record):
    root, record, _, _ = run_on_record(natural=False)
    with pytest.raises(RuntimeError, match="run-on take does not end naturally"):
        narration_thought_groups.validate_group_inputs(record, root=root)
