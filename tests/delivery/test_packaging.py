"""The delivery index, the player, the viewing members and the packaged films."""

import json
import subprocess
from pathlib import Path

import pytest

import ddwg_film.delivery.packaging as delivery_packaging
import ddwg_film.media as media
import ddwg_film.production as production
import ddwg_film.repository as repository
import ddwg_film.specification as specification
from ddwg_film.delivery.packaging import PackagingError


def test_the_player_transcript_keeps_chapters_segments_and_escaped_text():
    transcript = (
        "# DDWG · Title\n\nYang HENG · English · 25 min\n\n## 01 Opening\n\n"
        "00:00:02.118 · First <scene>\n\nA & B < C.\n\n## 02 Next\n\n"
        "00:01:00.000 · Second\n\nMore.\n"
    )
    assert delivery_packaging.transcript_html(transcript) == (
        "<h2>01 Opening</h2><h3>00:00:02.118 · First &lt;scene&gt;</h3>"
        "<p>A &amp; B &lt; C.</p><h2>02 Next</h2><h3>00:01:00.000 · Second</h3>"
        "<p>More.</p>"
    )
    player = (repository.ROOT / delivery_packaging.PLAYER).read_text()
    english = delivery_packaging.localize_player(player, "en")
    assert english.count("/*TRANSCRIPT*/") == 1
    assert '<a href="#transcript">Transcript</a>' in english
    assert '<a href="ddwg-en-transcript.md">Transcript (Markdown)</a>' in english
    assert delivery_packaging.CHINESE.search(english) is None
    assert delivery_packaging.localize_player(player, "zh") == player


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (("章节", "目录"), "lacks a text the English player translates: 章节"),
        (("ddwg-zh", "ddwg-cn"), "lacks a text the English player translates: ddwg-zh"),
        (("</footer>", "<a>新增</a></footer>"), "keeps Chinese text: 新增"),
        (("</footer>", "<a>，</a></footer>"), "keeps Chinese text: ，"),
    ],
)
def test_the_english_player_refuses_an_untranslated_template(change, message):
    player = (repository.ROOT / delivery_packaging.PLAYER).read_text().replace(*change)
    with pytest.raises(PackagingError, match=message):
        delivery_packaging.localize_player(player, "en")


def test_the_runtime_and_viewing_members_follow_the_edition():
    minutes, seconds = divmod(specification.DURATION, 60)
    assert delivery_packaging.runtime_label() == f"{minutes:02d}:{seconds:02d}"
    assert delivery_packaging.viewing_members(production.Edition("en")) == (
        "ddwg-cover.png",
        "ddwg-cover.jpg",
        "ddwg-en.srt",
        "ddwg-en.vtt",
        "ddwg-en-transcript.md",
        "chapters.json",
        "chapters.ffmeta",
        "index.html",
    )


def test_delivery_index_uses_sibling_languages_and_preserves_language_players(
    tmp_path,
    monkeypatch,
):
    """Exercise the actual root-template producer, independent of edition depth."""
    template = (repository.ROOT / delivery_packaging.INDEX).read_bytes()
    monkeypatch.setattr(repository, "ROOT", tmp_path)
    source = tmp_path / delivery_packaging.INDEX
    source.parent.mkdir(parents=True)
    source.write_bytes(template)
    root = tmp_path / "build/artifacts/film"
    for code in ("zh", "en"):
        player = root / code / "index.html"
        player.parent.mkdir(parents=True)
        player.write_text(f"Existing {code} player")
    observed = delivery_packaging.package_language_index()
    output = (root / "index.html").read_text()
    assert 'href="zh/index.html"' in output
    assert 'href="en/index.html"' in output
    runtime = f"{specification.DURATION // 60:02d}:{specification.DURATION % 60:02d}"
    assert "<base " not in output
    assert runtime in output
    assert observed == {
        "source": "src/ddwg_film/delivery/index.html",
        "source_sha256": repository.sha(source),
        "path": "build/artifacts/film/index.html",
        "sha256": repository.sha(root / "index.html"),
        "languages": ["zh", "en"],
    }
    for code in ("zh", "en"):
        assert (root / code / "index.html").read_text() == f"Existing {code} player"
    source.write_bytes(template.replace(b'href="en/index.html"', b'href="en.html"'))
    with pytest.raises(PackagingError, match="both sibling language links"):
        delivery_packaging.package_language_index()


