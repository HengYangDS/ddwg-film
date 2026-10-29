"""The production review record: its schema, scored dimensions, mean and thresholds.

`filmkit.review.round` writes each edition's record from a finished review round, and
`filmkit.delivery.verification` accepts it; both read these definitions. The film declares
its scored dimensions and floors. The record lives at `Edition.production_review`.
"""

from __future__ import annotations

from filmkit.film import FILM

SCHEMA_VERSION = 2
# The scored dimensions in record order, with what each one asks reviewers to judge.
DIMENSIONS = dict(FILM.review.dimensions)
# The verifier's floor: the overall score and every dimension at least this.
OVERALL_MINIMUM = FILM.review.overall_minimum
DIMENSION_MINIMUM = FILM.review.dimension_minimum


def overall(scores: dict[str, float]) -> float:
    """The record's overall score: the mean of its dimension scores to one decimal."""
    return round(sum(scores.values()) / len(scores), 1)
