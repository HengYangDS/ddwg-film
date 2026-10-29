"""Caption refresh keeps the assembled waveform and rebinds the cues to the current script."""

import hashlib
import json

import pytest

import filmkit.captions.refresh as captions_refresh
import filmkit.production as production
import filmkit.repository as repository

TEXT = "甲乙。丙丁。"
WORDS = (("甲", 2.0, 2.4), ("乙", 2.4, 2.8), ("丙", 3.4, 3.8), ("丁", 3.8, 4.2))


def sha256(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False))


@pytest.fixture
def edition(tmp_path, monkeypatch):
    """Stage an assembled edition: script, cast, timeline, waveform, receipt and selection."""
    release = repository.read(production.Edition("zh").script)["release"]
    monkeypatch.setattr(repository, "ROOT", tmp_path)
    edition = production.Edition("zh")
    segment = {
        "id": "01",
        "chapter": "a",
        "chapter_title": "A",
        "title": "Scene 01",
        "utterance_groups": ["甲乙。", "丙丁。"],
        "text": TEXT,
        "spoken_text": TEXT,
    }
    script = {
        "title": "DDWG",
        "caption_timing": {"tail_seconds": 0.25, "short_cue_lead_seconds": 0.1},
        "release": release,
        "segments": [segment],
    }
    write_json(tmp_path / edition.script, script)
    write_json(tmp_path / edition.cast, {"narration_language": "Chinese"})
    timed = {
        **segment,
        "start": 0.0,
        "voice_start": 2.0,
        "voice_end": 4.3,
        "gap_before": 2.0,
        "gap_kind": "opening",
        "words": [{"text": word, "start": start, "end": end} for word, start, end in WORDS],
        "end": 6.0,
    }
    timeline = {**script, "segments": [timed], "timing_state": "Assembled", "captions": []}
    write_json(edition.timeline, timeline)
    edition.soundtrack.write_bytes(b"RIFF narration")
    write_json(
        edition.audio_assembly,
        {
            "script_sha256": sha256(tmp_path / edition.script),
            "soundtrack_sha256": sha256(edition.soundtrack),
            "caption_count": 0,
            "alignment_limits": "Model-aligned words",
            "caption_timing": "Timed",
        },
    )
    write_json(
        edition.narration_selected,
        {
            "records": [{"id": "01", "text": TEXT}],
            "script_sha256": "0" * 64,
            "cast_sha256": sha256(tmp_path / edition.cast),
        },
    )
    return edition


def read(path) -> dict:
    return json.loads(path.read_text())


def revise_script(edition, change) -> None:
    path = repository.ROOT / edition.script
    script = read(path)
    change(script)
    write_json(path, script)


def test_a_current_edition_refreshes_its_cues_and_its_selection_binding(edition, capsys):
    captions_refresh.refresh_captions(edition)
    timeline, receipt = read(edition.timeline), read(edition.audio_assembly)
    assert [cue["text"] for cue in timeline["captions"]] == ["甲乙。", "丙丁。"]
    assert timeline["captions"][0]["start"] == 2.0
    assert receipt["caption_count"] == 2
    assert list(receipt)[-3:] == ["caption_count", "alignment_limits", "caption_timing"]
    assert receipt["caption_timing"].startswith("Nonoverlapping exact word-bound semantic cues")
    script_sha256 = sha256(repository.ROOT / edition.script)
    assert read(edition.narration_selected)["script_sha256"] == script_sha256
    assert (edition.artifacts / "ddwg-zh.srt").read_text().startswith("1\n00:00:02,000 --> ")
    assert json.loads(capsys.readouterr().out)["caption_count"] == 2


def test_a_presentation_revision_records_what_it_replaces(edition):
    before = {
        "script": sha256(repository.ROOT / edition.script),
        "timeline": sha256(edition.timeline),
        "receipt": sha256(edition.audio_assembly),
    }
    phrases = ["甲乙。", "丙丁。"]
    revise_script(edition, lambda script: script["segments"][0].update(caption_phrases=phrases))
    captions_refresh.refresh_captions(edition)
    receipt, timeline = read(edition.audio_assembly), read(edition.timeline)
    script_sha256 = sha256(repository.ROOT / edition.script)
    assert receipt["script_sha256"] == script_sha256
    assert receipt["caption_revision"] == {
        "previous_script_sha256": before["script"],
        "previous_timeline_sha256": before["timeline"],
        "previous_audio_assembly_sha256": before["receipt"],
        "script_sha256": script_sha256,
        "soundtrack_sha256": sha256(edition.soundtrack),
        "scope": (
            "Only authored visual and caption presentation changed; "
            "source copy, words and PCM preserved"
        ),
    }
    assert timeline["segments"][0]["caption_phrases"] == phrases
    assert list(receipt)[-1] == "caption_revision"


def test_a_presentation_revision_requires_the_assembled_waveform(edition):
    revise_script(edition, lambda script: script["segments"][0].update(visual_events=[]))
    edition.soundtrack.write_bytes(b"RIFF another narration")
    with pytest.raises(ValueError, match="requires the exact assembled waveform"):
        captions_refresh.refresh_captions(edition)


def test_a_copy_change_needs_a_new_assembly(edition):
    revise_script(
        edition,
        lambda script: script["segments"][0].update(
            text="甲己。丙丁。", spoken_text="甲己。丙丁。", utterance_groups=["甲己。", "丙丁。"]
        ),
    )
    with pytest.raises(ValueError, match="requires the exact current script and waveform"):
        captions_refresh.refresh_captions(edition)


def test_a_refresh_refuses_a_selection_of_other_copy(edition):
    selected = read(edition.narration_selected)
    selected["records"][0]["text"] = "甲。"
    write_json(edition.narration_selected, selected)
    with pytest.raises(ValueError, match="Selected narration differs"):
        captions_refresh.refresh_captions(edition)
