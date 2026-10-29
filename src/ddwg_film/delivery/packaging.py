"""Package each edition's metadata, player and delivered films.

`package_metadata` derives the viewing package: the cover as PNG and JPEG, the subtitles,
transcript and chapters, the localized player and the language entry page, each recorded with
its SHA-256 in the edition's viewing package. `package_film` muxes the rendered picture with the
soundtrack and chapters into every rendition in `production.RENDITIONS`, attaches the cover and
the QuickTime keys in the packaging work folder, checks the finished film and only then links it
into place, recording its SHA-256 and commands in the edition's film package.

A film's release metadata comes from its script's "release": FFmpeg writes it as the iTunes
item list (title, artist, collection, genre, year, comments, synopsis, copyright and media
kind) and names each track, and ExifTool adds the same facts as QuickTime keys with the
keywords and creation date, so both kinds of player read them. FFmpeg's MP4 muxer tags its
chapter text track English whatever the film's language; that tag is not settable.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from datetime import UTC, datetime
from html import escape
from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image

import ddwg_film.media as media
import ddwg_film.repository as repository
from ddwg_film.picture.rendering import COMPOSITION_SCRIPT, validate_picture
from ddwg_film.production import CODES, RENDITIONS
from ddwg_film.repository import read, run, sha, write
from ddwg_film.specification import AUTHOR, DURATION, FPS, H264_LEVELS, ISO_LANGUAGES, RATE

if TYPE_CHECKING:
    from ddwg_film.production import Edition, Rendition


class PackagingError(ValueError):
    """A package input or a finished film differs from what packaging requires."""


# The delivered player and the delivery folder's index page, as paths below the repository root.
PLAYER = Path(__file__).with_name("player.html").relative_to(repository.ROOT)
INDEX = Path(__file__).with_name("index.html").relative_to(repository.ROOT)
# The language entry page derived from INDEX, below the root.
LANGUAGE_INDEX = Path("build/artifacts/film/index.html")
# The folder below the root where each edition's films are encoded and finished.
WORK = Path("build/runtime/work/final-film-packaging")
# What a failed or timed-out encode was bound to, in the edition's evidence folder.
FAILURE_RECEIPT = "packaging-failure.json"
# Every film and player has this many chapters.
CHAPTERS = 8
CAPTION_OWNER = "Already drawn in source picture; no duplicate burn-in"
# No encode's deadline is shorter, in seconds.
DEADLINE_FLOOR = 600
# The English player's text for each Chinese text of the player template, in replacement order.
ENGLISH_PLAYER = {
    'lang="zh-CN"': 'lang="en"',
    "DDWG · 数据部门工作指南": "DDWG · Data Department Work Guidelines",
    "中文 · /*RUNTIME*/": "English · /*RUNTIME*/",
    "ddwg-zh": "ddwg-en",
    "视频版本": "Video versions",
    "观看版 · 1080p": "Viewing edition · 1080p",
    "章节": "Chapters",
    (
        "从判断、数据与交付，讲到人与智能体协作、沟通和持续改进。"
        "片中情境用于解释工作机制，未据此声称实际部署或团队采用。"
    ): (
        "From judgment, data and delivery to human–Agent collaboration, "
        "communication and continuous improvement. Situations illustrate "
        "mechanisms; they do not establish deployment or team adoption."
    ),
    "完整讲稿": "Transcript",
    "讲稿 Markdown": "Transcript (Markdown)",
    "字幕": "Captions",
    "封面": "Cover",
    "下载观看版": "Download viewing edition",
    "下载 4K UHD": "Download 4K UHD",
    "此浏览器无法播放当前编码，可下载视频后使用系统播放器。": (
        "This browser cannot play the current codec. Download the video and use your system player."
    ),
}
# Han characters and CJK or full-width punctuation, none of which the English player keeps.
CHINESE = re.compile(r"[\u3000-\u303f\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff00-\uffef]")


def runtime_label() -> str:
    """The films' running time as the player and the entry page show it, minutes:seconds."""
    minutes, seconds = divmod(DURATION, 60)
    return f"{minutes:02d}:{seconds:02d}"


def viewing_members(edition: Edition) -> tuple[str, ...]:
    """The viewing package's members in record order, by name in the edition's folder."""
    return (
        "ddwg-cover.png",
        "ddwg-cover.jpg",
        f"{edition.prefix}.srt",
        f"{edition.prefix}.vtt",
        f"{edition.prefix}-transcript.md",
        "chapters.json",
        "chapters.ffmeta",
        "index.html",
    )


