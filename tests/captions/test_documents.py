"""Subtitle documents: the captions, chapters, transcript and chapter metadata of an edition."""

import json

import pytest

import filmkit.captions.documents as captions_documents
import filmkit.captions.timing as captions_timing
import filmkit.production as production
import filmkit.repository as repository
import filmkit.specification as specification


@pytest.mark.parametrize(
    ("code", "byline"),
    [("zh", "Yang HENG · 中文 · 25 分钟"), ("en", "Yang HENG · English · 25 min")],
)
def test_chapters_land_on_their_cards_and_head_the_transcript(tmp_path, monkeypatch, code, byline):
    release = repository.read(production.Edition(code).script)["release"]
    monkeypatch.setattr(repository, "ROOT", tmp_path)
    edition = production.Edition(code)
    repository.write(edition.script, {"release": release})
    edition.artifacts.mkdir(parents=True)

    def segment(sid, chapter, title, start):
        return {
            "id": sid,
            "chapter": chapter,
            "chapter_title": title,
            "title": f"Scene {sid}",
            "start": start,
            "voice_start": start + 1.8,
            "text": f"Text {sid}.",
        }

    timeline = {
        "title": "DDWG",
        "captions": [{"start": 1.9, "end": 3.0, "text": "Text 01. "}],
        "segments": [
            segment("01", "purpose", "One", 0.0),
            segment("02", "purpose", "One", 30.0),
            segment("03", "decide", "Two", 60.0),
        ],
    }
    timeline["segments"][2]["text"] = "Text 03 isn't done."
    captions_documents.subtitle_files(timeline, edition)
    output = edition.artifacts
    chapters = json.loads((output / "chapters.json").read_text())["chapters"]
    # The second chapter starts once its card is shown, after its scene starts.
    second = 60.0 + specification.CHAPTER_CARD_SHOWN
    assert [(c["title"], c["start"]) for c in chapters] == [("One", 0.0), ("Two", second)]
    metadata = (output / "chapters.ffmeta").read_text()
    assert f"START={round(second * 1000)}\n" in metadata
    assert f"END={specification.DURATION * 1000}\n" in metadata
    assert f"comment={edition.comment}\n" in metadata
    assert ("示意" in metadata) == (code == "zh")
    for name in (f"ddwg-{code}.srt", f"ddwg-{code}.vtt"):
        lines = (output / name).read_text().splitlines()
        assert "Text 01." in lines
        assert all(line == line.rstrip() for line in lines)
    transcript = (output / f"ddwg-{code}-transcript.md").read_text()
    assert transcript.splitlines()[2] == byline
    assert transcript.count("\n## ") == 2
    assert "\n## 02 Two\n\n00:01:01.800 · Scene 03\n" in transcript
    # Display copy sets an apostrophe as a typographic right single quote.
    assert "Text 03 isn’t done." in transcript
    assert captions_timing.typeset("Others' work isn't done") == "Others’ work isn’t done"


def test_timecodes_round_to_the_millisecond():
    assert captions_documents.timecode(3723.4567) == "01:02:03,457"
    assert captions_documents.timecode(59.9996, ".") == "00:01:00.000"
