"""Exercise the sound-picture sync audit on a small timeline and label trace."""

import json
import re

import pytest

import filmkit.picture.rendering as picture_rendering
import filmkit.picture.sync_audit as picture_sync_audit
import filmkit.repository as repository
from filmkit.picture.rendering import PictureError


def timeline():
    words = [
        ("Test", 1.0, 1.3),
        ("the", 1.3, 1.5),
        ("judgment.", 1.5, 2.0),
        ("Solve", 4.0, 4.4),
        ("the", 4.4, 4.6),
        ("whole", 5.0, 5.5),
        ("problem.", 6.0, 6.5),
    ]
    segment = {
        "id": "01",
        "text": "Test the judgment. Solve the whole problem.",
        "utterance_groups": ["Test the judgment. ", "Solve the whole problem."],
        "words": [{"text": text, "start": a, "end": b} for text, a, b in words],
    }
    return {"segments": [segment]}


def line(t, label, contrast=4.0, scene="01"):
    return f"{t:.2f}\t{scene}\t{contrast:.2f}\t1.000\t{label}\n"


def frames(a, b, label):
    """One trace row per 0.1 s frame from a to b inclusive."""
    return [line(a + k / 10, label) for k in range(round((b - a) * 10) + 1)]


def test_labels_are_judged_against_their_spoken_clause():
    trace = [
        line(1.1, "Test the judgment"),
        line(0.4, " Solve the whole problem"),
        line(9.0, "Unspoken name"),
        line(1.2, "faint", contrast=2.0),
    ]
    report, judged = picture_sync_audit.audit(timeline(), trace)
    verdicts = {row["label"]: row["verdict"] for row in judged}
    assert verdicts == {
        "Test the judgment": "in-sync",
        "Solve the whole problem": "before-clause",
    }
    assert report["labels_judged"] == 2
    assert report["labels_unmatched"] == 1
    assert report["unmatched"] == [{"scene": "01", "label": "Unspoken name", "legible": 9.0}]
    assert report["far_from_words"] == []
    assert report["out_of_sync"] == 1
    assert report["by_scene"] == {"01": 1}


def test_a_label_shown_far_from_its_only_words_is_listed():
    report = picture_sync_audit.audit(timeline(), [line(12.5, "the judgment")])[0]
    assert report["labels_unmatched"] == 1
    assert report["unmatched"] == []
    assert report["out_of_sync"] == 0
    assert report["far_from_words"] == [
        {"scene": "01", "label": "the judgment", "legible": 12.5, "spoken": [1.3]}
    ]


def test_a_label_far_ahead_or_behind_its_words_is_out_of_sync():
    ahead = picture_sync_audit.audit(timeline(), [line(4.2, "problem")])[0]["findings"]
    late = picture_sync_audit.audit(timeline(), [line(3.0, "judgment")])[0]["findings"]
    assert [row["verdict"] for row in ahead + late] == [
        "ahead-in-clause",
        "after-words",
    ]


def test_speech_without_a_legible_name_for_over_a_second_is_reported():
    trace = frames(1.0, 2.0, "Test the judgment") + frames(5.8, 6.5, "Solve the whole problem")
    trace += [line(4.5, "faint", contrast=2.0), line(4.6, "17")]
    report = picture_sync_audit.continuity(timeline(), trace, step=0.1)
    assert report["unnamed_speech"] == [{"thought": "01.2", "from": 4.0, "to": 5.7}]
    named = frames(1.0, 2.0, "Test the judgment") + frames(5.0, 6.5, "Solve the whole problem")
    assert picture_sync_audit.continuity(timeline(), named, step=0.1)["unnamed_speech"] == []


def test_a_previous_picture_held_over_a_second_into_a_thought_is_reported():
    held = frames(1.0, 5.2, "Test the judgment") + frames(5.3, 6.5, "Solve the whole problem")
    assert picture_sync_audit.continuity(timeline(), held, step=0.1)["held_over"] == [
        {"thought": "01.2", "held": 1.3}
    ]
    cut = frames(1.0, 4.6, "Test the judgment") + frames(4.7, 6.5, "Solve the whole problem")
    assert picture_sync_audit.continuity(timeline(), cut, step=0.1)["held_over"] == []


