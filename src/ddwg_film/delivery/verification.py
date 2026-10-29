"""Verify delivered film editions against their current authored inputs.

The checks cover the pinned canonical sources, narration custody, the rendered picture,
package bindings, complete media decoding and the recorded review thresholds.
Aesthetic judgment belongs to the review record; human listening stays separate.
The verifier reads and decodes; it writes nothing and prints each edition's report.

Usage: python -m ddwg_film.delivery.verification [--technical-only] --language zh|en|all
           <films>
"""

from __future__ import annotations

import argparse
import json
import wave
from pathlib import Path

import ddwg_film.delivery.packaging as packaging
import ddwg_film.media as media
import ddwg_film.narration.selection as narration_selection
import ddwg_film.narration.spoken_units as narration_spoken_units
import ddwg_film.narration.thought_groups as narration_thought_groups
import ddwg_film.picture.rendering as picture_rendering
import ddwg_film.production as production
import ddwg_film.repository as repository
import ddwg_film.review.record as review_record
import ddwg_film.sources as sources
import ddwg_film.specification as specification
from ddwg_film.picture.rendering import COMPOSITION_SCRIPT


class VerificationError(ValueError):
    """A delivered edition or one of its bound inputs differs from what acceptance requires."""


CREDITS_DURATION, DURATION, FPS, RATE = (
    specification.CREDITS_DURATION,
    specification.DURATION,
    specification.FPS,
    specification.RATE,
)


def bilingual_inputs(files: list[Path]) -> dict[str, list[Path]]:
    """Require both edition pairs under their current language-owned roots."""
    groups = {code: production.Edition(code).films for code in production.CODES}
    expected = {path for pair in groups.values() for path in pair}
    if len(files) != len(expected) or set(files) != expected:
        msg = "Bilingual acceptance requires both current edition pairs"
        raise VerificationError(msg)
    return groups


def verify_sources() -> dict:
    """The pinned canonical sources, checked against a local clone when one is named."""
    return sources.verify()


def verify_captions(timeline: dict, code: str) -> int:
    """Captions stay single-line, within their limit and before the credits."""
    limit, prior_end = specification.CAPTION_LIMITS[code], 0.0
    for cue in timeline["captions"]:
        display = cue.get("display_text", cue["text"])
        if not (
            0 <= cue["start"] < cue["end"] <= DURATION - CREDITS_DURATION
            and cue["start"] >= prior_end - 0.15
            and all("\n" not in v and len(v) <= limit for v in (cue["text"], display))
            and narration_spoken_units.units(display) == narration_spoken_units.units(cue["text"])
        ):
            msg = f"Caption differs from the caption contract: {cue}"
            raise VerificationError(msg)
        prior_end = cue["end"]
    return len(timeline["captions"])


