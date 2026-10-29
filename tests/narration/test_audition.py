"""Auditioning alternative takes of chosen thoughts and binding the selected seeds."""

import dataclasses
import hashlib
import json
import wave
from types import SimpleNamespace

import numpy as np
import pytest

import ddwg_film.narration.audition as narration_audition
import ddwg_film.narration.group_generation as narration_group_generation
import ddwg_film.repository as repository
from ddwg_film.production import Edition


def sha256(data: bytes | str) -> str:
    return hashlib.sha256(data.encode() if isinstance(data, str) else data).hexdigest()


def take(
    seed,
    *,
    natural=True,
    heard=True,
    differing=0,
    end_ratio=0.1,
    seconds=3.0,
    quiet=True,
    stops=(),
):
    return {
        "seed": seed,
        "natural": natural,
        "phrase_stops": None if stops is None else list(stops),
        "required_heard": heard,
        "differing_units": differing,
        "end_ratio": end_ratio,
        "seconds": seconds,
        "opens_quiet": quiet,
    }


def test_propose_ranks_only_qualified_takes():
    takes = [
        take(1, natural=False),
        take(2, differing=1),
        take(3, end_ratio=0.05),
        take(4, end_ratio=0.08, seconds=3.4),
        take(5, heard=False, seconds=4.0),
        take(6, end_ratio=0.09, seconds=2.8),
        take(7, natural=False, seconds=2.0),
    ]
    assert narration_audition.propose(takes) == 3
    assert narration_audition.propose(takes, "slower") == 4
    assert narration_audition.propose(takes, "brisker") == 6
    assert narration_audition.propose(takes[:1] + takes[4:5]) is None


def test_propose_refuses_a_take_with_a_phrase_cut_inside_its_thought():
    # A take whose phrase ends could not be aligned is not known to end them naturally.
    stopped = {"end_sample": 24000, "final_fall_ms": 4.0}
    takes = [take(1, end_ratio=0.05, stops=[stopped]), take(2, end_ratio=0.06, stops=None)]
    assert narration_audition.propose(takes) is None
    assert narration_audition.propose([*takes, take(3, end_ratio=0.08)]) == 3


def test_propose_requires_a_recording_opening_thought_to_begin_in_quiet():
    takes = [take(1, end_ratio=0.05, quiet=False), take(2, end_ratio=0.08)]
    assert narration_audition.propose(takes) == 1
    assert narration_audition.propose(takes, opens_recording=True) == 2
    assert narration_audition.propose(takes[:1], opens_recording=True) is None


THOUGHTS = ["按及时性的标准，这次交付不合格。", "把调度窗口提前，是有权的人做的决定。"]


def proposal(segment: str, index: int, text: str, seed: int | None) -> dict:
    return {
        "segment": segment,
        "index": index,
        "text": text,
        "required": "有权的人",
        "current_seed": 4683,
        "takes": [],
        "proposed_seed": seed,
    }


@pytest.fixture
def cast(write_edition):
    return write_edition("zh", {"06": THOUGHTS}, {})["cast"]


def test_apply_binds_current_thoughts_and_skips_rows_without_a_proposal(tmp_path, cast, capsys):
    rows = [proposal("06", 2, THOUGHTS[1], 99711), proposal("06", 1, THOUGHTS[0], None)]
    repository.write(tmp_path / "proposals.json", rows)
    narration_audition.main(["apply", "--language", "zh", "--proposals", "proposals.json"])
    assert json.loads(capsys.readouterr().out) == {
        "language": "zh",
        "applied": ["06.2=99711"],
        "skipped": ["06.1"],
        "dry_run": False,
    }
    assert repository.read(cast)["retakes"] == {
        "06": {"groups": {"2": {"seed": 99711, "text_sha256": sha256(THOUGHTS[1])}}}
    }


@pytest.mark.parametrize(
    "row",
    [
        proposal("06", 2, "把调度窗口提前，是负责人的决定。", 99711),
        proposal("06", 3, THOUGHTS[1], 99711),
        proposal("07", 1, THOUGHTS[0], 99711),
    ],
)
def test_apply_refuses_a_thought_whose_text_changed(tmp_path, cast, row):
    repository.write(tmp_path / "proposals.json", [proposal("06", 1, THOUGHTS[0], 7), row])
    before = cast.read_bytes()
    with pytest.raises(ValueError, match="not the current thought"):
        narration_audition.main(["apply", "--language", "zh", "--proposals", "proposals.json"])
    assert cast.read_bytes() == before


