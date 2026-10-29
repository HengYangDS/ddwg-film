"""The designed pause contract that each edition's voice performance declares, validated once.

The contract declares the designed pause of each kind, the limits and weights that share the
remaining runtime among the gaps, the ranges of thought and paragraph pauses, the level
tolerances, and the caps, floors, breath and releases of the pauses inside thoughts. Its
validated form, under the names below, is what the assembly receipt records.
"""

from __future__ import annotations

import math
import re

from ddwg_film.narration.spoken_units import units
from ddwg_film.soundtrack.quiet import RELEASE_SECONDS

DESIGNED_PAUSE_KEYS = ("thought", "question", "opening", "paragraph", "chapter", "closing")
DESIGNED_GAP_KEYS = ("opening", "paragraph", "chapter")
# A declared release is at most this long.
LONGEST_RELEASE_SECONDS = 0.3


class PausePolicyError(ValueError):
    """A voice performance whose designed pause contract is incomplete or out of bounds."""


def _range(name: str, value: object, low: float, high: float) -> None:
    """Refuse a value that is not a finite number from low to high."""
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not low <= value <= high
    ):
        msg = f"{name} must be a number from {low} to {high}"
        raise PausePolicyError(msg)


def _optional(name: str, value: object, low: float, high: float) -> object:
    """A declared value within its range, or None when it is not declared."""
    if value is not None:
        _range(name, value, low, high)
    return value


def _by_kind(name: str, value: object, keys: tuple[str, ...], measure: str) -> dict:
    """A mapping that holds exactly the given kinds."""
    if not isinstance(value, dict) or set(value) != set(keys):
        msg = f"{name} requires exactly the {', '.join(keys[:-1])} and {keys[-1]} {measure}"
        raise PausePolicyError(msg)
    return value


def _pause_seconds(performance: dict) -> dict:
    """The designed pause of each kind, from 0.2 to 12 s."""
    pauses = _by_kind(
        "designed_pauses", performance.get("designed_pauses"), DESIGNED_PAUSE_KEYS, "seconds"
    )
    for key in DESIGNED_PAUSE_KEYS:
        _range(f"designed_pauses.{key}", pauses[key], 0.2, 12)
    return pauses


def _gap_limits(performance: dict, pauses: dict) -> dict:
    """The longest gap of each kind, from its designed pause to 20 s."""
    limits = _by_kind(
        "designed_pause_limits",
        performance.get("designed_pause_limits"),
        DESIGNED_GAP_KEYS,
        "seconds",
    )
    for key in DESIGNED_GAP_KEYS:
        _range(f"designed_pause_limits.{key}", limits[key], pauses[key], 20)
    return limits


def _weights(performance: dict) -> dict:
    """The share of the remaining runtime that each kind of gap takes, from 0 to 10."""
    weights = _by_kind(
        "designed_pause_weights",
        performance.get("designed_pause_weights"),
        DESIGNED_GAP_KEYS,
        "weights",
    )
    for key in DESIGNED_GAP_KEYS:
        _range(f"designed_pause_weights.{key}", weights[key], 0, 10)
    if not any(weights.values()):
        msg = "designed_pause_weights requires a positive weight"
        raise PausePolicyError(msg)
    return weights


def _pause_range(name: str, value: object, low: float, middle: float, high: float) -> list:
    """The low and high pauses around a designed mean: [low, middle] and [middle, high]."""
    if not isinstance(value, list) or len(value) != 2:
        msg = f"{name} requires a low and a high value"
        raise PausePolicyError(msg)
    _range(f"{name} low", value[0], low, middle)
    _range(f"{name} high", value[1], middle, high)
    return value


def _mark_seconds(name: str, value: object, low: float, high: float) -> dict:
    """Seconds by the punctuation marks they apply to, each mark named once."""
    if not isinstance(value, dict) or not value:
        msg = f"{name} requires marks with seconds"
        raise PausePolicyError(msg)
    if not all(isinstance(marks, str) and marks and not units(marks) for marks in value):
        msg = f"{name} keys must be punctuation marks"
        raise PausePolicyError(msg)
    written = "".join(value)
    if len(set(written)) != len(written):
        msg = f"{name} names a mark twice"
        raise PausePolicyError(msg)
    for marks, seconds in value.items():
        _range(f"{name}.{marks}", seconds, low, high)
    return value


def _inner_caps(performance: dict, inner_cap: float | None) -> dict | None:
    """The caps of pauses inside a thought by their marks, from 0.1 s to the inner cap."""
    caps = performance.get("inner_pause_caps_seconds")
    if caps is None:
        return None
    if inner_cap is None:
        msg = "inner_pause_caps_seconds requires inner_pause_cap_seconds"
        raise PausePolicyError(msg)
    return _mark_seconds("inner_pause_caps_seconds", caps, 0.1, inner_cap)


def _floors_within_caps(floors: dict | None, caps: dict | None) -> None:
    """Refuse a floor above the cap of a mark it shares."""
    for marks, floor in (floors or {}).items():
        for key, cap in (caps or {}).items():
            if set(key) & set(marks) and floor > cap:
                msg = (
                    f"inner_pause_floors_seconds.{marks} exceeds its cap in "
                    "inner_pause_caps_seconds"
                )
                raise PausePolicyError(msg)


