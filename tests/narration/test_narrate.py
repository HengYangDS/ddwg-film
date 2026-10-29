"""Narrating, aligning and transcribing one edition through the production commands."""

import json
import sys

import pytest

import filmkit.narration.narrate as narration_narrate
import filmkit.repository as repository

BASE = "build/evidence/editions/zh/ear-first"
RECEIPT = f"{BASE}/narration-receipt-06-07.json"
PYTHON = [sys.executable, "-B"]
NARRATION = [
    *PYTHON,
    "-m",
    "filmkit.narration.synthesis",
    "--script",
    "content/film-script.json",
    "--cast",
    "content/voice-reference.json",
    "--folder",
    f"{BASE}/recordings",
    "--receipt",
    RECEIPT,
    "--ids",
    "06,07",
]
ALIGNMENT = [
    *PYTHON,
    "-m",
    "filmkit.narration.alignment",
    "--model",
    "build/runtime/tool-cache/narration-aligner",
    "--receipt",
    RECEIPT,
    "--output",
    f"{BASE}/alignment-06-07.json",
    "--language",
    "Chinese",
]
TRANSCRIPTION = [
    *PYTHON,
    "-m",
    "filmkit.narration.transcription",
    "--receipt",
    RECEIPT,
    "--output",
    f"{BASE}/asr-06-07.json",
    "--language",
    "Chinese",
]


@pytest.mark.parametrize(
    ("scope", "expected"),
    [
        (
            narration_narrate.Scope.ALL,
            [("narration", NARRATION), ("alignment", ALIGNMENT), ("transcription", TRANSCRIPTION)],
        ),
        (narration_narrate.Scope.PLAN, [("narration", [*NARRATION, "--dry-run"])]),
        (
            narration_narrate.Scope.CHECKS,
            [("alignment", ALIGNMENT), ("transcription", TRANSCRIPTION)],
        ),
    ],
)
def test_narrate_edition_plans_receipts_named_after_the_selected_segments(scope, expected):
    assert narration_narrate.steps("zh", "06,07", scope) == expected


@pytest.fixture
def commands(monkeypatch) -> list:
    calls = []
    monkeypatch.setattr(
        narration_narrate.subprocess,
        "run",
        lambda command, **options: calls.append((command, options)),
    )
    return calls


def test_narrate_edition_runs_the_whole_edition_from_the_root(commands, capsys):
    narration_narrate.main(["--language", "en"])
    base = "build/evidence/editions/en/ear-first"
    run = [command for command, _ in commands]
    assert [command[2:4] for command in run] == [
        ["-m", "filmkit.narration.synthesis"],
        ["-m", "filmkit.narration.alignment"],
        ["-m", "filmkit.narration.transcription"],
    ]
    assert run[0][4:7] == ["--script", "content/en/film-script.json", "--cast"]
    assert run[0][-1] == f"{base}/narration-receipt.json"
    assert run[1][-3:] == [f"{base}/alignment.json", "--language", "English"]
    assert run[2][-3:] == [f"{base}/asr.json", "--language", "English"]
    assert [options for _, options in commands] == [{"cwd": repository.ROOT, "check": True}] * 3
    printed = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [line["step"] for line in printed] == ["narration", "alignment", "transcription"]


@pytest.mark.parametrize(
    ("flag", "expected"),
    [
        ("--dry-run", [("filmkit.narration.synthesis", "--dry-run")]),
        (
            "--skip-generation",
            [
                ("filmkit.narration.alignment", "Chinese"),
                ("filmkit.narration.transcription", "Chinese"),
            ],
        ),
    ],
)
def test_a_mode_flag_runs_only_its_steps(commands, flag, expected):
    narration_narrate.main(["--language", "zh", flag])
    assert [(command[3], command[-1]) for command, _ in commands] == expected
