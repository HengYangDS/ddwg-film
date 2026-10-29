"""Caption cue timing: word-bound cues, their declared edges and their reading time."""

import json
from itertools import pairwise
from pathlib import Path

import pytest

import ddwg_film.captions as captions
import ddwg_film.captions.timing as captions_timing
import ddwg_film.narration.spoken_units as spoken_units

# Real segments of both delivered timelines, with the cues the production timed for them.
SEGMENTS = json.loads((Path(__file__).parent / "cue-timing-segments.json").read_text())


def timeline(part: dict) -> dict:
    return {
        "caption_timing": part["caption_timing"],
        "segments": [
            {
                **segment,
                "words": [
                    {"text": text, "start": start, "end": end}
                    for text, start, end in segment["words"]
                ],
            }
            for segment in part["segments"]
        ],
    }


@pytest.mark.parametrize("code", ["zh", "en"])
def test_real_segments_time_their_cues_as_delivered(code):
    part = SEGMENTS[code]
    assert captions_timing.timed_caption_cues(timeline(part), code) == part["cues"]


def test_the_real_segments_cover_the_early_start_and_the_full_interval_hold():
    cues, leads = SEGMENTS["en"]["cues"], []
    for segment in SEGMENTS["en"]["segments"]:
        items = [
            {"text": text, "start_time": start, "end_time": end}
            for text, start, end in segment["words"]
        ]
        _, times = spoken_units.aligned_lookup(segment["text"], items)
        position = 0
        for cue in (cue for cue in cues if cue["segment"] == segment["id"]):
            leads.append(times[position][0] - cue["start"])
            position += len(spoken_units.units(cue["text"]))
    # A brief cue that ends a line starts before its first word, by at most 0.1 s.
    assert any(lead > 0 for lead in leads)
    assert max(leads) <= 0.1 + 1e-9
    # Every English cue holds until the next cue of its segment.
    assert all(a["end"] == b["start"] for a, b in pairwise(cues) if a["segment"] == b["segment"])


def segment(**changes) -> dict:
    words = [("甲", 1.0, 1.4), ("乙", 1.4, 1.8), ("丙", 2.4, 2.8), ("丁", 2.8, 3.2)]
    return {
        "id": "01",
        "text": "甲乙，丙丁。",
        "utterance_groups": ["甲乙，丙丁。"],
        "voice_start": 1.0,
        "voice_end": 3.3,
        "end": 5.0,
        "words": [{"text": text, "start": start, "end": end} for text, start, end in words],
        **changes,
    }


@pytest.mark.parametrize(
    ("caption_timing", "code", "message"),
    [
        (None, "zh", "requires a declared caption_timing policy"),
        ({"hold_mode": "full-interval"}, "zh", "full-interval for English"),
        ({"hold_mode": "sentence"}, "en", "full-interval for English"),
        ({"tail_seconds": 0.3}, "zh", "finite bounded seconds"),
        ({"short_cue_lead_seconds": True}, "zh", "finite bounded seconds"),
    ],
)
def test_cue_timing_requires_its_declared_bounded_policy(caption_timing, code, message):
    with pytest.raises(captions.CaptionError, match=message):
        captions_timing.timed_caption_cues(
            {"caption_timing": caption_timing, "segments": [segment()]}, code
        )


def test_a_cue_never_crosses_a_thought():
    policy = {"tail_seconds": 0.25}
    cues = captions_timing.timed_caption_cues(
        {"caption_timing": policy, "segments": [segment()]}, "zh"
    )
    assert [cue["text"] for cue in cues] == ["甲乙，丙丁。"]
    # A thought that ends at the comma would split the one line that both clauses fit.
    across = segment(utterance_groups=["甲乙，", "丙丁。"])
    with pytest.raises(captions.CaptionError, match="crosses a thought-group boundary: 01"):
        captions_timing.timed_caption_cues({"caption_timing": policy, "segments": [across]}, "zh")


def test_brief_captions_join_their_sentence_or_hold_for_reading():
    def cue(start, end, text, segment="01"):
        return {"start": start, "end": end, "text": text, "segment": segment}

    joined = captions_timing.steady_short_cues(
        [
            cue(0, 2.0, "不写“基本按时”，"),
            cue(2.0, 2.8, "这是信；"),
            cue(3.4, 5, "先说影响。"),
        ],
        33,
    )
    assert [c["text"] for c in joined] == ["不写“基本按时”，这是信；", "先说影响。"]
    assert (joined[0]["start"], joined[0]["end"]) == (0, 2.8)
    held = captions_timing.steady_short_cues(
        [
            cue(0, 2.0, "Report the state. "),
            cue(2.0, 2.7, "With the problem, "),
            cue(2.7, 5.0, "scope or completion condition missing, work is unframed. "),
        ],
        66,
    )
    # A brief cue with no quiet after it ends where the next cue's words begin.
    assert [c["text"] for c in held][1] == "With the problem, "
    assert held[1]["end"] == 2.7
    assert held[2]["start"] == 2.7
    apart = captions_timing.steady_short_cues(
        [cue(0, 2.0, "规则，"), cue(2.0, 2.8, "就退役。", "02")], 33
    )
    assert len(apart) == 2
    assert apart[1]["end"] - apart[1]["start"] < 1.0


def test_a_brief_caption_holds_into_the_quiet_without_moving_the_next_one():
    def cue(start, end, text):
        return {"start": start, "end": end, "text": text, "segment": "25"}

    held = captions_timing.steady_short_cues(
        [
            cue(0, 2.0, "信达雅要分开看。"),
            cue(2.0, 2.6, "也能行动。"),
            cue(3.4, 5.0, "雅，是用审美和修养。"),
        ],
        33,
    )
    assert [c["text"] for c in held][1] == "也能行动。"
    assert abs(held[1]["end"] - 3.0) < 1e-9
    assert held[2]["start"] == 3.4
    lent = captions_timing.steady_short_cues(
        [cue(2.0, 2.6, "也能行动。"), cue(2.75, 5.0, "雅，是用审美和修养。")], 33
    )
    # The next cue still starts on its first word: a brief cue only takes the quiet.
    assert lent[0]["end"] == 2.75
    assert lent[1]["start"] == 2.75


def test_the_receipt_counts_the_cues_and_states_their_timing():
    fields = captions_timing.caption_receipt_fields({"captions": [{}, {}]})
    assert fields == {"caption_count": 2, "caption_timing": captions_timing.CAPTION_TIMING}