def mark(t, box, named, scene="01"):
    return f"{t:.2f}\t{scene}\t" + "\t".join(str(v) for v in box) + f"\t{int(named)}\n"


def test_a_mark_that_stands_before_its_name_is_reported_as_a_seat():
    samples = range(20)
    # A seat waits 1.2 s for its name; a mark named from its first frame and a mark named
    # after 0.5 s are not seats, nor is an illustration that is never named.
    marks = [mark(4.0 + k / 10, (300, 400, 340, 440), named=k >= 12) for k in samples]
    marks += [mark(4.0 + k / 10, (600, 400, 640, 440), named=True) for k in samples]
    marks += [mark(4.0 + k / 10, (900, 400, 940, 440), named=k >= 5) for k in samples]
    marks += [mark(4.0 + k / 10, (1200, 400, 1240, 440), named=False) for k in samples]
    assert picture_sync_audit.seats(timeline(), marks, step=0.1) == [
        {"thought": "01.2", "at": 4.0, "lag": 1.2, "box": [300, 400, 340, 440]}
    ]


def test_a_ruled_row_that_stands_before_its_name_is_reported_as_a_seat():
    # A ruled row has no height; it is still followed from frame to frame.
    rows = [mark(4.0 + k / 10, (300, 400, 900, 400), named=k >= 10) for k in range(20)]
    assert picture_sync_audit.seats(timeline(), rows, step=0.1) == [
        {"thought": "01.2", "at": 4.0, "lag": 1.0, "box": [300, 400, 900, 400]}
    ]


def test_parts_are_judged_on_their_own_and_reports_are_deterministic(tmp_path):
    trace = [line(1.1, "Test · Solve"), line(4.1, "Solve")]
    judged = picture_sync_audit.audit(timeline(), trace)[1]
    assert sorted(row["label"] for row in judged) == ["Solve", "Test"]
    timeline_path, trace_path = tmp_path / "timeline.json", tmp_path / "trace.tsv"
    marks_path = tmp_path / "marks.tsv"
    timeline_path.write_text(json.dumps(timeline()))
    trace_path.write_text("".join(trace))
    marks_path.write_text(mark(1.0, (300, 400, 340, 440), named=True))
    outputs = []
    for name in ("first.json", "second.json"):
        out = tmp_path / name
        picture_sync_audit.main(
            [
                str(timeline_path),
                str(trace_path),
                "--out",
                str(out),
                "--bind",
                str(timeline_path),
                "--marks",
                str(marks_path),
            ]
        )
        outputs.append(out.read_text())
    assert outputs[0] == outputs[1]
    written = json.loads(outputs[0])
    assert written["bound_timeline"] == {
        "path": str(timeline_path),
        "sha256": repository.sha(timeline_path),
    }
    # The trace comes from running the composition, so the report binds its script too.
    composition = repository.ROOT / picture_rendering.COMPOSITION_SCRIPT
    assert written["composition_sha256"] == repository.sha(composition)
    assert set(written["continuity"]) == {"unnamed_speech", "held_over", "seats"}


def test_words_that_do_not_cover_their_segment_text_are_refused():
    # Clause starts follow the text's stops, so the words must spell the whole text.
    uncovered = timeline()
    uncovered["segments"][0]["words"].pop()
    with pytest.raises(PictureError, match=re.escape("01: the aligned words do not cover")):
        picture_sync_audit.audit(uncovered, [line(1.1, "Test the judgment")])


def test_the_summary_keys_are_the_report_counts():
    report = picture_sync_audit.audit(timeline(), [line(4.2, "problem")])[0]
    assert picture_sync_audit.VERDICTS == ("before-clause", "ahead-in-clause", "after-words")
    assert {key: report[key] for key in picture_sync_audit.SUMMARY_KEYS} == {
        "tolerance": 0.3,
        "labels_judged": 1,
        "labels_unmatched": 0,
        "out_of_sync": 1,
        "before-clause": 0,
        "ahead-in-clause": 1,
        "after-words": 0,
    }
