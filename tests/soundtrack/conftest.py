"""Fixtures shared by the soundtrack tests: a complete designed pause contract."""

import pytest

import filmkit.soundtrack.policy as soundtrack_policy

PERFORMANCE = {
    "assembly_mode": "native-speech-designed-pauses",
    "designed_pauses": {
        "thought": 0.45,
        "question": 0.7,
        "opening": 3.0,
        "paragraph": 1.6,
        "chapter": 3.4,
        "closing": 2.6,
    },
    "designed_pause_limits": {"opening": 9.0, "paragraph": 5.5, "chapter": 9.0},
    "designed_pause_weights": {"opening": 2.0, "paragraph": 1.0, "chapter": 2.5},
    "tail_guard_seconds": 0.3,
    "thought_pause_range": [0.3, 0.6],
    "paragraph_pause_range": [1.2, 2.0],
}


@pytest.fixture
def performance():
    """A voice performance that declares only the required parts of the pause contract."""
    return {**PERFORMANCE}


@pytest.fixture
def designed_policy(performance):
    """Validate the performance's pause contract with the given parts declared over it."""

    def designed(**overrides):
        return soundtrack_policy.designed_pause_policy({**performance, **overrides})

    return designed
