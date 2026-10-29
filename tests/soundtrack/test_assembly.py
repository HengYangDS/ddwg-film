"""Soundtrack assembly checks every selected recording against its script before mixing."""

import hashlib
import json
import wave

import numpy as np
import pytest

import filmkit.production as production
import filmkit.repository as repository
import filmkit.soundtrack.assembly as soundtrack_assembly

REPOSITORY = repository.ROOT
RATE = 48000


@pytest.fixture
def edition(tmp_path, monkeypatch):
    monkeypatch.setattr(repository, "ROOT", tmp_path)
    performance = json.loads((REPOSITORY / "content/film-script.json").read_text())[
        "voice_performance"
    ]

    def stage(script, recording, wav=b"RIFF"):
        (tmp_path / "content").mkdir(exist_ok=True)
        (tmp_path / "content/film-script.json").write_text(json.dumps(script))
        (tmp_path / "take.wav").write_bytes(wav)
        evidence = production.Edition("zh").evidence
        evidence.mkdir(parents=True)
        (evidence / "narration-selected.json").write_text(json.dumps({"records": [recording]}))
        (evidence / "alignment-selected.json").write_text(json.dumps({"records": [{"id": "01"}]}))

    return performance, stage


def test_assembly_refuses_a_script_without_designed_pauses(edition):
    _, stage = edition
    stage({"segments": []}, {"id": "01"})
    with pytest.raises(ValueError, match="Assembly requires native speech with designed pauses"):
        soundtrack_assembly.assemble(production.Edition("zh"))


def test_assembly_refuses_a_recording_whose_text_differs(edition):
    performance, stage = edition
    script = {"voice_performance": performance, "segments": [{"id": "01", "text": "甲。"}]}
    stage(script, {"id": "01", "text": "乙。", "path": "take.wav", "wav_sha256": ""})
    with pytest.raises(ValueError, match="Selected recording text differs: 01"):
        soundtrack_assembly.assemble(production.Edition("zh"))


def test_assembly_refuses_a_recording_whose_waveform_differs(edition):
    performance, stage = edition
    script = {"voice_performance": performance, "segments": [{"id": "01", "text": "甲。"}]}
    stage(script, {"id": "01", "text": "甲。", "path": "take.wav", "wav_sha256": "0" * 64})
    with pytest.raises(ValueError, match="Selected recording waveform differs: 01"):
        soundtrack_assembly.assemble(production.Edition("zh"))


# Two thoughts per recording: 0.4 s of quiet, two words of tone, 0.6 s of quiet at the join,
# two more words and 0.5 s of quiet.
WORDS = (("甲", 0.4, 0.9), ("乙", 0.9, 1.4), ("丙", 2.0, 2.5), ("丁", 2.5, 3.0))


