"""Compare a rebuild with the published release under the reproduction standard.

The published assets lie in build/artifacts/release under the names that the release manifest
content/release.json records with each asset's size and SHA-256; an asset that differs from
the manifest refuses the comparison before any layer is compared. Each edition's soundtrack and
staged picture document must hold the bytes the manifest records, its captions, transcript and
cover the published bytes, and its published review must bind the published films and the
current script and composition. Each rebuilt film must have its published film's frame count,
decoded audio, streams, chapters and tags, and every decoded frame's PSNR against it at or
above the floor that the manifest records. Without a floor the comparison reports the lowest
frames, so that they can be inspected and the floor recorded, and does not pass.

The report goes to build/evidence/reproduction/report.json unless --read-only is given; a
comparison that does not pass exits with "<edition>: <asset>: <layer>" for each failing layer.

Usage: python -m filmkit.delivery.reproduction [--read-only]
"""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Annotated

from pydantic import Field, NonNegativeInt, PositiveFloat, StringConstraints, ValidationError

import filmkit.delivery.packaging as packaging
import filmkit.delivery.verification as verification
import filmkit.media as media
import filmkit.production as production
import filmkit.repository as repository
from filmkit.film import Declared

MANIFEST = Path("content/release.json")
RELEASE = Path("build/artifacts/release")
REPORT = Path("build/evidence/reproduction/report.json")
CHECKSUMS = "SHA256SUMS"
# Seconds one decode of a film pair may take.
DECODE_DEADLINE = 7200
# How many of the lowest frames a film's comparison reports.
LOWEST = 10

Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
AssetName = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")]


class ReproductionError(ValueError):
    """The release manifest or a published asset differs from what the comparison requires."""


class Asset(Declared):
    """A published asset: its name in the release and its exact bytes."""

    name: AssetName
    bytes: NonNegativeInt
    sha256: Digest


class EditionRecord(Declared):
    """What an edition's published films were made from, and each film's PSNR floor."""

    soundtrack_sha256: Digest
    stage_sha256: Digest
    picture_floor_db: dict[AssetName, PositiveFloat] = Field(default_factory=dict)


class Release(Declared):
    """The release manifest: the version, each edition's record and every published asset."""

    version: Annotated[str, StringConstraints(pattern=r"^\d+\.\d+\.\d+$")]
    editions: dict[str, EditionRecord]
    assets: tuple[Asset, ...] = Field(min_length=1)


def members(edition: production.Edition) -> dict[str, tuple[str, Path]]:
    """Each asset an edition publishes, by its release name: its layer and the build file."""
    prefix, review = edition.prefix, edition.production_review
    return {
        **{film.name: ("film", film) for film in edition.films},
        **{
            f"{prefix}{suffix}": ("document", edition.artifacts / f"{prefix}{suffix}")
            for suffix in (".srt", ".vtt", "-transcript.md")
        },
        f"{prefix}-cover.png": ("document", edition.artifacts / packaging.COVER_PNG),
        f"{prefix}-production-review.json": ("review", review),
        f"{prefix}-production-review.md": ("review", review.with_suffix(".md")),
    }


def checksums(release: Release) -> str:
    """The release's SHA256SUMS: every other asset's SHA-256 and name, as shasum writes them."""
    listed = sorted((a.name, a.sha256) for a in release.assets if a.name != CHECKSUMS)
    return "".join(f"{digest}  {name}\n" for name, digest in listed)


def load() -> Release:
    """The release manifest, refused unless it records exactly what the editions publish."""
    try:
        release = Release.model_validate_json((repository.ROOT / MANIFEST).read_bytes())
    except ValidationError as error:
        msg = f"{MANIFEST} is not a release manifest: {error}"
        raise ReproductionError(msg) from None
    if set(release.editions) != set(production.CODES):
        msg = f"{MANIFEST} records the editions {sorted(release.editions)}"
        raise ReproductionError(msg)
    published = [name for code in production.CODES for name in members(production.Edition(code))]
    names = [asset.name for asset in release.assets]
    if len(set(names)) != len(names) or sorted(names) != sorted([*published, CHECKSUMS]):
        msg = f"{MANIFEST} does not name every published asset of the editions, each once"
        raise ReproductionError(msg)
    for code, record in release.editions.items():
        films = {film.name for film in production.Edition(code).films}
        if not set(record.picture_floor_db) <= films:
            msg = f"{MANIFEST} records a floor for an asset that is not a film of {code}"
            raise ReproductionError(msg)
    listed = next(asset for asset in release.assets if asset.name == CHECKSUMS)
    if listed.sha256 != repository.content_sha(checksums(release)):
        msg = f"{MANIFEST}: {CHECKSUMS} differs from the assets it lists"
        raise ReproductionError(msg)
    return release


