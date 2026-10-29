"""Narrate, align and transcribe one edition through the production CLIs.

Runs the synthesis, alignment and transcription commands of `ddwg_film.narration` from
the repository root on the edition's ear-first evidence. With --ids only those segments
are narrated, into a receipt, alignment and transcript named after them, such as
narration-receipt-06-07.json, alignment-06-07.json and asr-06-07.json.

Usage: python -m ddwg_film.narration.narrate
    --language zh|en [--ids 06,07] [--dry-run | --skip-generation]
--dry-run prints the narration plan without writing; --skip-generation aligns and
transcribes the existing receipt. Each step runs under this tool's interpreter.
"""

import argparse
import enum
import json
import subprocess
import sys
import time

import ddwg_film.repository as repository
from ddwg_film.production import CODES, Edition

ALIGNER = "build/runtime/tool-cache/narration-aligner"


class Scope(enum.Enum):
    """The steps a run takes: every step, the narration plan alone, or the checks alone."""

    ALL = "all"
    PLAN = "plan"
    CHECKS = "checks"


def evidence_paths(code: str, ids: str = "") -> dict[str, str]:
    """The edition's recordings folder and its receipt, alignment and transcript."""
    base = Edition(code).ear_first.relative_to(repository.ROOT).as_posix()
    suffix = f"-{ids.replace(',', '-')}" if ids else ""
    return {
        "folder": f"{base}/recordings",
        "receipt": f"{base}/narration-receipt{suffix}.json",
        "alignment": f"{base}/alignment{suffix}.json",
        "asr": f"{base}/asr{suffix}.json",
    }


def steps(code: str, ids: str = "", scope: Scope = Scope.ALL) -> list[tuple[str, list[str]]]:
    """The edition's named commands in order, each run from the repository root."""
    edition, paths = Edition(code), evidence_paths(code, ids)
    python = [sys.executable, "-B"]
    narration = [
        *python,
        "-m",
        "ddwg_film.narration.synthesis",
        "--script",
        edition.script,
        "--cast",
        edition.cast,
        "--folder",
        paths["folder"],
        "--receipt",
        paths["receipt"],
    ]
    if ids:
        narration += ["--ids", ids]
    if scope is Scope.PLAN:
        return [("narration", [*narration, "--dry-run"])]
    receipt, language = paths["receipt"], edition.language
    checks = [
        (
            "alignment",
            [
                *python,
                "-m",
                "ddwg_film.narration.alignment",
                "--model",
                ALIGNER,
                "--receipt",
                receipt,
                "--output",
                paths["alignment"],
                "--language",
                language,
            ],
        ),
        (
            "transcription",
            [
                *python,
                "-m",
                "ddwg_film.narration.transcription",
                "--receipt",
                receipt,
                "--output",
                paths["asr"],
                "--language",
                language,
            ],
        ),
    ]
    return checks if scope is Scope.CHECKS else [("narration", narration), *checks]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Narrate, align and transcribe one edition.")
    parser.add_argument("--language", choices=CODES, required=True)
    parser.add_argument("--ids", default="", help="Comma-separated segment ids")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Print the narration plan only")
    mode.add_argument(
        "--skip-generation",
        action="store_true",
        help="Align and transcribe the existing receipt",
    )
    options = parser.parse_args(argv)
    scope = Scope.ALL
    if options.dry_run:
        scope = Scope.PLAN
    elif options.skip_generation:
        scope = Scope.CHECKS
    for name, command in steps(options.language, options.ids, scope):
        started = time.monotonic()
        subprocess.run(command, cwd=repository.ROOT, check=True)
        seconds = round(time.monotonic() - started, 1)
        print(
            json.dumps({"edition": options.language, "step": name, "seconds": seconds}),
            flush=True,
        )


if __name__ == "__main__":
    main()