def package_language_index() -> dict:
    """Derive one neutral entry point for the sibling language deliveries."""
    source = repository.ROOT / INDEX
    destination = repository.ROOT / LANGUAGE_INDEX
    template = source.read_text()
    for code in CODES:
        if f'href="{code}/index.html"' not in template:
            msg = "Delivery entry needs both sibling language links"
            raise PackagingError(msg)
    if "<base " in template:
        msg = "Delivery entry must not select a language through base"
        raise PackagingError(msg)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(template.replace("/*RUNTIME*/", runtime_label()))
    return {
        "source": str(INDEX),
        "source_sha256": sha(source),
        "path": str(LANGUAGE_INDEX),
        "sha256": sha(destination),
        "languages": list(CODES),
    }


def transcript_html(transcript: str) -> str:
    """Render the generated transcript for the player.

    Chapter headings, timed segment headings and paragraphs are kept; the page
    title and the byline that follows it are left to the page.
    """
    blocks = [block.strip() for block in transcript.split("\n\n") if block.strip()]
    parts = []
    for index, block in enumerate(blocks):
        if block.startswith("# ") or (index and blocks[index - 1].startswith("# ")):
            continue
        if block.startswith("## "):
            parts.append(f"<h2>{escape(block[3:])}</h2>")
        elif re.match(r"\d{2}:\d{2}:\d{2}\.\d{3} · ", block):
            parts.append(f"<h3>{escape(block)}</h3>")
        else:
            parts.append(f"<p>{escape(block)}</p>")
    return "".join(parts)


def localize_player(player: str, code: str) -> str:
    """The player in the edition's language; the template is the Chinese player.

    Every text the English player translates must be in the template, and no Chinese text
    may remain in it.
    """
    if code == "zh":
        return player
    for original, translated in ENGLISH_PLAYER.items():
        if original not in player:
            msg = f"The player template lacks a text the English player translates: {original}"
            raise PackagingError(msg)
        player = player.replace(original, translated)
    remaining = CHINESE.findall(player)
    if remaining:
        msg = f"The English player keeps Chinese text: {''.join(remaining)}"
        raise PackagingError(msg)
    return player


def refresh_shot_plan(edition: Edition, timeline: dict) -> None:
    """Derive scene bindings without assigning capture or artistic acceptance."""
    source = read(edition.script)
    scenes = source["segments"]
    segments = timeline["segments"]
    if len(scenes) != len(segments) or len({s["id"] for s in scenes}) != len(scenes):
        msg = "Shot plan requires the complete unique scene sequence"
        raise PackagingError(msg)
    shots = []
    identity = ("id", "title", "text", "source_sections")
    for scene, segment in zip(scenes, segments, strict=True):
        if any(scene[key] != segment[key] for key in identity):
            msg = "Shot plan timeline differs from the current script"
            raise PackagingError(msg)
        shots.append(
            {
                **{key: scene[key] for key in identity if key != "text"},
                **{
                    key: segment[key]
                    for key in ("start", "end", "voice_start", "voice_end", "gap_kind")
                },
                "script_text_sha256": repository.content_sha(scene["text"]),
                "caption_count": sum(cue["segment"] == scene["id"] for cue in timeline["captions"]),
            }
        )
    write(
        edition.shot_plan,
        {
            "schema_version": 1,
            "language": edition.code,
            "duration": DURATION,
            "fps": FPS,
            "script_sha256": sha(edition.script),
            "composition_sha256": sha(COMPOSITION_SCRIPT),
            "timeline_sha256": sha(edition.timeline),
            "composition_owner": str(COMPOSITION_SCRIPT),
            "motion_grammar": (
                "One dark 2D field; each scene shows its subject as objects, "
                "processes and relations that change on spoken words, with "
                "minimal attached labels."
            ),
            "binding_scope": (
                "Current source and timing projection; capture, audiovisual "
                "quality and artistic acceptance are checked separately."
            ),
            "shots": shots,
        },
    )