def verify_narration(edition: production.Edition) -> dict:
    """Bind script, selected recordings, assembly, soundtrack and timeline."""
    script_path, cast_path = repository.ROOT / edition.script, repository.ROOT / edition.cast
    script, cast = repository.read(script_path), repository.read(cast_path)
    script_sha256 = repository.sha(script_path)
    mirror = (repository.ROOT / edition.mirror).read_text().strip()
    if mirror != "\n\n".join(segment["text"] for segment in script["segments"]):
        msg = "Narration mirror differs from the current script"
        raise VerificationError(msg)
    selected = repository.read(edition.narration_selected)
    assembly = repository.read(edition.audio_assembly)
    soundtrack = edition.soundtrack
    timeline = repository.read(edition.timeline)
    if (
        selected["script_sha256"] != script_sha256
        or selected["cast_sha256"] != repository.sha(cast_path)
        or assembly["script_sha256"] != script_sha256
        or assembly["soundtrack_sha256"] != repository.sha(soundtrack)
    ):
        msg = "Narration custody differs from the current script"
        raise VerificationError(msg)
    with wave.open(str(soundtrack)) as audio:
        shape = (audio.getnframes(), audio.getframerate(), audio.getnchannels())
    if shape != (DURATION * RATE, RATE, 2):
        msg = "Soundtrack must be exact 48 kHz stereo for the duration"
        raise VerificationError(msg)
    level, policy = assembly.get("program_level", {}), specification.PROGRAM_LEVEL
    after = level.get("after", {})
    if not (
        level.get("policy") == policy
        and abs(after.get("integrated_lufs", -99) - policy["integrated_lufs"]) <= 0.5
        and after.get("true_peak_dbtp", 99) <= policy["true_peak_ceiling_dbtp"]
    ):
        msg = "Soundtrack differs from the declared program level"
        raise VerificationError(msg)
    order = [segment["id"] for segment in script["segments"]]
    if order != [segment["id"] for segment in timeline["segments"]] or order != [
        record["id"] for record in selected["records"]
    ]:
        msg = "Script, timeline and selection differ in segment order"
        raise VerificationError(msg)
    for section, segment, record in zip(
        script["segments"], timeline["segments"], selected["records"], strict=True
    ):
        if (
            not (section["text"] == segment["text"] == record["text"])
            or repository.sha(repository.ROOT / record["path"]) != record["wav_sha256"]
        ):
            msg = f"Selected recording differs: {section['id']}"
            raise VerificationError(msg)
        narration_thought_groups.validate_group_inputs(
            record, root=repository.ROOT, section=section
        )
        narration_selection.validate_voice_record(record, cast)
    return {
        "segments": len(order),
        "captions": verify_captions(timeline, edition.code),
        "soundtrack_sha256": assembly["soundtrack_sha256"],
        "program_level": after,
    }


