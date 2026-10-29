"""The film the engine builds: its declaration in `content/film.toml`, checked before any work.

The engine takes every film-specific value from this declaration and the files it names; each
edition's script declares the edition's title, author, language, duration, frame rate and
chapters. A declaration that is malformed, incomplete or names a missing file is refused with
each failing field.
"""

from __future__ import annotations

import tomllib
from typing import TYPE_CHECKING, Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

import filmkit.repository as repository

if TYPE_CHECKING:
    from pathlib import Path

DECLARATION = "content/film.toml"
# The files every edition's sources folder holds.
EDITION_FILES = ("film-script.json", "voice-reference.json", "player.html")
# A lowercase name of words joined by hyphens.
Name = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")]
Floor = Annotated[int, Field(ge=0, le=100)]


class FilmError(ValueError):
    """The film declaration is missing, invalid or names a missing file."""


class Declared(BaseModel):
    """A declared table: every field is known, and none changes after loading."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class EditionDeclaration(Declared):
    """One edition's folder of script, cast and player, its cover, and its caption terms."""

    sources: str
    cover: str
    caption_terms: tuple[str, ...] = ()


class Review(Declared):
    """The reviewer prompt, the verifier's floors and the scored dimensions in record order."""

    prompt: str
    overall_minimum: Floor
    dimension_minimum: Floor
    dimensions: dict[str, str] = Field(min_length=1)


class Film(Declared):
    """A bilingual film: its file prefix, delivery folder, entry page, sources and review."""

    slug: Name
    documents_folder: Name
    entry: str
    source_manifest: str
    editions: dict[Literal["zh", "en"], EditionDeclaration] = Field(min_length=2)
    review: Review


def named_files(film: Film) -> list[tuple[str, str]]:
    """Each file the declaration names, with the field that names it."""
    named = [
        ("entry", film.entry),
        ("source_manifest", film.source_manifest),
        ("review.prompt", film.review.prompt),
    ]
    for code, edition in film.editions.items():
        field = f"editions.{code}.sources"
        named += [(field, f"{edition.sources}/{name}") for name in EDITION_FILES]
        named.append((f"editions.{code}.cover", edition.cover))
    return named


def load(root: Path) -> Film:
    """Read and check the declaration below a root, refusing it with each failing field."""
    try:
        film = Film.model_validate(tomllib.loads((root / DECLARATION).read_text(encoding="utf-8")))
    except (OSError, tomllib.TOMLDecodeError, ValidationError) as error:
        message = f"{DECLARATION} is not a film declaration: {error}"
        raise FilmError(message) from error
    named = named_files(film)
    missing = [f"{field}: {path}" for field, path in named if not (root / path).is_file()]
    if missing:
        message = f"{DECLARATION} names missing files: {'; '.join(missing)}"
        raise FilmError(message)
    return film


FILM = load(repository.ROOT)