def player_page(edition: Edition, chapters: list[dict]) -> str:
    """The edition's player: the localized template with its chapters, transcript and runtime."""
    player = (repository.ROOT / PLAYER).read_text()
    if "/*CHAPTERS*/[]" not in player:
        msg = "The player template lacks its chapter list"
        raise PackagingError(msg)
    player = player.replace("/*CHAPTERS*/[]", json.dumps(chapters, ensure_ascii=False))
    player = localize_player(player, edition.code)
    if player.count("/*TRANSCRIPT*/") != 1:
        msg = "The player template needs exactly one transcript place"
        raise PackagingError(msg)
    player = player.replace(
        "/*TRANSCRIPT*/",
        transcript_html((edition.artifacts / f"{edition.prefix}-transcript.md").read_text()),
    )
    return player.replace("/*RUNTIME*/", runtime_label())


def package_metadata(edition: Edition) -> None:
    """Derive the viewing package from the current source-bound timeline."""
    output = edition.artifacts
    source_cover = repository.ROOT / edition.cover
    target_cover = output / "ddwg-cover.png"
    if not target_cover.exists() or sha(target_cover) != sha(source_cover):
        shutil.copy2(source_cover, target_cover)
    timeline = read(edition.timeline)
    if (timeline["duration"], timeline["fps"]) != (DURATION, FPS):
        msg = f"The timeline must last {DURATION} s at {FPS} fps"
        raise PackagingError(msg)
    refresh_shot_plan(edition, timeline)
    chapters = read(output / "chapters.json")["chapters"]
    if len(chapters) != CHAPTERS:
        msg = f"The films have {CHAPTERS} chapters, not {len(chapters)}"
        raise PackagingError(msg)
    (output / "index.html").write_text(player_page(edition, chapters))
    language_index = package_language_index()
    with Image.open(output / "ddwg-cover.png") as cover:
        if cover.width * 9 != cover.height * 16:
            msg = f"The cover must be 16:9, not {cover.width}x{cover.height}"
            raise PackagingError(msg)
        cover.convert("RGB").save(output / "ddwg-cover.jpg", quality=95)
    members = viewing_members(edition)
    write(
        edition.viewing_package,
        {
            "script_sha256": sha(edition.script),
            "timeline_sha256": sha(edition.timeline),
            "player_source_sha256": sha(PLAYER),
            "language_index": language_index,
            "author": AUTHOR,
            "chapters": CHAPTERS,
            "members": [{"path": name, "sha256": sha(output / name)} for name in members],
            "scope": "Metadata and player derivation; actual playback checked separately",
        },
    )
    print(json.dumps({"package": str(output), "members": members}), flush=True)


def film_bindings(edition: Edition) -> dict:
    """The production inputs of both delivered films, by SHA-256, in record order."""
    return {
        "picture_sha256": sha(edition.picture),
        "soundtrack_sha256": sha(edition.soundtrack),
        "cover_sha256": sha(edition.artifacts / "ddwg-cover.jpg"),
        "script_sha256": sha(edition.script),
        "chapters_sha256": sha(edition.artifacts / "chapters.ffmeta"),
    }


def resume_package(edition: Edition) -> dict:
    """The edition's film package: the recorded one when it binds the current inputs, else new."""
    package = {**film_bindings(edition), "editions": [], "caption_owner": CAPTION_OWNER}
    if edition.film_package.exists():
        previous = read(edition.film_package)
        if any(previous.get(key) != value for key, value in package.items() if key != "editions"):
            msg = "Existing package is bound to different production inputs"
            raise PackagingError(msg)
        package["editions"] = previous["editions"]
    return package


def video_tags(rendition: Rendition) -> str:
    """The H.264 bitstream tags: BT.709 colour and limited range, and the level for 60 fps.

    The tags spare players a guess; at the rendition's height, every other limit of that level
    is at least that of the encoder's lower default.
    """
    return (
        "h264_metadata=colour_primaries=1:transfer_characteristics=1"
        ":matrix_coefficients=1:video_full_range_flag=0"
        f":level={H264_LEVELS[rendition.height] / 10}"
    )


def release_tags(edition: Edition, rendition: Rendition) -> list[tuple[str, str]]:
    """The film's global tags in command order, as FFmpeg names them for the iTunes item list.

    A media type of 9 marks a movie; the 1080p film is also marked as HD video of 1080 lines.
    """
    script = read(edition.script)
    release = script["release"]
    tags = [
        ("title", script["title"]),
        ("artist", AUTHOR),
        ("album_artist", AUTHOR),
        ("album", release["collection"]),
        ("genre", release["genre"]),
        ("date", str(release["year"])),
        ("comment", release["comment"]),
        ("description", release["description"]),
        ("synopsis", release["synopsis"]),
        ("copyright", f"© {release['year']} {AUTHOR}"),
        ("media_type", "9"),
    ]
    return [*tags, ("hd_video", "2")] if rendition.height == 1080 else tags


