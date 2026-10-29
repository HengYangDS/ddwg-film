"""A narration receipt's records, still bound to their recordings, texts and language."""

import hashlib

import pytest

import ddwg_film.narration.receipts as narration_receipts
import ddwg_film.repository as repository


@pytest.fixture
def receipt(tmp_path, monkeypatch) -> dict:
    monkeypatch.setattr(repository, "ROOT", tmp_path)
    (tmp_path / "recordings").mkdir()
    (tmp_path / "recordings/01.wav").write_bytes(b"pcm")
    record = {
        "id": "01",
        "path": "recordings/01.wav",
        "text": "数据的用途。",
        "text_sha256": hashlib.sha256("数据的用途。".encode()).hexdigest(),
        "language": "Chinese",
        "wav_sha256": hashlib.sha256(b"pcm").hexdigest(),
    }
    value = {"records": [record]}
    repository.write("receipt.json", value)
    return value


def test_bound_records_are_the_receipt_records(receipt):
    assert narration_receipts.bound_records("receipt.json", "Chinese") == receipt["records"]


def test_a_record_without_a_language_takes_the_requested_one(receipt):
    receipt["records"][0].pop("language")
    repository.write("receipt.json", receipt)
    assert narration_receipts.bound_records("receipt.json", "English") == receipt["records"]


@pytest.mark.parametrize(
    ("tamper", "language", "message"),
    [
        (
            lambda root, _: (root / "recordings/01.wav").write_bytes(b"changed"),
            "Chinese",
            "01: the recording differs from its receipt",
        ),
        (
            lambda _, record: record.update(text="数据的来源。"),
            "Chinese",
            "Recording text binding differs",
        ),
        (lambda _root, _record: None, "English", "01: the recording language differs"),
    ],
    ids=["recording", "text", "language"],
)
def test_a_record_that_differs_from_its_recording_is_refused(
    tmp_path, receipt, tamper, language, message
):
    tamper(tmp_path, receipt["records"][0])
    repository.write("receipt.json", receipt)
    with pytest.raises(ValueError, match=message):
        narration_receipts.bound_records("receipt.json", language)