def verify_picture(edition: production.Edition) -> dict:
    """Bind the native render and its whole-film geometry to the staged picture."""
    render = repository.read(edition.render_receipt)
    picture_rendering.validate_picture_binding(edition, render)
    geometry = repository.read(edition.picture_geometry)
    step = geometry.get("step_frames")
    if not (
        geometry.get("format") == "picture-geometry"
        and geometry.get("passed") is True
        and geometry["findings"] == geometry["errors"] == []
        and geometry["index_sha256"] == repository.sha(edition.picture_stage / "index.html")
        and (geometry["width"], geometry["height"]) == (3840, 2160)
        and (geometry["duration"], geometry["fps"]) == (DURATION, FPS)
        and step in (1, 2)
        and geometry["checked"] == -(-DURATION * FPS // step)
    ):
        msg = "Picture geometry does not cover the current staged film"
        raise VerificationError(msg)
    plan = repository.read(edition.shot_plan)
    if (
        plan["script_sha256"] != repository.sha(repository.ROOT / edition.script)
        or plan["composition_sha256"] != repository.sha(repository.ROOT / COMPOSITION_SCRIPT)
        or plan["timeline_sha256"] != repository.sha(edition.timeline)
    ):
        msg = "Shot plan differs from the current picture inputs"
        raise VerificationError(msg)
    return {
        "picture_sha256": render["output_sha256"],
        "geometry_frames": geometry["checked"],
        "browser": geometry["browser"],
    }


def language_index() -> dict:
    """The record of the language entry page that a current viewing package holds."""
    return {
        "source": str(packaging.INDEX),
        "source_sha256": repository.sha(repository.ROOT / packaging.INDEX),
        "path": str(packaging.LANGUAGE_INDEX),
        "sha256": repository.sha(repository.ROOT / packaging.LANGUAGE_INDEX),
        "languages": list(production.CODES),
    }


def verify_package(edition: production.Edition) -> dict:
    """Bind both delivered formats and the viewing package to their inputs."""
    output = edition.artifacts
    films = repository.read(edition.film_package)
    render = repository.read(edition.render_receipt)
    names = sorted(film.name for film in edition.films)
    if (
        films["script_sha256"] != repository.sha(repository.ROOT / edition.script)
        or films["soundtrack_sha256"] != repository.sha(edition.soundtrack)
        or films["picture_sha256"] != render["output_sha256"]
        or films["cover_sha256"] != repository.sha(output / "ddwg-cover.jpg")
        or films["chapters_sha256"] != repository.sha(output / "chapters.ffmeta")
        or sorted(member["path"] for member in films["editions"]) != names
        or any(
            member["sha256"] != repository.sha(output / member["path"])
            for member in films["editions"]
        )
    ):
        msg = "Film package differs from its current inputs"
        raise VerificationError(msg)
    viewing = repository.read(edition.viewing_package)
    if [member["path"] for member in viewing["members"]] != list(
        packaging.viewing_members(edition)
    ):
        msg = "Viewing package members differ from the declared viewing members"
        raise VerificationError(msg)
    if (
        viewing["script_sha256"] != repository.sha(repository.ROOT / edition.script)
        or viewing["timeline_sha256"] != repository.sha(edition.timeline)
        or viewing["player_source_sha256"] != repository.sha(repository.ROOT / packaging.PLAYER)
        or viewing["author"] != specification.AUTHOR
        or viewing["chapters"] != packaging.CHAPTERS
        or any(
            member["sha256"] != repository.sha(output / member["path"])
            for member in viewing["members"]
        )
        or repository.sha(output / "ddwg-cover.png")
        != repository.sha(repository.ROOT / edition.cover)
    ):
        msg = "Viewing package differs from its current inputs"
        raise VerificationError(msg)
    if viewing.get("language_index") != language_index():
        msg = "Viewing package language index differs from the current entry page"
        raise VerificationError(msg)
    return {"films": names, "viewing_members": len(viewing["members"])}


def verify_media(edition: production.Edition, path: Path, size: tuple[int, int]) -> dict:
    """Decode one complete delivered movie and check its declared contract."""
    data = media.probe(path)
    try:
        video = media.require_video(
            data, frames=DURATION * FPS, fps=FPS, size=size, duration=DURATION
        )
    except media.MediaError as error:
        msg = f"Movie differs from the delivery contract: {path.name}: {error}"
        raise VerificationError(msg) from error
    audio = next((s for s in data["streams"] if s["codec_type"] == "audio"), None)
    tags = data["format"]["tags"]
    language = specification.ISO_LANGUAGES[edition.code]
    rendition = next(r for r in production.RENDITIONS.values() if (r.width, r.height) == size)
    release, names = packaging.delivered_tags(edition, rendition), packaging.track_names(edition)
    tolerance = media.DURATION_TOLERANCE
    if not (
        audio is not None
        and video.get("field_order", "progressive") in ("progressive", "unknown")
        and all(
            video.get(key) == "bt709"
            for key in ("color_primaries", "color_transfer", "color_space")
        )
        and video.get("level") == specification.H264_LEVELS[size[1]]
        and (int(audio["sample_rate"]), audio["channels"]) == (RATE, 2)
        and abs(float(audio["duration"]) - DURATION) < tolerance
        and any(s.get("disposition", {}).get("attached_pic") for s in data["streams"])
        and tags.get("artist") == specification.AUTHOR
        and tags.get("author", tags.get("com.apple.quicktime.author")) == specification.AUTHOR
        and all(tags.get(key) == release.get(key) for key in {*release, "hd_video"})
        and video.get("tags", {}).get("language") == language
        and audio.get("tags", {}).get("language") == language
        and video.get("tags", {}).get("handler_name") == names["picture"]
        and audio.get("tags", {}).get("handler_name") == names["narration"]
        and len(data["chapters"]) == packaging.CHAPTERS
    ):
        msg = f"Movie differs from the delivery contract: {path.name}"
        raise VerificationError(msg)
    media.video_cadence(path, DURATION * FPS, FPS)
    frames = media.decoded_video_frames(path, DURATION * FPS, max(300, DURATION))
    sample_frames = media.decoded_audio_frames(path)
    # AAC encoder padding is distinct from the declared sample domain.
    if abs(sample_frames - DURATION * RATE) > 1024:
        msg = f"Decoded audio length differs: {path.name}"
        raise VerificationError(msg)
    return {
        "path": str(path.relative_to(repository.ROOT)),
        "sha256": repository.sha(path),
        "bytes": path.stat().st_size,
        "dimensions": list(size),
        "video_frames": frames,
        "audio_sample_frames_decoded": sample_frames,
    }


def verify_review(edition: production.Edition, files: list[Path]) -> dict:
    """Accept only a current review of both delivered formats above threshold."""
    path = edition.production_review
    review = repository.read(path)
    covered = {item["path"]: item["sha256"] for item in review["media"]}
    current = {str(f.relative_to(repository.ROOT)): repository.sha(f) for f in files}
    if (
        review.get("schema_version") != review_record.SCHEMA_VERSION
        or review.get("language") != edition.code
        or covered != current
        or review["script_sha256"] != repository.sha(repository.ROOT / edition.script)
        or review["composition_sha256"] != repository.sha(repository.ROOT / COMPOSITION_SCRIPT)
    ):
        msg = "Review does not cover the current delivered edition"
        raise VerificationError(msg)
    scores = review["scores"]
    if set(scores) != set(review_record.DIMENSIONS):
        msg = "Review must score every declared dimension"
        raise VerificationError(msg)
    if review_record.overall(scores) != review["overall"]:
        msg = "Review overall score must be the mean of its dimensions"
        raise VerificationError(msg)
    if (
        review["overall"] < review_record.OVERALL_MINIMUM
        or min(scores.values()) < review_record.DIMENSION_MINIMUM
    ):
        msg = "Review scores are below the acceptance thresholds"
        raise VerificationError(msg)
    if any(finding["severity"] == "material" for finding in review["findings"]):
        msg = "Review records an unresolved material finding"
        raise VerificationError(msg)
    report = review["report"]
    if repository.sha(repository.ROOT / report["path"]) != report["sha256"]:
        msg = "Review report differs from its record"
        raise VerificationError(msg)
    return {
        "path": str(path.relative_to(repository.ROOT)),
        "reviewer": review["reviewer"],
        "overall": review["overall"],
        "minimum_dimension": min(scores.values()),
        "human_listening": review["human_listening"],
    }


def qualify(
    edition: production.Edition, files: list[Path], *, technical_only: bool = False
) -> dict:
    """Verify one edition's two delivered formats and their bound inputs."""
    sizes = {
        edition.film(kind).name: (rendition.width, rendition.height)
        for kind, rendition in production.RENDITIONS.items()
    }
    if sorted(path.name for path in files) != sorted(sizes) or any(
        path.parent != edition.artifacts for path in files
    ):
        msg = "An edition is verified as its two current delivered formats"
        raise VerificationError(msg)
    report = {
        "verdict": "pass",
        "scope": "technical" if technical_only else "acceptance",
        "language": edition.code,
        "sources": verify_sources(),
        "narration": verify_narration(edition),
        "picture": verify_picture(edition),
        "package": verify_package(edition),
        "media": [verify_media(edition, path, sizes[path.name]) for path in sorted(files)],
    }
    report["review"] = (
        {"verdict": "not_reviewed"} if technical_only else verify_review(edition, sorted(files))
    )
    report["limits"] = (
        "Media, source and binding checks do not certify taste; human listening "
        "is recorded by the review, not inferred from these checks."
    )
    return report


# The owners' refusals that the command reports as "<language>: <reason>"; any other exception
# keeps its traceback.
REFUSALS = (
    VerificationError,
    sources.SourceError,
    media.MediaError,
    picture_rendering.PictureError,
    narration_selection.SelectionError,
    narration_spoken_units.AlignmentError,
    narration_thought_groups.RetainedUtteranceError,
)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("files", nargs="+", type=Path)
    # The film-media gate passes this flag; the verifier never writes, with or without it.
    parser.add_argument("--read-only", action="store_true", help="accepted; nothing is written")
    parser.add_argument("--technical-only", action="store_true")
    parser.add_argument("--language", choices=(*production.CODES, "all"), required=True)
    options = parser.parse_args(argv)
    files = [path.resolve() for path in options.files]
    groups = bilingual_inputs(files) if options.language == "all" else {options.language: files}
    for language, members in groups.items():
        try:
            report = qualify(
                production.Edition(language), members, technical_only=options.technical_only
            )
        except REFUSALS as error:
            msg = f"{language}: {error}"
            raise SystemExit(msg) from None
        print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
