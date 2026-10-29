"""Spoken units: the characters a narration aligns, and the joins and thoughts they form.

A narration speaks its text as units: Chinese characters, Latin letters and digits. The aligner
returns items, such as words, that each hold some of those units with their times. Everything
else in the text is written, not spoken. The punctuation roles below are named once here, and
the captions and the soundtrack read each role from this module.
"""

from __future__ import annotations

import re
from bisect import bisect_left
from dataclasses import dataclass
from itertools import accumulate, pairwise

# Marks that end a sentence.
SENTENCE_ENDS = "。！？.!?"
# Marks that end a clause without ending its sentence.
SEMICOLONS = "；;"
# Marks after which a caption line ends: a sentence end or a semicolon. Only a sentence end
# keeps a brief cue from joining the cue after it.
LINE_ENDS = SENTENCE_ENDS + SEMICOLONS
# Closing quotes and brackets that follow a sentence end and belong to its sentence.
CLOSING_MARKS = "”’\"')]}"
# Quotation marks, which are not pauses of their own.
QUOTATION_MARKS = "“”‘’\"'"
# Marks that end a question.
QUESTION_MARKS = "？?"
# Chinese marks that close a clause, where a caption line may break.
CLAUSE_MARKS = "，。；：！？、"
# The Chinese enumeration comma: a line that ends there ends inside a list.
ENUMERATION_MARK = "、"
# English marks that break a phrase inside a sentence.
PHRASE_BREAKS = ",;:"
# Marks after which a phrase ends: a clause, phrase or sentence mark.
PHRASE_END_MARKS = frozenset(CLAUSE_MARKS + PHRASE_BREAKS + SENTENCE_ENDS + SEMICOLONS)


class AlignmentError(ValueError):
    """Aligned items or thought groups that do not fit their narration text exactly."""


def units(text: str) -> str:
    """The text's spoken units, lowercased: Chinese characters, Latin letters and digits."""
    return "".join(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]", text)).lower()


def _require_cover(stream: str, text: str) -> None:
    if stream != units(text):
        msg = f"Alignment does not cover exact text: {stream[:50]}"
        raise AlignmentError(msg)


def aligned_lookup(text: str, items: list[dict]) -> tuple[str, list[tuple[float, float]]]:
    """The units of the aligned items, which must be the text's, and each unit's item times."""
    stream = ""
    times = []
    for item in items:
        value = units(item["text"])
        stream += value
        times.extend([(item["start_time"], item["end_time"])] * len(value))
    _require_cover(stream, text)
    return stream, times


def unit_gaps(text: str) -> list[str]:
    """The text written between each unit and the next one, in order."""
    gaps, current, seen = [], "", False
    for character in text:
        if units(character):
            if seen:
                gaps.append(current)
            current, seen = "", True
        elif seen:
            current += character
    return gaps


def thought_ends(text: str, groups: list[str]) -> list[int]:
    """The number of units spoken by the end of each thought.

    The thought groups must be strings that each hold a unit and that join into the text.
    """
    if (
        not isinstance(groups, list)
        or not groups
        or any(not isinstance(group, str) or not units(group) for group in groups)
        or "".join(groups) != text
    ):
        msg = "Designed pauses require complete nonempty thought groups"
        raise AlignmentError(msg)
    return list(accumulate(len(units(group)) for group in groups))


@dataclass(frozen=True)
class ItemJoin:
    """Two consecutive aligned items that hold units, and the marks written between them.

    `left` and `right` index the items. `thought` is the index of the thought that holds the
    left item, and `ends_thought` tells whether that thought ends with it. `marks` is the text
    written between the left item's last unit and the right item's first, without whitespace.
    """

    left: int
    right: int
    thought: int
    ends_thought: bool
    marks: str


def _spoken(items: list[dict]) -> list[int]:
    """The indices of the items that hold units."""
    return [index for index, item in enumerate(items) if units(item["text"])]


def item_joins(text: str, items: list[dict], groups: list[str]) -> list[ItemJoin]:
    """Every join between consecutive aligned items of a narration, in order.

    The items must hold exactly the text's units (as `aligned_lookup` requires), the thought
    groups must be complete (as `thought_ends` requires), and every thought must end where an
    item ends. Only each item's "text" is read, so any item or word record serves. An item
    without units, such as a mark the aligner returns on its own, belongs to no join.
    """
    _require_cover("".join(units(item["text"]) for item in items), text)
    ends, gaps, spoken = thought_ends(text, groups), unit_gaps(text), _spoken(items)
    offsets = list(accumulate(len(units(items[index]["text"])) for index in spoken))
    if not set(ends) <= set(offsets):
        msg = "Every thought boundary requires an aligned item boundary"
        raise AlignmentError(msg)
    return [
        ItemJoin(
            left,
            right,
            thought=bisect_left(ends, offset),
            ends_thought=offset in ends,
            marks="".join(gaps[offset - 1].split()),
        )
        for (left, right), offset in zip(pairwise(spoken), offsets[:-1], strict=True)
    ]


def phrase_joins(text: str, items: list[dict], groups: list[str]) -> list[ItemJoin]:
    """The joins inside thoughts where a phrase ends: a phrase-end mark follows the left item.

    The items and groups are validated as `item_joins` validates them.
    """
    return [
        join
        for join in item_joins(text, items, groups)
        if not join.ends_thought and PHRASE_END_MARKS & set(join.marks)
    ]


@dataclass(frozen=True)
class ThoughtSpan:
    """The aligned items that speak one thought: the first and the last, by index."""

    first: int
    last: int


def thought_spans(text: str, items: list[dict], groups: list[str]) -> list[ThoughtSpan]:
    """The items that speak each thought of a narration, in order.

    The items and groups are validated as `item_joins` validates them, and only each item's
    "text" is read: a caller takes the times from its own records, such as an alignment
    item's "start_time" and "end_time" or a timeline word's "start" and "end". Every thought
    has at least one item; an item without units belongs to no thought.
    """
    boundaries = [join for join in item_joins(text, items, groups) if join.ends_thought]
    spoken = _spoken(items)
    firsts = [spoken[0], *(join.right for join in boundaries)]
    lasts = [*(join.left for join in boundaries), spoken[-1]]
    return [ThoughtSpan(first, last) for first, last in zip(firsts, lasts, strict=True)]