def _breath(performance: dict, floors: dict | None, ceiling: float) -> dict | None:
    """The breath a long run of speech takes at a floored mark: its group and its pause."""
    breath = performance.get("inner_breath")
    if breath is None:
        return None
    if not floors:
        msg = "inner_breath requires inner_pause_floors_seconds"
        raise PausePolicyError(msg)
    if not isinstance(breath, dict) or set(breath) != {"longest_group_seconds", "pause_seconds"}:
        msg = "inner_breath requires exactly longest_group_seconds and pause_seconds"
        raise PausePolicyError(msg)
    _range("inner_breath.longest_group_seconds", breath["longest_group_seconds"], 3, 20)
    _range("inner_breath.pause_seconds", breath["pause_seconds"], 0.1, ceiling)
    return breath


def _releases(performance: dict) -> dict:
    """The declared release seconds by thought join, such as 24.3 for segment 24's third."""
    releases = performance.get("released_tail_seconds", {})
    if not isinstance(releases, dict):
        msg = "released_tail_seconds requires seconds by thought join"
        raise PausePolicyError(msg)
    for key, seconds in releases.items():
        if not isinstance(key, str) or not re.fullmatch(r"\d{2}\.[1-9]\d*", key):
            msg = f"released_tail_seconds key must name a thought join such as 24.3: {key}"
            raise PausePolicyError(msg)
        _range(f"released_tail_seconds.{key}", seconds, RELEASE_SECONDS, LONGEST_RELEASE_SECONDS)
    return releases


def designed_pause_policy(performance: dict) -> dict:
    """Validate the declared native-speech pause contract once.

    Return its parts under the names the assembly receipt records, in its order; an optional
    part that is not declared takes its default.
    """
    if performance.get("assembly_mode") != "native-speech-designed-pauses":
        msg = "Assembly requires native speech with designed pauses"
        raise PausePolicyError(msg)
    pauses = _pause_seconds(performance)
    limits = _gap_limits(performance, pauses)
    weights = _weights(performance)
    tail_guard = performance.get("tail_guard_seconds", 0.3)
    _range("tail_guard_seconds", tail_guard, 0.05, 0.6)
    thought_range = _pause_range(
        "thought_pause_range", performance.get("thought_pause_range"), 0.2, pauses["thought"], 12
    )
    paragraph_range = _pause_range(
        "paragraph_pause_range",
        performance.get("paragraph_pause_range"),
        0.2,
        pauses["paragraph"],
        limits["paragraph"],
    )
    boundary_ratio = performance.get("thought_boundary_ratio", 1.0)
    _range("thought_boundary_ratio", boundary_ratio, 1.0, 2.0)
    boundary_margin = performance.get("thought_boundary_margin_seconds", 0.0)
    _range("thought_boundary_margin_seconds", boundary_margin, 0, 0.2)
    level_tolerance = _optional(
        "thought_level_tolerance_db", performance.get("thought_level_tolerance_db"), 0.5, 6.0
    )
    chapter_tolerance = _optional(
        "chapter_level_tolerance_db", performance.get("chapter_level_tolerance_db"), 0.1, 3.0
    )
    coda = _optional(
        "coda_thought_pause_seconds",
        performance.get("coda_thought_pause_seconds"),
        pauses["thought"],
        2.0,
    )
    inner_cap = _optional(
        "inner_pause_cap_seconds",
        performance.get("inner_pause_cap_seconds"),
        0.2,
        pauses["thought"],
    )
    # Floors and the breath pause stay within the inner cap, or the thought pause without one.
    ceiling = inner_cap or pauses["thought"]
    inner_caps = _inner_caps(performance, inner_cap)
    inner_floors = performance.get("inner_pause_floors_seconds")
    if inner_floors is not None:
        _mark_seconds("inner_pause_floors_seconds", inner_floors, 0.05, ceiling)
    _floors_within_caps(inner_floors, inner_caps)
    return {
        "pauses": pauses,
        "limits": limits,
        "weights": weights,
        "tail_guard": tail_guard,
        "thought_range": thought_range,
        "paragraph_range": paragraph_range,
        "boundary_ratio": boundary_ratio,
        "boundary_margin": boundary_margin,
        "level_tolerance": level_tolerance,
        "chapter_level_tolerance": chapter_tolerance,
        "coda": coda,
        "inner_cap": inner_cap,
        "inner_caps": inner_caps,
        "inner_floors": inner_floors,
        "inner_breath": _breath(performance, inner_floors, ceiling),
        "releases": _releases(performance),
    }


def segment_releases(policy: dict, segments: list[dict]) -> dict[str, dict[int, float]]:
    """The declared release seconds of each segment's thought joins, by join number.

    A key such as 24.3 names the join after the third thought of segment 24. A key that names
    no segment, or no join of its segment, is refused rather than ignored.
    """
    releases: dict[str, dict[int, float]] = {segment["id"]: {} for segment in segments}
    joins = {segment["id"]: len(segment["utterance_groups"]) - 1 for segment in segments}
    for key, seconds in policy["releases"].items():
        segment_id, join = key.split(".")
        if not 1 <= int(join) <= joins.get(segment_id, 0):
            msg = f"Released tail names no thought join: {key}"
            raise PausePolicyError(msg)
        releases[segment_id][int(join)] = seconds
    return releases
