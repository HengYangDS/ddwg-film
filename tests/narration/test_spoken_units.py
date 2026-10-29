"""Spoken units, the joins between aligned items and the thoughts they speak."""

import re

import pytest

import ddwg_film.narration.spoken_units as spoken_units


def items(*words):
    return [
        {"text": word, "start_time": float(index), "end_time": index + 0.5}
        for index, word in enumerate(words)
    ]


def test_alignment_requires_exact_source():
    assert (
        spoken_units.aligned_lookup("记录", [{"text": "记录", "start_time": 0, "end_time": 1}])[0]
        == "记录"
    )
    with pytest.raises(ValueError, match="Alignment does not cover exact text"):
        spoken_units.aligned_lookup("记录", [{"text": "结果", "start_time": 0, "end_time": 1}])


def test_joins_name_their_thought_and_the_marks_written_between_items():
    joins = spoken_units.item_joins(
        "先，看。再说", items("先", "看", "再", "说"), ["先，看。", "再说"]
    )
    assert joins == [
        spoken_units.ItemJoin(left=0, right=1, thought=0, ends_thought=False, marks="，"),
        spoken_units.ItemJoin(left=1, right=2, thought=0, ends_thought=True, marks="。"),
        spoken_units.ItemJoin(left=2, right=3, thought=1, ends_thought=False, marks=""),
    ]
    # Marks are written without the spaces between words, and quotation marks stay marks.
    english = spoken_units.item_joins(
        "“One”, two. Three four",
        items("One", "two", "Three", "four"),
        ["“One”, two. ", "Three four"],
    )
    assert [(join.marks, join.ends_thought) for join in english] == [
        ("”,", False),
        (".", True),
        ("", False),
    ]


def test_items_without_units_belong_to_no_join():
    aligned = items("先", "，", "看")
    joins = spoken_units.item_joins("先，看", aligned, ["先，", "看"])
    assert joins == [spoken_units.ItemJoin(0, 2, 0, ends_thought=True, marks="，")]
    assert spoken_units.thought_spans("先，看", aligned, ["先，", "看"]) == [
        spoken_units.ThoughtSpan(first=0, last=0),
        spoken_units.ThoughtSpan(first=2, last=2),
    ]


@pytest.mark.parametrize(
    ("text", "words", "groups", "message"),
    [
        ("先看", ("先", "看"), ["先看", "再"], "complete nonempty thought groups"),
        ("先，看", ("先", "看"), ["先", "，", "看"], "complete nonempty thought groups"),
        ("先看", ("先", "看"), [], "complete nonempty thought groups"),
        ("先看再", ("先看", "再"), ["先", "看再"], "requires an aligned item boundary"),
        ("先看", ("先", "再"), ["先看"], "Alignment does not cover exact text"),
    ],
)
def test_joins_require_exact_alignment_and_complete_thoughts(text, words, groups, message):
    with pytest.raises(spoken_units.AlignmentError, match=message):
        spoken_units.item_joins(text, items(*words), groups)


def test_thought_spans_index_the_items_that_speak_each_thought():
    aligned = items("Check", "the", "source.", "Then", "act.")
    groups = ["Check the source. ", "Then act."]
    assert spoken_units.thought_spans("Check the source. Then act.", aligned, groups) == [
        spoken_units.ThoughtSpan(first=0, last=2),
        spoken_units.ThoughtSpan(first=3, last=4),
    ]
    # Only the items' texts are read, so timeline words with their own time keys serve too.
    words = [{"text": item["text"], "start": 0.0, "end": 1.0} for item in aligned]
    spans = spoken_units.thought_spans("Check the source. Then act.", words, groups)
    assert [(span.first, span.last) for span in spans] == [(0, 2), (3, 4)]
    assert spoken_units.thought_ends("Check the source. Then act.", groups) == [14, 21]


def test_each_punctuation_role_is_named_once():
    # A semicolon ends a caption line but not a sentence, so a brief cue may still join it.
    assert set(spoken_units.SEMICOLONS) <= set(spoken_units.LINE_ENDS)
    assert not set(spoken_units.SEMICOLONS) & set(spoken_units.SENTENCE_ENDS)
    sentence_end = re.compile(
        f"[{re.escape(spoken_units.SENTENCE_ENDS)}][{re.escape(spoken_units.CLOSING_MARKS)}]*$"
    )
    assert all(sentence_end.search(text) for text in ("完成。", "Done.", "“Done.”", "(Done!)"))
    assert not any(sentence_end.search(text) for text in ("这是信；", "Then;", "Wait,"))
    assert spoken_units.units(spoken_units.QUOTATION_MARKS + spoken_units.CLAUSE_MARKS) == ""