def test_apply_dry_run_leaves_the_cast_unchanged(tmp_path, cast, capsys):
    repository.write(tmp_path / "proposals.json", [proposal("06", 2, THOUGHTS[1], 99711)])
    before = cast.read_bytes()
    narration_audition.main(
        ["apply", "--language", "zh", "--proposals", "proposals.json", "--dry-run"]
    )
    report = json.loads(capsys.readouterr().out)
    assert report["applied"] == ["06.2=99711"]
    assert report["dry_run"] is True
    assert cast.read_bytes() == before


@pytest.fixture
def auditioned(retained_group_record, monkeypatch):
    """An English edition whose declared receipt holds one grouped, bound recording."""
    root, record, plans, settings = retained_group_record
    monkeypatch.setattr(repository, "ROOT", root)
    record = {**record, "text_sha256": sha256(record["text"])}
    edition = Edition("en")
    section = {
        "id": "26",
        "text": record["text"],
        "spoken_text": record["spoken_text"],
        "utterance_groups": [plan["text"] for plan in plans],
    }
    repository.write(edition.script, {"segments": [section]})
    cast = {
        "reference_audio": settings["reference_audio"],
        "reference_sha256": settings["reference_sha256"],
        "reference_text": settings["reference_text"],
        "narration_language": "English",
        "performance_recording": {"receipt": "build/receipt.json"},
    }
    repository.write(edition.cast, cast)
    repository.write("build/receipt.json", {"records": [record]})
    repository.write("targets.json", {"26.2": "second thought"})

    def unloaded():
        pytest.fail("A refused audition loads no model")

    monkeypatch.setattr(narration_group_generation, "load_voice_model", unloaded)
    monkeypatch.setattr(narration_audition, "load_asr", unloaded)
    monkeypatch.setattr(narration_audition, "load_aligner", unloaded)
    return {"root": root, "record": record, "cast": cast}


def other_narrator(cast: dict) -> None:
    """Point the cast at another narrator's reference recording."""
    (repository.ROOT / "other.wav").write_bytes(b"another narrator")
    cast.update(reference_audio="other.wav", reference_sha256=sha256(b"another narrator"))


def rewrite(path, change) -> None:
    value = repository.read(path)
    change(value)
    repository.write(path, value)


@pytest.mark.parametrize(
    ("tamper", "error", "message"),
    [
        (
            lambda: rewrite(
                Edition("en").script,
                lambda script: script["segments"][0].update(
                    utterance_groups=["First thought.", " A new second thought."]
                ),
            ),
            ValueError,
            "26.2: the receipt does not hold the current thought",
        ),
        (lambda: repository.write("targets.json", {"26.3": "third"}), ValueError, "Every target"),
        (
            lambda: rewrite(
                "build/receipt.json",
                lambda receipt: receipt["records"][0]["utterance_groups"]["records"][1].update(
                    receipt_sha256="0" * 64
                ),
            ),
            RuntimeError,
            "Retained utterance input changed",
        ),
        (
            lambda: rewrite(Edition("en").cast, other_narrator),
            ValueError,
            "26: the recording's narrator reference differs from the cast",
        ),
        (
            lambda: (
                repository.ROOT / repository.read("build/receipt.json")["records"][0]["path"]
            ).write_bytes(b"changed"),
            ValueError,
            "26: the recording differs from its receipt",
        ),
    ],
    ids=[
        "stale-thought",
        "unknown-target",
        "tampered-thought",
        "other-reference",
        "changed-recording",
    ],
)
def test_audition_refuses_before_loading_any_model(auditioned, tamper, error, message):
    tamper()
    with pytest.raises(error, match=message):
        narration_audition.audition("en", "targets.json", "build/receipt.json")
    assert not (auditioned["root"] / narration_audition.AUDITIONS).exists()


def test_audition_preserves_existing_proposals(auditioned):
    repository.write(auditioned["root"] / narration_audition.AUDITIONS / "en/audition.json", [])
    with pytest.raises(FileExistsError, match="Preserve the existing proposals"):
        narration_audition.audition("en", "targets.json")