def probe(
    *,
    frames=specification.DURATION * specification.FPS,
    author=specification.AUTHOR,
    sound="audio",
    kind="uhd",
    changes=None,
):
    """A probe of a finished film, as FFprobe reports one that meets the delivery contract.

    Its tags are the zh edition's release tags for the rendition of the given kind, and
    `changes` replaces or, with None, removes some of them.
    """
    edition = production.Edition("zh")
    rendition = production.RENDITIONS[kind]
    duration = f"{specification.DURATION:.6f}"
    tags = {**delivery_packaging.delivered_tags(edition, rendition)}
    tags["com.apple.quicktime.author"] = author
    for key, value in (changes or {}).items():
        if value is None:
            tags.pop(key, None)
        else:
            tags[key] = value
    names = delivery_packaging.track_names(edition)
    return {
        "streams": [
            {
                "codec_type": "video",
                "nb_frames": str(frames),
                "avg_frame_rate": "60/1",
                "tags": {"language": "zho", "handler_name": names["picture"]},
            },
            {
                "codec_type": sound,
                "duration": duration,
                "tags": {"language": "zho", "handler_name": names["narration"]},
            },
            {"codec_type": "video", "disposition": {"attached_pic": 1}},
        ],
        "format": {"duration": duration, "tags": {k: v for k, v in tags.items() if v}},
    }


@pytest.fixture
def packaging_root(tmp_path, monkeypatch):
    """A root holding one edition's packaging inputs, with FFmpeg and ExifTool simulated."""
    monkeypatch.setattr(repository, "ROOT", tmp_path)
    edition = production.Edition("zh")
    script = json.loads((Path(__file__).parents[2] / edition.script).read_text())
    (tmp_path / edition.script).parent.mkdir(parents=True)
    (tmp_path / edition.script).write_text(
        json.dumps({"title": script["title"], "release": script["release"]}, ensure_ascii=False)
    )
    edition.artifacts.mkdir(parents=True)
    for path, body in (
        (edition.picture, "picture"),
        (edition.soundtrack, "soundtrack"),
        (edition.artifacts / "chapters.ffmeta", ";FFMETADATA1\n"),
        (edition.artifacts / "ddwg-cover.jpg", "cover"),
    ):
        path.write_text(body)
    calls = []

    def run(command, timeout=120):
        calls.append((command, timeout))
        output = Path(command[-1])
        if command[0] == "ffmpeg":
            output.write_text(
                f"{output.name} encoded from {Path(command[command.index('-i') + 1]).name}\n"
            )
        else:
            output.write_text(output.read_text() + "author tagged\n")
        return subprocess.CompletedProcess(command, 0, b"", b"")

    monkeypatch.setattr(delivery_packaging, "run", run)
    monkeypatch.setattr(delivery_packaging, "validate_picture", lambda _edition: {})
    monkeypatch.setattr(delivery_packaging, "package_metadata", lambda _edition: None)
    monkeypatch.setattr(media, "probe", lambda path: probe(kind=kind_of(path)))
    return tmp_path, edition, calls


def kind_of(path) -> str:
    """The rendition kind a film's name declares."""
    return next(kind for kind in production.RENDITIONS if Path(path).stem.endswith(kind))


def test_each_film_is_encoded_finished_and_checked_in_work_before_it_is_linked_into_place(
    packaging_root,
):
    root, edition, calls = packaging_root
    delivery_packaging.package_film(edition)
    package = json.loads(edition.film_package.read_text())
    assert list(package) == [
        "picture_sha256",
        "soundtrack_sha256",
        "cover_sha256",
        "script_sha256",
        "chapters_sha256",
        "editions",
        "caption_owner",
    ]
    assert [member["path"] for member in package["editions"]] == [
        "ddwg-zh-uhd.mp4",
        "ddwg-zh-1080p-captioned.mp4",
    ]
    work = root / "build/runtime/work/final-film-packaging/zh"
    for member, film in zip(package["editions"], edition.films, strict=True):
        assert member["sha256"] == repository.sha(film)
        assert film.read_text() == f"{film.name} encoded from {film.name}\nauthor tagged\n"
        encode, cover, author = member["commands"]
        assert encode[-1] == str(work / film.name)
        assert cover[-1] == author[-1] == str(work / "finished" / film.name)
        assert [command for command, _ in calls[:3]] == member["commands"]
        calls[:3] = []
    assert list(work.rglob("*.mp4")) == []
    assert not (edition.evidence / "packaging-failure.json").exists()


