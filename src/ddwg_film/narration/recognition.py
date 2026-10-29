"""Recognition units: how a transcript is compared with the text it should hold.

Recognition compares units: each Han character, and each case-folded run of Latin letters,
digits and apostrophes, so punctuation and capitals in a transcript never count as
differences. A recording's unit error rate is the unit edit distance between its text and its
transcript over the text's unit count.
"""

from __future__ import annotations

import re


def recognition_units(text: str) -> list[str]:
    """Han characters and case-folded words of Latin letters, digits and apostrophes."""
    return re.findall(r"[\u4e00-\u9fff]|[a-z0-9']+", text.lower())


def heard_phrase(heard: str, phrase: str) -> bool:
    """Whether a transcript holds the phrase's units contiguously and in order."""
    wanted, observed = recognition_units(phrase), recognition_units(heard)
    return bool(wanted) and any(
        observed[i : i + len(wanted)] == wanted for i in range(len(observed) - len(wanted) + 1)
    )


def unit_distance(expected: list[str], observed: list[str]) -> int:
    """The fewest unit insertions, deletions and substitutions between two sequences."""
    row = list(range(len(observed) + 1))
    for i, want in enumerate(expected, 1):
        diagonal, row[0] = row[0], i
        for j, got in enumerate(observed, 1):
            diagonal, row[j] = (
                row[j],
                min(row[j] + 1, row[j - 1] + 1, diagonal + (want != got)),
            )
    return row[-1]