def published(release: Release) -> dict[str, Path]:
    """Each published asset, refused unless it holds the bytes the manifest records."""
    folder, found = repository.ROOT / RELEASE, {}
    for asset in release.assets:
        path = folder / asset.name
        if (
            not path.is_file()
            or path.stat().st_size != asset.bytes
            or repository.sha(path) != asset.sha256
        ):
            msg = f"The published asset differs from the release manifest: {asset.name}"
            raise ReproductionError(msg)
        found[asset.name] = path
    return found


def recorded(path: Path, digest: str) -> dict:
    """A rebuilt file that must hold recorded bytes."""
    current = repository.sha(path) if path.is_file() else None
    return {
        "path": repository.relative(path),
        "sha256": current,
        "verdict": "pass" if current == digest else "fail",
    }


def identical(name: str, rebuilt: Path, published: Path) -> dict:
    """A rebuilt document that must hold its published asset's bytes."""
    same = rebuilt.is_file() and repository.sha(rebuilt) == repository.sha(published)
    return {"asset": name, "verdict": "pass" if same else "fail"}


def review(edition: production.Edition, assets: dict[str, Path]) -> dict:
    """The edition's published review, which must bind its published films and sources."""
    films = [assets[film.name] for film in edition.films]
    record = assets[f"{edition.prefix}-production-review.json"]
    try:
        accepted = verification.verify_review(edition, films, record=record)
    except verification.VerificationError as error:
        return {"verdict": "fail", "reason": str(error)}
    return {"verdict": "pass", **accepted}


def frame_psnr(rebuilt: Path, published: Path) -> list[float]:
    """Each decoded frame's PSNR between two films' pictures, infinite where they are equal."""
    stats = repository.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-nostdin",
            "-i",
            str(rebuilt),
            "-i",
            str(published),
            "-lavfi",
            "[0:v:0][1:v:0]psnr=stats_file=-",
            "-f",
            "null",
            "-",
        ],
        timeout=DECODE_DEADLINE,
    ).stdout.decode()
    return [float(value) for value in re.findall(r"psnr_avg:(\S+)", stats)]


def decoded_audio(path: Path) -> str:
    """The SHA-256 of a film's first audio stream, decoded."""
    hashed = repository.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-nostdin",
            "-i",
            str(path),
            "-map",
            "0:a:0",
            "-f",
            "hash",
            "-hash",
            "sha256",
            "-",
        ],
        timeout=DECODE_DEADLINE,
    ).stdout.decode()
    return hashed.strip().removeprefix("SHA256=")


def container(path: Path) -> dict:
    """A film's streams, duration, chapters and tags, apart from encoder labels."""
    data = media.probe(path)
    keys = ("codec_type", "codec_name", "width", "height", "sample_rate", "channels", "nb_frames")
    return {
        "streams": [
            {key: stream.get(key) for key in keys}
            | {
                "cover": bool(stream.get("disposition", {}).get("attached_pic")),
                "tags": {
                    key: value
                    for key, value in stream.get("tags", {}).items()
                    if key in ("language", "handler_name")
                },
            }
            for stream in data["streams"]
        ],
        "duration": data["format"].get("duration"),
        "chapters": [
            (chapter["start_time"], chapter["end_time"], chapter.get("tags", {}).get("title"))
            for chapter in data.get("chapters", [])
        ],
        "tags": {k: v for k, v in data["format"].get("tags", {}).items() if k != "encoder"},
    }