def test_the_commands_carry_the_release_metadata(packaging_root):
    root, edition, calls = packaging_root
    delivery_packaging.package_film(edition)
    release = repository.read(edition.script)["release"]
    artifacts, work = (
        f"{root}/build/artifacts/film/zh",
        f"{root}/build/runtime/work/final-film-packaging/zh",
    )
    created = next(argument for argument in calls[0][0] if argument.startswith("creation_time="))
    inputs = [
        "-i",
        f"{artifacts}/ddwg-final-picture.mp4",
        "-i",
        f"{artifacts}/ddwg-zh-narration.wav",
        "-f",
        "ffmetadata",
        "-i",
        f"{artifacts}/chapters.ffmeta",
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-map_metadata",
        "2",
        "-map_chapters",
        "2",
    ]
    sound = ["-c:a", "aac", "-b:a", "256k", "-ar", "48000", "-ac", "2"]
    sound += ["-t", str(specification.DURATION)]
    tags = [
        "title=DDWG · 数据部门工作指南",
        "artist=Yang HENG",
        "album_artist=Yang HENG",
        "album=DDWG · 数据部门工作指南",
        "genre=教育",
        "date=2026",
        "comment=中文介绍影片；示例均为示意；不声称已部署或已采用",
        "description=数据部门工作指南；中文；纯 2D；仅旁白",
        "synopsis=" + release["synopsis"],
        "copyright=© 2026 Yang HENG",
        "media_type=9",
    ]
    streams = [
        "-metadata:s:v:0",
        "language=zho",
        "-metadata:s:v:0",
        "handler_name=画面",
        "-metadata:s:a:0",
        "language=zho",
        "-metadata:s:a:0",
        "handler_name=中文旁白",
    ]
    bitstream = (
        "h264_metadata=colour_primaries=1:transfer_characteristics=1:matrix_coefficients=1"
        ":video_full_range_flag=0:level="
    )
    hardware = ["-hwaccel", "videotoolbox", "-hwaccel_output_format", "videotoolbox_vld"]
    scaled = [
        "-filter:v:0",
        "scale_vt=w=1920:h=1080",
        "-c:v:0",
        "h264_videotoolbox",
        "-b:v:0",
        "10M",
    ]
    attach = ["-map", "0:v:0", "-map", "0:a:0", "-map", "1:v:0", "-map_metadata", "0"]
    attach += ["-map_chapters", "0", "-c", "copy", "-disposition:v:1", "attached_pic"]
    keys = [
        "-Keys:Author=Yang HENG",
        "-Keys:Title=DDWG · 数据部门工作指南",
        "-Keys:Artist=Yang HENG",
        "-Keys:Album=DDWG · 数据部门工作指南",
        "-Keys:Genre=教育",
        "-Keys:Description=数据部门工作指南；中文；纯 2D；仅旁白",
        "-Keys:Comment=中文介绍影片；示例均为示意；不声称已部署或已采用",
        "-Keys:Copyright=© 2026 Yang HENG",
        "-Keys:Keywords=" + ", ".join(release["keywords"]),
        "-Keys:Year=2026",
        "-Keys:CreationDate=" + created.removeprefix("creation_time="),
    ]
    expected = []
    for name, decoding, video, level, marks, deadline in (
        ("ddwg-zh-uhd.mp4", [], ["-c:v:0", "copy"], "5.2", [], 600),
        (
            "ddwg-zh-1080p-captioned.mp4",
            hardware,
            scaled,
            "4.2",
            ["hd_video=2"],
            2 * specification.DURATION,
        ),
    ):
        intermediate, finished = f"{work}/{name}", f"{work}/finished/{name}"
        cover = ["-i", intermediate, "-i", f"{artifacts}/ddwg-cover.jpg", *attach]
        metadata = [arg for tag in [*tags, *marks, created] for arg in ("-metadata", tag)]
        encode = [*decoding, *inputs, *video, "-bsf:v:0", bitstream + level, *sound, *metadata]
        encode += [*streams, "-movflags", "+faststart", intermediate]
        expected += [
            (["ffmpeg", "-v", "warning", "-nostdin", *encode], deadline),
            (
                [
                    "ffmpeg",
                    "-v",
                    "warning",
                    "-nostdin",
                    *cover,
                    "-movflags",
                    "+faststart",
                    finished,
                ],
                120,
            ),
            (["exiftool", "-overwrite_original", *keys, finished], 120),
        ]
    assert calls == expected
    created = {
        argument for command, _ in calls for argument in command if "creation_time" in argument
    }
    assert len(created) == 1


def test_a_failed_check_leaves_no_film_in_place_and_keeps_the_work(packaging_root, monkeypatch):
    root, edition, _ = packaging_root
    monkeypatch.setattr(
        media, "probe", lambda path: probe(author="Someone else", kind=kind_of(path))
    )
    with pytest.raises(PackagingError, match="finished film differs from the delivery contract"):
        delivery_packaging.package_film(edition)
    assert not edition.film("uhd").exists()
    work = root / "build/runtime/work/final-film-packaging/zh"
    assert (work / "finished/ddwg-zh-uhd.mp4").is_file()
    assert json.loads(edition.film_package.read_text())["editions"] == []
    monkeypatch.setattr(media, "probe", lambda path: probe(kind=kind_of(path)))
    with pytest.raises(PackagingError, match="Preserve existing packaging input"):
        delivery_packaging.package_film(edition)