def test_audition_records_each_take_with_its_waveform_hash(auditioned, monkeypatch, capsys):
    calls, seeds, heard = [], [], []

    class Voice:
        sample_rate = 24000

        def generate(self, **request):
            calls.append(request)
            yield SimpleNamespace(audio=np.full(30000, 0.2, dtype=np.float32))

    class Recognizer:
        def generate(self, path, *, language):
            heard.append((path, language))
            return SimpleNamespace(text=" Second thought.")

    class Aligner:
        def generate(self, _path, *, text, language):
            assert (text, language) == (" Second thought.", "English")
            words = [Aligned("Second", 0.1, 0.5), Aligned("thought", 0.5, 1.0)]
            return SimpleNamespace(items=words)

    identity = {"repo": "aligner", "revision": "r", "weights_sha256": "0" * 64}
    monkeypatch.setattr(narration_group_generation, "load_voice_model", Voice)
    monkeypatch.setattr(narration_group_generation.mx.random, "seed", seeds.append)
    monkeypatch.setattr(narration_audition, "load_asr", Recognizer)
    monkeypatch.setattr(
        narration_audition, "load_aligner", lambda: {"identity": identity, "model": Aligner()}
    )
    narration_audition.audition("en", "targets.json", takes=2, first=11)
    seed = auditioned["record"]["seed"]
    assert seeds == [seed + 11 * 7919, seed + 12 * 7919]
    assert [call["text"] for call in calls] == [" Second thought."] * 2
    folder = auditioned["root"] / narration_audition.AUDITIONS / "en"
    (row,) = json.loads((folder / "audition.json").read_text())
    assert [take["seed"] for take in row["takes"]] == seeds
    assert heard == [(str(auditioned["root"] / take["path"]), "English") for take in row["takes"]]
    for take_row in row["takes"]:
        recording = auditioned["root"] / take_row["path"]
        assert take_row["wav_sha256"] == sha256(recording.read_bytes())
        assert (take_row["required_heard"], take_row["differing_units"]) == (True, 0)
        assert take_row["natural"] is False
        # The thought holds no phrase end before its own.
        assert take_row["phrase_stops"] == []
    assert row["proposed_seed"] is None
    assert json.loads(capsys.readouterr().out.splitlines()[-1])["proposed"] == {"26.2": None}


@dataclasses.dataclass
class Aligned:
    """One aligned item, as the forced aligner returns it."""

    text: str
    start_time: float
    end_time: float


def dying(seconds: float, rate: int = 24000) -> np.ndarray:
    """A float voice that holds and then dies away over its last 0.3 s."""
    n, tail = round(seconds * rate), round(0.3 * rate)
    envelope = np.concatenate([np.ones(n - tail), np.exp(-np.arange(tail) / (0.03 * rate))])
    return (np.sin(2 * np.pi * 180 * np.arange(n) / rate) * 0.3 * envelope).astype(np.float32)


def test_a_run_on_target_is_read_on_into_the_next_thought_and_cut_before_it(
    auditioned, monkeypatch
):
    repository.write("targets.json", {"26.1": {"required": "first thought", "run_on": True}})
    quiet = np.zeros(2400, dtype=np.float32)
    whole = np.concatenate([quiet, dying(1.0), quiet, np.full(19200, 0.1, dtype=np.float32)])
    texts, aligned = [], []

    class Voice:
        sample_rate = 24000

        def generate(self, **request):
            texts.append(request["text"])
            yield SimpleNamespace(audio=whole)

    class Recognizer:
        def generate(self, *_, **__):
            return SimpleNamespace(text="First thought.")

    class Aligner:
        def generate(self, _path, *, text, language):
            aligned.append((text, language))
            words = [
                ("First", 0.1, 0.5),
                ("thought", 0.5, 1.0),
                ("Second", 1.2, 1.6),
                ("thought", 1.6, 1.9),
            ]
            # The cut take holds only its own thought.
            words = words if "Second" in text else words[:2]
            return SimpleNamespace(items=[Aligned(word, start, end) for word, start, end in words])

    identity = {"repo": "aligner", "revision": "r", "weights_sha256": "0" * 64}
    monkeypatch.setattr(narration_group_generation, "load_voice_model", Voice)
    monkeypatch.setattr(narration_group_generation.mx.random, "seed", lambda _: None)
    monkeypatch.setattr(narration_audition, "load_asr", Recognizer)
    monkeypatch.setattr(
        narration_audition, "load_aligner", lambda: {"identity": identity, "model": Aligner()}
    )
    narration_audition.audition("en", "targets.json", takes=1, first=11)
    assert texts == ["First thought. Second thought."]
    # The whole take locates the cut; the cut take is aligned again for its phrase ends.
    assert aligned == [
        ("First thought. Second thought.", "English"),
        ("First thought.", "English"),
    ]
    folder = auditioned["root"] / narration_audition.AUDITIONS / "en"
    (row,) = json.loads((folder / "audition.json").read_text())
    (taken,) = row["takes"]
    # Three quiet frames of 10 ms after the thought's aligned end at 1.0 s end the cut.
    cut = {"spoken_text": " Second thought.", "cut_sample": 24000 + 720}
    assert (row["run_on"], row["aligner"], taken["run_on"]) == (" Second thought.", identity, cut)
    assert taken["natural"] is True
    assert row["proposed_run_on"] == cut
    with wave.open(str(auditioned["root"] / taken["path"])) as source:
        assert source.getnframes() == cut["cut_sample"]
    assert (auditioned["root"] / taken["run_on_take"]["path"]).exists()
