"""Each language edition's sources and the places of its media and evidence.

Every action takes the edition it produces as an argument; nothing holds a current edition.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import filmkit.repository as repository

if TYPE_CHECKING:
    from pathlib import Path


# The language editions, Chinese first.
CODES = ("zh", "en")


@dataclass(frozen=True)
class Rendition:
    """A delivered film's frame size, whether it re-encodes the rendered picture, and how.

    `decoding` holds the FFmpeg options before the picture input and `video` those of the video
    stream. Packaging allows the encode `deadline_ratio` seconds per second of film, and never
    less than its own floor.
    """

    width: int
    height: int
    reencoded: bool
    decoding: tuple[str, ...] = ()
    video: tuple[str, ...] = ("-c:v:0", "copy")
    deadline_ratio: int = 0


# Each edition's delivered films by kind: the UHD master copies the rendered picture stream
# and the 1080p viewing film re-encodes it, decoded and scaled through VideoToolbox. Both show
# the captions the picture draws.
RENDITIONS = {
    "uhd": Rendition(3840, 2160, reencoded=False),
    "1080p-captioned": Rendition(
        1920,
        1080,
        reencoded=True,
        decoding=("-hwaccel", "videotoolbox", "-hwaccel_output_format", "videotoolbox_vld"),
        video=(
            "-filter:v:0",
            "scale_vt=w=1920:h=1080",
            "-c:v:0",
            "h264_videotoolbox",
            "-b:v:0",
            "10M",
        ),
        deadline_ratio=2,
    ),
}


@dataclass(frozen=True)
class Edition:
    """Keep language-specific source, timing, media and evidence together."""

    code: str

    def __post_init__(self) -> None:
        if self.code not in CODES:
            message = "An edition must be zh or en"
            raise ValueError(message)

    @property
    def language(self) -> str:
        return "Chinese" if self.code == "zh" else "English"

    @property
    def sources(self) -> str:
        """The folder of the edition's script, cast, narration mirror and shot plan."""
        return "content" if self.code == "zh" else "content/en"

    @property
    def script(self) -> str:
        return f"{self.sources}/film-script.json"

    @property
    def cast(self) -> str:
        return f"{self.sources}/voice-reference.json"

    @property
    def shot_plan(self) -> str:
        """The shot plan that every render writes from the script, composition and timeline."""
        return f"{self.sources}/shot-plan.json"

    @property
    def mirror(self) -> str:
        """The narration text, which equals the script's segment texts joined by blank lines."""
        return f"{self.sources}/narration.md"

    @property
    def cover(self) -> str:
        return (
            "assets/cover/ddwg-cover.png" if self.code == "zh" else "assets/cover/ddwg-cover-en.png"
        )

    @property
    def artifacts(self) -> Path:
        return repository.ROOT / "build/artifacts/film" / self.code

    @property
    def evidence(self) -> Path:
        return repository.ROOT / "build/evidence/editions" / self.code

    @property
    def picture_stage(self) -> Path:
        return repository.ROOT / "build/runtime/work" / f"final-delivery-{self.code}-uhd"

    @property
    def prefix(self) -> str:
        return f"ddwg-{self.code}"

    @property
    def timeline(self) -> Path:
        """The assembled timeline: segment times, thought pauses, words and captions."""
        return self.artifacts / "timeline.json"

    @property
    def soundtrack(self) -> Path:
        """The assembled narration at program level, the films' only audio."""
        return self.artifacts / f"{self.prefix}-narration.wav"

    @property
    def picture(self) -> Path:
        """The rendered picture, before the soundtrack, cover and metadata join it."""
        return self.artifacts / "ddwg-final-picture.mp4"

    def film(self, kind: str) -> Path:
        """A delivered film by its kind in `RENDITIONS`."""
        return self.artifacts / f"{self.prefix}-{kind}.mp4"

    @property
    def films(self) -> list[Path]:
        """The delivered films in `RENDITIONS` order: the UHD master, then the viewing film."""
        return [self.film(kind) for kind in RENDITIONS]

    @property
    def ear_first(self) -> Path:
        """The narration's recordings and their receipt, alignment and transcript."""
        return self.evidence / "ear-first"

    @property
    def narration_selected(self) -> Path:
        return self.evidence / "narration-selected.json"

    @property
    def alignment_selected(self) -> Path:
        return self.evidence / "alignment-selected.json"

    @property
    def audio_assembly(self) -> Path:
        return self.evidence / "audio-assembly.json"

    @property
    def render_receipt(self) -> Path:
        return self.evidence / "render/receipt.json"

    @property
    def picture_geometry(self) -> Path:
        return self.evidence / "picture-geometry.json"

    @property
    def picture_sync(self) -> Path:
        return self.evidence / "picture-sync.json"

    @property
    def film_package(self) -> Path:
        return self.evidence / "film-package.json"

    @property
    def viewing_package(self) -> Path:
        return self.evidence / "viewing-package.json"

    @property
    def production_review(self) -> Path:
        """The tracked production review that the film verifier reads."""
        folder = "evidence/reviews" if self.code == "zh" else "evidence/reviews/en"
        return repository.ROOT / folder / "production-review.json"

    @property
    def release(self) -> dict:
        """The release metadata the edition's script declares for its films."""
        return repository.read(self.script)["release"]

    @property
    def comment(self) -> str:
        return self.release["comment"]

    @property
    def description(self) -> str:
        return self.release["description"]