def film(name: str, rebuilt: Path, published: Path, floor: float | None) -> dict:
    """A rebuilt film against its published film: frames, audio, container and picture."""
    if not rebuilt.is_file():
        return {"asset": name, "verdict": "fail", "failing": ["missing"]}
    frames = media.video_stream(media.probe(published)).get("nb_frames")
    psnr = frame_psnr(rebuilt, published)
    finite = sorted((value, index) for index, value in enumerate(psnr) if math.isfinite(value))
    below = [index for index, value in enumerate(psnr) if floor is not None and value < floor]
    result = {
        "asset": name,
        "frames": len(psnr),
        "audio": "identical" if decoded_audio(rebuilt) == decoded_audio(published) else "differs",
        "container": "identical" if container(rebuilt) == container(published) else "differs",
        "psnr": {
            "floor_db": floor,
            "identical_frames": len(psnr) - len(finite),
            "minimum_db": finite[0][0] if finite else None,
            "mean_db": sum(value for value, _ in finite) / len(finite) if finite else None,
            "lowest": [{"frame": index, "psnr_db": value} for value, index in finite[:LOWEST]],
            "below_floor": below[:LOWEST],
        },
    }
    failing = [
        layer
        for layer, held in (
            ("frames", str(len(psnr)) == str(frames)),
            ("audio", result["audio"] == "identical"),
            ("container", result["container"] == "identical"),
            ("picture", not below),
        )
        if not held
    ]
    result["failing"] = failing
    result["verdict"] = "fail" if failing else "calibrating" if floor is None else "pass"
    return result


def compare_edition(edition: production.Edition, record: EditionRecord, assets: dict) -> dict:
    """One edition's every layer against its published assets and its manifest record."""
    layers = members(edition)
    return {
        "soundtrack": recorded(edition.soundtrack, record.soundtrack_sha256),
        "stage": recorded(edition.picture_stage / "index.html", record.stage_sha256),
        "review": review(edition, assets),
        "documents": [
            identical(name, source, assets[name])
            for name, (layer, source) in layers.items()
            if layer == "document"
        ],
        "films": [
            film(name, source, assets[name], record.picture_floor_db.get(name))
            for name, (layer, source) in layers.items()
            if layer == "film"
        ],
    }


def failures(report: dict) -> list[str]:
    """Each failing layer as "<edition>: <layer>" or "<edition>: <asset>: <layer>"."""
    found = []
    for code, edition in report["editions"].items():
        found += [
            f"{code}: {layer}"
            for layer in ("soundtrack", "stage", "review")
            if edition[layer]["verdict"] == "fail"
        ]
        found += [
            f"{code}: {document['asset']}: documents"
            for document in edition["documents"]
            if document["verdict"] == "fail"
        ]
        for result in edition["films"]:
            found += [f"{code}: {result['asset']}: {layer}" for layer in result["failing"]]
    return found


def compare() -> dict:
    """The comparison of the rebuild with the published release, every layer reported."""
    release = load()
    assets = published(release)
    report = {
        "release": release.version,
        "ffmpeg": repository.run(["ffmpeg", "-version"]).stdout.decode().splitlines()[0],
        "editions": {
            code: compare_edition(production.Edition(code), release.editions[code], assets)
            for code in production.CODES
        },
    }
    verdicts = [
        result["verdict"] for edition in report["editions"].values() for result in edition["films"]
    ]
    report["verdict"] = (
        "fail" if failures(report) else "calibrating" if "calibrating" in verdicts else "pass"
    )
    return report


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--read-only", action="store_true", help="print the report only")
    options = parser.parse_args(argv)
    try:
        report = compare()
    except ReproductionError as error:
        raise SystemExit(str(error)) from None
    if not options.read_only:
        repository.write(REPORT, report)
    print(json.dumps({"verdict": report["verdict"], "release": report["release"]}))
    if report["verdict"] == "calibrating":
        msg = "The comparison is calibrating: inspect each film's lowest frames, record its floor"
        raise SystemExit(msg)
    if report["verdict"] != "pass":
        raise SystemExit("\n".join(failures(report)))


if __name__ == "__main__":
    main()
