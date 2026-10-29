"""The production review record: its schema, scored dimensions, mean and thresholds.

`filmkit.review.round` writes each edition's record from a finished review round, and
`filmkit.delivery.verification` accepts it; both read these definitions. The record
lives at `Edition.production_review`.
"""

from __future__ import annotations

SCHEMA_VERSION = 2
# The scored dimensions in record order, with what each one asks reviewers to judge.
DIMENSIONS = {
    "subject_and_faithfulness": (
        "DDWG remains the subject; all seven documents substantively covered with "
        "conditions and boundaries; examples illuminate rules; Human/Agent "
        "responsibility and role combinations accurate."
    ),
    "narrative_and_clarity": (
        "the real problem before the response; terms defined before use; connected "
        "argument; clear chapter boundaries; ending returns to the opening; the "
        "edition stands alone."
    ),
    "narration_identity_and_performance": (
        "same voice identity across editions; delivery natural (not sleepy, rushed or "
        "theatrical); distinct thought pauses, paragraph boundaries and audible phrase "
        "tails; continuous and idiomatic."
    ),
    "pronunciation_and_bilingual_language": (
        "tones and polyphones in context or English vowels and stress; idiomatic "
        "language (not translated); consistent terms."
    ),
    "visual_explanation_and_motion": (
        "pictures explain relationships, operations, comparisons and consequences as "
        "narration develops; restrained but varied, intentional 2D motion; text "
        "supports the visual argument."
    ),
    "composition_and_typography": (
        "alignment guides, hierarchy, margins, density, modest single-line captions, "
        "consistent color and contrast; collisions or clipping with timecodes."
    ),
    "sound_picture_continuity": (
        "speech, captions, diagrams and scene changes synchronized; complete thoughts "
        "survive the edit; image stays purposeful through transitions and pauses."
    ),
    "credits_and_deliverable_craft": (
        "covers and Yang HENG metadata; restrained signature; subtitles and transcript "
        "match the speech; chapters; player; opening, ending, covers and entry form "
        "one edition."
    ),
}
# The verifier's floor: the overall score and every dimension at least this.
OVERALL_MINIMUM = 90
DIMENSION_MINIMUM = 90


def overall(scores: dict[str, float]) -> float:
    """The record's overall score: the mean of its dimension scores to one decimal."""
    return round(sum(scores.values()) / len(scores), 1)
