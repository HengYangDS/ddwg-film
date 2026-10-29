"""Selecting the narration recordings and binding their narrator, alignment and script."""

import copy
import hashlib
import json

import pytest

import ddwg_film.narration.selection as narration_selection
import ddwg_film.repository as repository
from ddwg_film.production import Edition


def sha256(data: bytes | str) -> str:
    return hashlib.sha256(data.encode() if isinstance(data, str) else data).hexdigest()


@pytest.fixture
def edition(retained_group_record, monkeypatch):
    """An English edition whose script, cast, receipt and alignment bind one grouped record."""
    root, record, plans, settings = retained_group_record
    monkeypatch.setattr(repository, "ROOT", root)
    record = {**record, "text_sha256": sha256(record["text"])}
    section = {
        "id": record["id"],
        "text": record["text"],
        "spoken_text": record["spoken_text"],
        "language": "English",
        "utterance_groups": [plan["text"] for plan in plans],
    }
    repository.write(
        "content/voice-performance.json",
        {"pronunciation": {"languages": {"English": {"normalization": []}}}},
    )
    script = {
        "language": "English",
        "pronunciation_contract": "content/voice-performance.json",
        "segments": [section],
    }
    cast = {
        "reference_audio": settings["reference_audio"],
        "reference_sha256": settings["reference_sha256"],
        "reference_text": settings["reference_text"],
        "reference_text_sha256": sha256(settings["reference_text"]),
        "narration_language": "English",
        "reference_language": "English",
        "performance_recording": {
            "receipt": "build/receipt.json",
            "alignment": "build/alignment.json",
        },
    }
    alignment = {
        "records": [
            {
                "id": record["id"],
                "items": [],
                "wav_sha256": record["wav_sha256"],
                "text_sha256": record["text_sha256"],
            }
        ]
    }
    values = {"script": script, "cast": cast, "receipt": {"records": [record]}}
    values["alignment"] = alignment
    write_edition(values)
    return values


def write_edition(values: dict) -> None:
    edition = Edition("en")
    repository.write(edition.script, values["script"])
    repository.write(edition.cast, values["cast"])
    repository.write("build/receipt.json", values["receipt"])
    repository.write("build/alignment.json", values["alignment"])


def test_selection_binds_each_current_recording_and_its_alignment(edition, capsys):
    narration_selection.select(Edition("en"))
    selected = repository.read(Edition("en").narration_selected)
    assert selected == {
        "records": edition["receipt"]["records"],
        "script_sha256": repository.sha(Edition("en").script),
        "cast_sha256": repository.sha(Edition("en").cast),
        "selection": "Current paragraph text; original generation retained",
        "listening_acceptance": "Separate review required",
    }
    assert repository.read(Edition("en").alignment_selected) == edition["alignment"]
    assert json.loads(capsys.readouterr().out) == {"selected": 1, "seconds": 4.3}


def receipt_record(values: dict) -> dict:
    return values["receipt"]["records"][0]


@pytest.mark.parametrize(
    ("tamper", "error", "message"),
    [
        (
            lambda values: values["cast"].pop("performance_recording"),
            ValueError,
            "A current declared performance recording is required",
        ),
        (
            lambda values: receipt_record(values).update(text="Changed."),
            ValueError,
            "Recording text differs: 26",
        ),
        (
            lambda values: receipt_record(values).update(spoken_text="Changed."),
            ValueError,
            "Recording spoken text differs: 26",
        ),
        (
            lambda values: receipt_record(values).update(wav_sha256="0" * 64),
            ValueError,
            "Recording waveform differs: 26",
        ),
        (
            lambda values: receipt_record(values)["utterance_groups"]["records"][0].update(
                receipt_sha256="0" * 64
            ),
            RuntimeError,
            "Retained utterance input changed",
        ),
        (
            lambda values: values["cast"].update(reference_treatment={"pitch_shift": 0}),
            ValueError,
            "26: the recording's narrator reference differs from the cast",
        ),
        (
            lambda values: values["alignment"]["records"][0].update(wav_sha256="0" * 64),
            ValueError,
            "Selected alignment waveform differs: 26",
        ),
    ],
)
def test_selection_refuses_a_recording_that_differs(edition, tamper, error, message):
    tamper(edition)
    write_edition(edition)
    with pytest.raises(error, match=message):
        narration_selection.select(Edition("en"))
    assert not Edition("en").narration_selected.exists()


def test_selection_refuses_a_recording_outside_the_production_root(edition, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside") / "recording.wav"
    outside.write_bytes(b"recording")
    record = receipt_record(edition)
    record.pop("utterance_groups")
    record.update(path=str(outside), wav_sha256=sha256(outside.read_bytes()))
    edition["script"]["segments"][0].pop("utterance_groups")
    edition["alignment"]["records"][0]["wav_sha256"] = record["wav_sha256"]
    write_edition(edition)
    with pytest.raises(ValueError, match="must belong to the production root"):
        narration_selection.select(Edition("en"))


def test_a_voice_record_binds_the_cast_reference(edition):
    record, cast = receipt_record(edition), edition["cast"]
    narration_selection.validate_voice_record(record, cast)
    for field, value in (
        ("reference_audio", "other.wav"),
        ("reference_sha256", "0" * 64),
        ("reference_text_sha256", sha256("Other.")),
        ("reference_treatment", {"pitch_shift": 0}),
    ):
        with pytest.raises(ValueError, match="narrator reference differs from the cast"):
            narration_selection.validate_voice_record({**record, field: value}, cast)


def test_a_voice_record_refuses_a_changed_cast_reference(edition):
    record, cast = receipt_record(edition), copy.deepcopy(edition["cast"])
    narration_selection.validate_voice_record(record, cast)
    reference = repository.ROOT / cast["reference_audio"]
    reference.write_bytes(reference.read_bytes() + b"\0\0")
    with pytest.raises(ValueError, match="differs from the cast's SHA-256"):
        narration_selection.validate_voice_record(record, cast)


RECORD = {"id": "01", "text": "先核验。", "text_sha256": sha256("先核验。"), "wav_sha256": "a" * 64}
ALIGNED = {key: RECORD[key] for key in ("id", "text_sha256", "wav_sha256")}


@pytest.mark.parametrize(
    ("record", "aligned", "message"),
    [
        (RECORD, {**ALIGNED, "id": "02"}, "Selected alignment identity differs: 01"),
        (RECORD, {**ALIGNED, "wav_sha256": "b" * 64}, "Selected alignment waveform differs: 01"),
        (RECORD, {**ALIGNED, "text_sha256": sha256("旧稿")}, "Selected alignment text differs: 01"),
        ({**RECORD, "text": "旧稿"}, ALIGNED, "Selected alignment text differs: 01"),
    ],
)
def test_an_alignment_binds_its_exact_recording_and_text(record, aligned, message):
    narration_selection.validate_aligned_recording(RECORD, ALIGNED)
    with pytest.raises(ValueError, match=message):
        narration_selection.validate_aligned_recording(record, aligned)
