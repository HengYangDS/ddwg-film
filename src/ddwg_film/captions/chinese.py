"""Set a Chinese passage as single caption lines that end at its own punctuation.

A sentence end, semicolon, question or exclamation closes a line, and between them the lines
balance the length of their speech: the fewest lines of at most 25 characters of speech win,
a line that ends inside an enumeration or holds under a second of speech costs more, and a
line may hold up to 30 characters when that reads better.
"""

from __future__ import annotations

import re

from ddwg_film.captions import CaptionError
from ddwg_film.narration.spoken_units import CLAUSE_MARKS, ENUMERATION_MARK, LINE_ENDS, units
from ddwg_film.specification import CAPTION_LIMITS

# A Chinese line holds at most 25 characters of speech, about five seconds, or up to 30 when
# that keeps its sentence's number of lines or ends fewer of them inside an enumeration.
LINE_UNITS = 25
WIDE_LINE_UNITS = 30
# Fewer than six characters are under a second of speech.
BRIEF_UNITS = 6
# What a Chinese line costs: one more line; more when it ends inside an enumeration at 、;
# more than either when it is brief; and a little when it holds over 25 characters.
LINE_COST = 100
ENUMERATION_COST = 150
BRIEF_COST = 200
WIDE_COST = 20
_CLAUSE = re.compile(f"[^{re.escape(CLAUSE_MARKS)}]+[{re.escape(CLAUSE_MARKS)}]?")


def _fits(run: list[str], first: int, last: int, cap: int) -> bool:
    """Whether a sentence's clauses first to last fit one line of cap characters of speech.

    A sentence's closing clause of under six characters, under a second of speech, rides
    on its line, as a brief cue later joins the cue before it.
    """
    line = "".join(run[first:last])
    rides = last == len(run) and len(units(run[last - 1])) < BRIEF_UNITS
    body = "".join(run[first : last - 1]) if rides else line
    return len(line) <= CAPTION_LIMITS["zh"] and (last == first + 1 or len(units(body)) <= cap)


def _line_cost(run: list[str], last: int, line: str) -> int:
    """What one line costs among the lines of its sentence."""
    cost = LINE_COST
    if last < len(run) and line.endswith(ENUMERATION_MARK):
        cost += ENUMERATION_COST
    if len(run) > 1 and len(units(line)) < BRIEF_UNITS:
        cost += BRIEF_COST
    if len(units(line)) > LINE_UNITS:
        cost += WIDE_COST
    return cost


def _partition(run: list[str], cap: int) -> list[str]:
    """The cheapest lines for a sentence's clauses; a tie keeps the longest early line."""
    best: dict[int, tuple[float, list[str]]] = {len(run): (0.0, [])}
    for first in range(len(run) - 1, -1, -1):
        choice = None
        for last in range(len(run), first, -1):
            if last not in best or not _fits(run, first, last, cap):
                continue
            line = "".join(run[first:last])
            cost = best[last][0] + _line_cost(run, last, line)
            if choice is None or cost < choice[0]:
                choice = (cost, [line, *best[last][1]])
        if choice is None:
            msg = f"Caption requires semantic segmentation: {run[first]}"
            raise CaptionError(msg)
        best[first] = choice
    return best[0][1]


def _settle(run: list[str]) -> list[str]:
    """Set a sentence's lines at 25 characters of speech, or at 30 where that reads better.

    The wider lines win when they keep the sentence's number of lines or end fewer of them
    inside an enumeration.
    """
    strict, wide = _partition(run, LINE_UNITS), _partition(run, WIDE_LINE_UNITS)
    inside = [sum(line.endswith(ENUMERATION_MARK) for line in lines) for lines in (strict, wide)]
    return wide if len(wide) == len(strict) or inside[1] < inside[0] else strict


def caption_phrases(text: str) -> list[str]:
    """Set a Chinese passage as single caption lines that end at its punctuation.

    A sentence end, semicolon, question or exclamation closes its line. Between them
    a line holds at most 25 characters of speech, about five seconds, within the
    caption limit, and the fewest lines win. A line that ends inside an enumeration
    at 、 costs more than one more line, and a line of fewer than six characters,
    under a second of speech, costs more than either. A line may hold up to 30
    characters of speech when the sentence then keeps its number of lines or ends
    fewer lines inside an enumeration. Ties keep the longest early line, so a
    passage without such a choice reads as before.
    """
    result, run = [], []
    for clause in (clause for clause in _CLAUSE.findall(text) if clause.strip()):
        run.append(clause)
        if clause.endswith(tuple(LINE_ENDS)):
            result.extend(_settle(run))
            run = []
    if run:
        result.extend(_settle(run))
    return result