def track_names(edition: Edition) -> dict[str, str]:
    """The names of the film's picture and narration tracks."""
    return dict(read(edition.script)["release"]["tracks"])


def quicktime_keys(edition: Edition) -> dict[str, str]:
    """The QuickTime keys ExifTool writes, by ExifTool tag name, without the creation date."""
    script = read(edition.script)
    release = script["release"]
    return {
        "Author": AUTHOR,
        "Title": script["title"],
        "Artist": AUTHOR,
        "Album": release["collection"],
        "Genre": release["genre"],
        "Description": release["description"],
        "Comment": release["comment"],
        "Copyright": f"© {release['year']} {AUTHOR}",
        "Keywords": ", ".join(release["keywords"]),
        "Year": str(release["year"]),
    }


def delivered_tags(edition: Edition, rendition: Rendition) -> dict[str, str]:
    """The global tags FFprobe reads from a finished film: its item list and QuickTime keys."""
    keys = {
        f"com.apple.quicktime.{key.lower()}": value
        for key, value in quicktime_keys(edition).items()
    }
    return {**dict(release_tags(edition, rendition)), **keys}


def encode_command(
    edition: Edition, rendition: Rendition, intermediate: Path, created_at: str
) -> list[str]:
    """The FFmpeg command that muxes the picture, soundtrack and chapters into one rendition."""
    language, names = ISO_LANGUAGES[edition.code], track_names(edition)
    tags = [
        *(f"{key}={value}" for key, value in release_tags(edition, rendition)),
        f"creation_time={created_at}",
    ]
    return [
        "ffmpeg",
        "-v",
        "warning",
        "-nostdin",
        *rendition.decoding,
        "-i",
        str(edition.picture),
        "-i",
        str(edition.soundtrack),
        "-f",
        "ffmetadata",
        "-i",
        str(edition.artifacts / "chapters.ffmeta"),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-map_metadata",
        "2",
        "-map_chapters",
        "2",
        *rendition.video,
        "-bsf:v:0",
        video_tags(rendition),
        "-c:a",
        "aac",
        "-b:a",
        "256k",
        "-ar",
        str(RATE),
        "-ac",
        "2",
        "-t",
        str(DURATION),
        *(argument for tag in tags for argument in ("-metadata", tag)),
        "-metadata:s:v:0",
        "language=" + language,
        "-metadata:s:v:0",
        "handler_name=" + names["picture"],
        "-metadata:s:a:0",
        "language=" + language,
        "-metadata:s:a:0",
        "handler_name=" + names["narration"],
        "-movflags",
        "+faststart",
        str(intermediate),
    ]


def encode(
    edition: Edition, package: dict, command: list[str], deadline: int, intermediate: Path
) -> None:
    """Run an encode; when it fails or times out, record what it was bound to and re-raise."""
    try:
        run(command, timeout=deadline)
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError) as error:
        write(
            edition.evidence / FAILURE_RECEIPT,
            {
                "input_bindings": {
                    key: value for key, value in package.items() if key != "editions"
                },
                "command": command,
                "deadline_seconds": deadline,
                "error_type": type(error).__name__,
                "intermediate": str(intermediate.relative_to(repository.ROOT)),
                "intermediate_sha256": sha(intermediate) if intermediate.exists() else None,
                "completed_members": [member["path"] for member in package["editions"]],
            },
        )
        raise


def attach_cover_and_keys(
    edition: Edition, intermediate: Path, finished: Path, created_at: str
) -> list[list[str]]:
    """Attach the JPEG cover and the QuickTime keys; return both commands."""
    cover_command = [
        "ffmpeg",
        "-v",
        "warning",
        "-nostdin",
        "-i",
        str(intermediate),
        "-i",
        str(edition.artifacts / "ddwg-cover.jpg"),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0",
        "-map",
        "1:v:0",
        "-map_metadata",
        "0",
        "-map_chapters",
        "0",
        "-c",
        "copy",
        "-disposition:v:1",
        "attached_pic",
        "-movflags",
        "+faststart",
        str(finished),
    ]
    run(cover_command, timeout=120)
    keys = {**quicktime_keys(edition), "CreationDate": created_at}
    keys_command = [
        "exiftool",
        "-overwrite_original",
        *(f"-Keys:{key}={value}" for key, value in keys.items()),
        str(finished),
    ]
    run(keys_command, timeout=120)
    return [cover_command, keys_command]


