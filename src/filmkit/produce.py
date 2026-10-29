"""The production command: one production action for an edition.

Each action belongs to its owning module, which derives its media and receipts from the
current production contract; the command parses the options and calls that owner. Every
action needs --language.
A refusal by an action's owner exits with status 1 and "<action>: <reason>" on standard
error. The command owns no goal, approval, repository
lifecycle, service or task state.

Usage: python -m filmkit.produce <edition action> --language zh|en [options]
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import TYPE_CHECKING

from filmkit.captions import CaptionError
from filmkit.captions.refresh import refresh_captions
from filmkit.delivery.packaging import PackagingError, package_film, package_metadata
from filmkit.media import MediaError
from filmkit.narration.selection import SelectionError, select
from filmkit.narration.spoken_units import AlignmentError
from filmkit.narration.thought_groups import RetainedUtteranceError
from filmkit.picture.rendering import (
    PictureError,
    render_picture,
    stage_picture,
    validate_picture,
)
from filmkit.production import CODES, Edition
from filmkit.soundtrack.assembly import AssemblyError, assemble
from filmkit.soundtrack.level import LevelError
from filmkit.soundtrack.pauses import PauseError
from filmkit.soundtrack.policy import PausePolicyError
from filmkit.specification import DURATION

if TYPE_CHECKING:
    from collections.abc import Callable


# Each edition action's adapter from the parsed options to its owner. The adapters name their
# owners when they run, so a test can replace an owner.
EDITION_ACTIONS: dict[str, Callable[[Edition, argparse.Namespace], object]] = {
    "select": lambda edition, _: select(edition),
    "assemble": lambda edition, _: assemble(edition),
    "refresh-captions": lambda edition, _: refresh_captions(edition),
    "stage-picture": lambda edition, options: stage_picture(
        edition, options.output, options.duration, options.width, options.height, options.start
    ),
    "render-picture": lambda edition, options: render_picture(edition, options.deadline),
    "package-metadata": lambda edition, _: package_metadata(edition),
    "validate-picture": lambda edition, _: validate_picture(edition),
    "package-film": lambda edition, _: package_film(edition),
}
# The refusals of the actions' owners, which end the command with the action's name and the
# reason; any other exception keeps its traceback.
REFUSALS = (
    SelectionError,
    RetainedUtteranceError,
    AlignmentError,
    AssemblyError,
    PausePolicyError,
    PauseError,
    LevelError,
    CaptionError,
    PictureError,
    MediaError,
    PackagingError,
)


def arguments() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("action", choices=[*EDITION_ACTIONS])
    parser.add_argument("--duration", type=int, default=DURATION)
    parser.add_argument("--start", type=float, default=0)
    parser.add_argument("--width", type=int, default=3840)
    parser.add_argument("--height", type=int, default=2160)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--language", choices=CODES, help="the edition of an edition action")
    parser.add_argument("--deadline", type=int, default=10800)
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = arguments()
    options = parser.parse_args(argv)
    if options.language is None:
        parser.error("the following arguments are required: --language")
    try:
        EDITION_ACTIONS[options.action](Edition(options.language), options)
    except REFUSALS as error:
        msg = f"{options.action}: {error}"
        raise SystemExit(msg) from None


if __name__ == "__main__":
    main()