def sha256(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_tones(path, amplitude) -> None:
    """Write a mono 48 kHz recording whose words are tones and whose pauses are silent."""
    pcm = np.zeros(round(3.5 * RATE))
    for _, start, end in WORDS:
        time = np.arange(round(end * RATE) - round(start * RATE)) / RATE
        pcm[round(start * RATE) : round(end * RATE)] = amplitude * np.sin(2 * np.pi * 440 * time)
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(RATE)
        audio.writeframes(np.rint(pcm).astype("<i2").tobytes())


@pytest.fixture
def two_chapters(tmp_path, monkeypatch, performance):
    """Stage two one-segment chapters at different levels; the first declares a level gain."""
    release = repository.read(production.Edition("zh").script)["release"]
    monkeypatch.setattr(repository, "ROOT", tmp_path)
    monkeypatch.setattr(soundtrack_assembly, "DURATION", 24)
    monkeypatch.setattr(soundtrack_assembly, "CREDITS_DURATION", 4)
    # Retained-group custody has its own tests; these recordings carry no groups.
    monkeypatch.setattr(soundtrack_assembly, "validate_group_inputs", lambda *_, **__: set())
    edition = production.Edition("zh")
    edition.evidence.mkdir(parents=True)
    text = "甲乙。丙丁。"
    segments, records, alignments = [], [], []
    for index, (chapter, amplitude) in enumerate((("a", 6000), ("b", 9000)), 1):
        segment_id = f"{index:02d}"
        path = tmp_path / f"take-{segment_id}.wav"
        write_tones(path, amplitude)
        segments.append(
            {
                "id": segment_id,
                "chapter": chapter,
                "chapter_title": chapter.upper(),
                "title": f"Scene {segment_id}",
                "utterance_groups": ["甲乙。", "丙丁。"],
                "text": text,
            }
        )
        text_sha256 = hashlib.sha256(text.encode()).hexdigest()
        records.append(
            {
                "id": segment_id,
                "text": text,
                "text_sha256": text_sha256,
                "path": path.name,
                "wav_sha256": sha256(path),
            }
        )
        alignments.append(
            {
                "id": segment_id,
                "wav_sha256": sha256(path),
                "text_sha256": text_sha256,
                "items": [
                    {"text": word, "start_time": start, "end_time": end}
                    for word, start, end in WORDS
                ],
            }
        )
    level = tmp_path / "level-01.json"
    level.write_text(json.dumps({"recording_sha256": records[0]["wav_sha256"], "gain_db": 1.0}))
    records[0]["level_correction"] = {
        "gain_db": 1.0,
        "evidence": level.name,
        "evidence_sha256": sha256(level),
    }
    script = {
        "title": "DDWG",
        "voice_performance": {
            **performance,
            "thought_level_tolerance_db": 0.75,
            "chapter_level_tolerance_db": 0.3,
        },
        "caption_timing": {"tail_seconds": 0.25, "short_cue_lead_seconds": 0.1},
        "release": release,
        "segments": segments,
    }
    (tmp_path / "content").mkdir()
    (tmp_path / edition.script).write_text(json.dumps(script, ensure_ascii=False))
    edition.narration_selected.write_text(json.dumps({"records": records}, ensure_ascii=False))
    edition.alignment_selected.write_text(json.dumps({"records": alignments}, ensure_ascii=False))
    return edition


@pytest.mark.ffmpeg
def test_assembly_lays_out_each_recording_with_its_own_level_and_exact_samples(two_chapters):
    soundtrack_assembly.assemble(two_chapters)
    receipt = json.loads(two_chapters.audio_assembly.read_text())
    timeline = json.loads(two_chapters.timeline.read_text())
    records = receipt["records"]
    # Each record carries its own declared level gain.
    assert [record["level_gain_db"] for record in records] == [1.0, 0]
    # The quieter chapter is raised and the louder one lowered towards the film's level.
    assert records[0]["chapter_gain_db"] > 0 > records[1]["chapter_gain_db"]
    # The gaps, the speech and the closing quiet fill the runtime before the credits exactly.
    gaps = [round(gap["seconds"] * RATE) for gap in receipt["gaps"]]
    assert [gap["kind"] for gap in receipt["gaps"]] == ["opening", "chapter"]
    assert records[0]["start_sample"] == gaps[0]
    assert records[1]["start_sample"] == gaps[0] + records[0]["frames"] + gaps[1]
    closing = round(receipt["closing_seconds"] * RATE)
    assert sum(gaps) + sum(record["frames"] for record in records) + closing == 20 * RATE
    assert receipt["samples_per_channel"] == 24 * RATE
    # Each gap keeps its declared pause and stays within its limit.
    assert round(3.0 * RATE) <= gaps[0] <= round(9.0 * RATE)
    assert round(3.4 * RATE) <= gaps[1] <= round(9.0 * RATE)
    # One designed pause at each thought join, from the native quiet heard there.
    pauses = [record["designed_thought_pauses"] for record in records]
    assert [len(designed) for designed in pauses] == [1, 1]
    assert all(designed[0]["designed_quiet_seconds"] == 0.45 for designed in pauses)
    # The timeline places each voice where its samples are, with its words inside it.
    for segment, record in zip(timeline["segments"], records, strict=True):
        assert segment["voice_start"] == record["start_sample"] / RATE
        assert segment["voice_end"] == (record["start_sample"] + record["frames"]) / RATE
        assert all(
            segment["voice_start"] <= word["start"] <= word["end"] <= segment["voice_end"]
            for word in segment["words"]
        )
    with wave.open(str(two_chapters.soundtrack)) as audio:
        assert (audio.getnchannels(), audio.getframerate()) == (2, RATE)
        pcm = np.frombuffer(audio.readframes(audio.getnframes()), "<i2").reshape(-1, 2)
    assert len(pcm) == 24 * RATE
    assert not pcm[: records[0]["start_sample"]].any()
    assert not pcm[records[1]["start_sample"] + records[1]["frames"] :].any()
    # Both receipt writers give the caption fields the same place.
    assert list(receipt)[-3:] == ["caption_count", "alignment_limits", "caption_timing"]
    assert receipt["caption_count"] == len(timeline["captions"]) == 4