@pytest.mark.parametrize(
    "change",
    [
        {"frames": specification.DURATION * specification.FPS - 1},
        {"author": None},
        {"sound": "data"},
        {"changes": {"album": None}},
        {"changes": {"synopsis": "Another film."}},
        {"changes": {"com.apple.quicktime.keywords": None}},
        {"kind": "1080p-captioned"},
    ],
    ids=["frames", "author", "sound", "album", "synopsis", "keywords", "hd-mark"],
)
def test_a_finished_film_needs_every_frame_its_author_and_release(tmp_path, monkeypatch, change):
    monkeypatch.setattr(media, "probe", lambda _path: probe(**change))
    with pytest.raises(PackagingError, match="differs from the delivery contract"):
        delivery_packaging.check_delivered_film(
            tmp_path / "film.mp4", production.Edition("zh"), production.RENDITIONS["uhd"]
        )


def test_the_release_tags_come_from_the_script():
    edition, uhd = production.Edition("zh"), production.RENDITIONS["uhd"]
    release = repository.read(edition.script)["release"]
    tags = dict(delivery_packaging.release_tags(edition, uhd))
    assert tags == {
        "title": "DDWG · 数据部门工作指南",
        "artist": "Yang HENG",
        "album_artist": "Yang HENG",
        "album": release["collection"],
        "genre": "教育",
        "date": "2026",
        "comment": edition.comment,
        "description": edition.description,
        "synopsis": release["synopsis"],
        "copyright": "© 2026 Yang HENG",
        "media_type": "9",
    }
    viewing = dict(
        delivery_packaging.release_tags(edition, production.RENDITIONS["1080p-captioned"])
    )
    assert viewing == {**tags, "hd_video": "2"}
    assert delivery_packaging.track_names(production.Edition("en")) == {
        "picture": "Picture",
        "narration": "English narration",
    }


def test_a_failed_encode_records_its_bindings_and_command(packaging_root, monkeypatch):
    _, edition, _ = packaging_root

    def fail(command, timeout=120):
        raise subprocess.TimeoutExpired(command, timeout)

    monkeypatch.setattr(delivery_packaging, "run", fail)
    with pytest.raises(subprocess.TimeoutExpired):
        delivery_packaging.package_film(edition)
    failure = json.loads((edition.evidence / "packaging-failure.json").read_text())
    assert list(failure) == [
        "input_bindings",
        "command",
        "deadline_seconds",
        "error_type",
        "intermediate",
        "intermediate_sha256",
        "completed_members",
    ]
    assert failure["input_bindings"]["caption_owner"] == delivery_packaging.CAPTION_OWNER
    assert "editions" not in failure["input_bindings"]
    assert (failure["deadline_seconds"], failure["error_type"]) == (600, "TimeoutExpired")
    assert failure["intermediate"] == "build/runtime/work/final-film-packaging/zh/ddwg-zh-uhd.mp4"
    assert failure["intermediate_sha256"] is None
    assert failure["completed_members"] == []


def test_a_finished_package_retires_the_receipt_of_an_earlier_failed_attempt(
    packaging_root, monkeypatch
):
    _, edition, _ = packaging_root
    succeed = delivery_packaging.run

    def fail(command, timeout=120):
        raise subprocess.TimeoutExpired(command, timeout)

    monkeypatch.setattr(delivery_packaging, "run", fail)
    with pytest.raises(subprocess.TimeoutExpired):
        delivery_packaging.package_film(edition)
    assert (edition.evidence / "packaging-failure.json").exists()
    monkeypatch.setattr(delivery_packaging, "run", succeed)
    delivery_packaging.package_film(edition)
    assert edition.film_package.exists()
    assert not (edition.evidence / "packaging-failure.json").exists()


def test_a_package_resumes_its_verified_films_and_refuses_changed_inputs(packaging_root):
    _, edition, calls = packaging_root
    delivery_packaging.package_film(edition)
    recorded = edition.film_package.read_text()
    calls.clear()
    delivery_packaging.package_film(edition)
    assert calls == []
    assert edition.film_package.read_text() == recorded
    edition.film("1080p-captioned").write_text("changed\n")
    with pytest.raises(PackagingError, match="Completed package member differs"):
        delivery_packaging.package_film(edition)
    edition.soundtrack.write_text("another soundtrack")
    with pytest.raises(PackagingError, match="bound to different production inputs"):
        delivery_packaging.package_film(edition)


def test_an_unrecorded_film_in_place_is_preserved(packaging_root):
    _, edition, calls = packaging_root
    edition.film("uhd").write_text("left by an interrupted step\n")
    with pytest.raises(PackagingError, match="Preserve existing film output"):
        delivery_packaging.package_film(edition)
    assert calls == []
    assert edition.film("uhd").read_text() == "left by an interrupted step\n"
    edition.picture.unlink()
    with pytest.raises(PackagingError, match="No rendered picture"):
        delivery_packaging.package_film(edition)