def check_delivered_film(path: Path, edition: Edition, rendition: Rendition) -> None:
    """Refuse a finished film without every frame, its duration, cover, release tags or tracks.

    Its release tags must be exactly the rendition's, so only the 1080p film is marked HD, and
    its picture and narration tracks must carry their names and the edition's language.
    """
    info = media.probe(path)
    streams = info["streams"]
    movie = media.video_stream(info)
    sounds = [stream for stream in streams if stream["codec_type"] == "audio"]
    tags, expected = info["format"].get("tags", {}), delivered_tags(edition, rendition)
    names, language = track_names(edition), ISO_LANGUAGES[edition.code]
    if not (
        sounds
        and int(movie["nb_frames"]) == DURATION * FPS
        and movie["avg_frame_rate"] == f"{FPS}/1"
        and float(info["format"]["duration"]) == float(sounds[0]["duration"]) == DURATION
        and any(stream.get("disposition", {}).get("attached_pic") for stream in streams)
        and all(tags.get(key) == expected.get(key) for key in {*expected, "hd_video"})
        and movie.get("tags", {}) | {"handler_name": names["picture"], "language": language}
        == movie.get("tags", {})
        and sounds[0].get("tags", {}) | {"handler_name": names["narration"], "language": language}
        == sounds[0].get("tags", {})
    ):
        msg = f"The finished film differs from the delivery contract: {path}"
        raise PackagingError(msg)


def package_rendition(
    edition: Edition, package: dict, rendition: Rendition, target: Path, created_at: str
) -> dict:
    """Encode, finish and check one film in the work folder, then link it into place.

    Returns the film's package member. A film or work file already in place is preserved
    for inspection, as is the work of a failed step.
    """
    if target.exists():
        msg = f"Preserve existing film output: {target}"
        raise PackagingError(msg)
    work = repository.ROOT / WORK / edition.code
    intermediate, finished = work / target.name, work / "finished" / target.name
    if intermediate.exists() or finished.exists():
        msg = f"Preserve existing packaging input: {target.name}"
        raise PackagingError(msg)
    finished.parent.mkdir(parents=True, exist_ok=True)
    command = encode_command(edition, rendition, intermediate, created_at)
    write(edition.film_package, package)
    deadline = max(DEADLINE_FLOOR, DURATION * rendition.deadline_ratio)
    encode(edition, package, command, deadline, intermediate)
    commands = [command, *attach_cover_and_keys(edition, intermediate, finished, created_at)]
    check_delivered_film(finished, edition, rendition)
    target.hardlink_to(finished)
    member = {"path": target.name, "sha256": sha(target), "commands": commands}
    finished.unlink()
    intermediate.unlink()
    return member


def package_film(edition: Edition) -> None:
    """Write both delivered films with the exact soundtrack and media metadata.

    A film recorded by a package bound to the current inputs is reused when its bytes are the
    recorded ones; the edition's folder never receives a film before its checks pass. The
    finished package supersedes the failure receipt of an earlier attempt, which is retired.
    """
    if not edition.picture.is_file():
        msg = f"No rendered picture at {edition.picture}"
        raise PackagingError(msg)
    validate_picture(edition)
    package_metadata(edition)
    package = resume_package(edition)
    created_at = datetime.now(UTC).isoformat()
    for kind, rendition in RENDITIONS.items():
        target = edition.film(kind)
        completed = next((m for m in package["editions"] if m["path"] == target.name), None)
        if completed:
            if not target.is_file() or sha(target) != completed["sha256"]:
                msg = "Completed package member differs; preserve and inspect it"
                raise PackagingError(msg)
            print(json.dumps({"film": target.name, "reused_verified_member": True}), flush=True)
            continue
        package["editions"].append(
            package_rendition(edition, package, rendition, target, created_at)
        )
        write(edition.film_package, package)
        print(json.dumps({"film": target.name, "bytes": target.stat().st_size}), flush=True)
    write(edition.film_package, package)
    (edition.evidence / FAILURE_RECEIPT).unlink(missing_ok=True)
