"""The comparison of a rebuild with the published release under the reproduction standard."""

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

import filmkit.delivery.packaging as packaging
import filmkit.delivery.reproduction as reproduction
import filmkit.picture.rendering as picture_rendering
import filmkit.production as production
import filmkit.repository as repository
import filmkit.review.record as review_record
from filmkit.delivery.reproduction import ReproductionError

pytestmark = pytest.mark.ffmpeg


def encode(target: Path, picture: str, tone: int, created: str = "2026-10-28T11:29:43Z") -> Path:
    """A six-frame 60 fps film of a test picture and a sine tone, titled and dated like a film."""
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-nostdin",
            "-f",
            "lavfi",
            "-i",
            f"{picture}=s=64x36:r=60",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency={tone}:sample_rate=48000",
            "-frames:v",
            "6",
            "-t",
            "0.1",
            "-ac",
            "2",
            "-c:v",
            "libx264",
            "-bf",
            "0",
            "-c:a",
            "aac",
            "-metadata",
            "title=A film",
            "-metadata",
            f"creation_time={created}",
            str(target),
        ],
        check=True,
        capture_output=True,
        timeout=60,
    )
    return target


@pytest.fixture(scope="session")
def films(tmp_path_factory) -> dict[str, Path]:
    """The published film, and rebuilt films of another picture and of another sound."""
    folder = tmp_path_factory.mktemp("films")
    return {
        "same": encode(folder / "same.mp4", "testsrc2", 440),
        "picture": encode(folder / "picture.mp4", "smptebars", 440),
        "sound": encode(folder / "sound.mp4", "testsrc2", 880),
        "later": encode(folder / "later.mp4", "testsrc2", 440, "2026-11-05T09:00:00Z"),
    }


@dataclass
class Release:
    """A rebuild of both editions below the root and the release it is compared with."""

    root: Path
    films: dict[str, Path]

    @property
    def folder(self) -> Path:
        return self.root / reproduction.RELEASE

    def publish(self, name: str, source: Path) -> None:
        """Place a published asset as a copy of a file."""
        self.folder.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, self.folder / name)

    def record(self, floors: float | None = 30.0) -> None:
        """Write the release manifest of the published folder, with each film's floor."""
        editions = {}
        for code in production.CODES:
            edition = production.Edition(code)
            films = [film.name for film in edition.films]
            editions[code] = {
                "soundtrack_sha256": repository.sha(edition.soundtrack),
                "stage_sha256": repository.sha(edition.picture_stage / "index.html"),
                "picture_floor_db": {} if floors is None else dict.fromkeys(films, floors),
            }
        assets = [
            {"name": path.name, "bytes": path.stat().st_size, "sha256": repository.sha(path)}
            for path in sorted(self.folder.iterdir())
            if path.name != reproduction.CHECKSUMS
        ]
        manifest = {"version": "1.0.0", "editions": editions, "assets": assets}
        checksums = reproduction.checksums(reproduction.Release.model_validate(manifest))
        (self.folder / reproduction.CHECKSUMS).write_text(checksums)
        assets.append(
            {
                "name": reproduction.CHECKSUMS,
                "bytes": len(checksums.encode()),
                "sha256": repository.content_sha(checksums),
            }
        )
        (self.root / reproduction.MANIFEST).write_text(json.dumps(manifest))

    def compare(self) -> dict:
        return reproduction.compare()


@pytest.fixture
def release(tmp_path, monkeypatch, films) -> Release:
    """A faithful rebuild of both editions and their published release, with every floor."""
    monkeypatch.setattr(repository, "ROOT", tmp_path)
    composition = tmp_path / picture_rendering.COMPOSITION_SCRIPT
    composition.parent.mkdir(parents=True)
    composition.write_text("/* film */")
    published = Release(tmp_path, films)
    for code in production.CODES:
        edition = production.Edition(code)
        script = tmp_path / edition.script
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text(json.dumps({"edition": code}))
        edition.artifacts.mkdir(parents=True)
        edition.picture_stage.mkdir(parents=True)
        (edition.picture_stage / "index.html").write_text(f"<html>{code}</html>")
        edition.soundtrack.write_bytes(f"soundtrack {code}".encode())
        for film in edition.films:
            shutil.copyfile(films["same"], film)
        for name, (layer, source) in reproduction.members(edition).items():
            if layer == "document":
                source.write_text(f"{name}\n")
            if layer != "review":
                published.publish(name, source)
        report = f"# Review of {code}\n"
        (published.folder / f"{edition.prefix}-production-review.md").write_text(report)
        review = {
            "schema_version": review_record.SCHEMA_VERSION,
            "language": code,
            "reviewer": "independent reviewer",
            "media": [
                {"path": repository.relative(film), "sha256": repository.sha(film)}
                for film in edition.films
            ],
            "script_sha256": repository.sha(script),
            "composition_sha256": repository.sha(composition),
            "scores": dict.fromkeys(review_record.DIMENSIONS, 96),
            "overall": 96.0,
            "findings": [],
            "human_listening": {"state": "performed"},
            "report": {"path": "evidence/reviews/production-review.md", "sha256": ""},
        }
        review["report"]["sha256"] = repository.content_sha(report)
        (published.folder / f"{edition.prefix}-production-review.json").write_text(
            json.dumps(review)
        )
    published.record()
    return published


def test_a_faithful_rebuild_passes_and_reports_every_layer(release):
    report = release.compare()
    assert report["verdict"] == "pass"
    assert report["release"] == "1.0.0"
    zh = report["editions"]["zh"]
    assert {zh["soundtrack"]["verdict"], zh["stage"]["verdict"], zh["review"]["verdict"]} == {
        "pass"
    }
    assert [document["asset"] for document in zh["documents"]] == [
        "ddwg-zh.srt",
        "ddwg-zh.vtt",
        "ddwg-zh-transcript.md",
        "ddwg-zh-cover.png",
    ]
    uhd = zh["films"][0]
    assert uhd["asset"] == "ddwg-zh-uhd.mp4"
    assert (uhd["frames"], uhd["audio"], uhd["container"]) == (6, "identical", "identical")
    assert uhd["psnr"]["identical_frames"] == 6
    assert uhd["psnr"]["minimum_db"] is None
    assert uhd["verdict"] == "pass"


def test_the_report_is_written_unless_read_only(release, capsys):
    reproduction.main([])
    written = json.loads((release.root / reproduction.REPORT).read_text())
    assert written["verdict"] == "pass"
    (release.root / reproduction.REPORT).unlink()
    reproduction.main(["--read-only"])
    assert not (release.root / reproduction.REPORT).exists()
    assert "pass" in capsys.readouterr().out


def test_without_a_floor_the_comparison_reports_the_lowest_frames_and_does_not_pass(release):
    shutil.copyfile(release.films["picture"], production.Edition("zh").film("uhd"))
    release.record(floors=None)
    report = release.compare()
    assert report["verdict"] == "calibrating"
    psnr = report["editions"]["zh"]["films"][0]["psnr"]
    assert (psnr["floor_db"], psnr["identical_frames"]) == (None, 0)
    lowest = [frame["psnr_db"] for frame in psnr["lowest"]]
    assert lowest == sorted(lowest)
    assert psnr["minimum_db"] == lowest[0]
    with pytest.raises(SystemExit, match="calibrating"):
        reproduction.main(["--read-only"])


def test_a_frame_below_its_floor_fails_naming_the_film_and_frame(release):
    shutil.copyfile(release.films["picture"], production.Edition("en").film("1080p-captioned"))
    film = release.compare()["editions"]["en"]["films"][1]
    assert film["verdict"] == "fail"
    assert film["psnr"]["below_floor"][0] == 0
    with pytest.raises(SystemExit, match=r"en: ddwg-en-1080p-captioned\.mp4: picture"):
        reproduction.main(["--read-only"])


def test_a_film_packaged_later_differs_only_in_its_creation_date(release):
    shutil.copyfile(release.films["later"], production.Edition("zh").film("uhd"))
    film = release.compare()["editions"]["zh"]["films"][0]
    assert (film["container"], film["audio"], film["verdict"]) == ("identical", "identical", "pass")


def test_different_decoded_audio_fails(release):
    shutil.copyfile(release.films["sound"], production.Edition("zh").film("uhd"))
    film = release.compare()["editions"]["zh"]["films"][0]
    assert (film["audio"], film["verdict"]) == ("differs", "fail")


@pytest.mark.parametrize(
    ("change", "layer"),
    [
        (lambda edition: edition.soundtrack.write_bytes(b"another soundtrack"), "soundtrack"),
        (
            lambda edition: (edition.picture_stage / "index.html").write_text("<html></html>"),
            "stage",
        ),
        (lambda edition: (edition.artifacts / "ddwg-zh.vtt").write_text("WEBVTT\n"), "documents"),
    ],
)
def test_a_rebuilt_byte_that_differs_fails_naming_the_edition_and_layer(release, change, layer):
    change(production.Edition("zh"))
    report = release.compare()
    assert report["verdict"] == "fail"
    with pytest.raises(SystemExit, match=f"zh: .*{layer}"):
        reproduction.main(["--read-only"])


def test_a_review_that_does_not_bind_the_published_films_fails(release):
    path = release.folder / "ddwg-en-production-review.json"
    review = json.loads(path.read_text())
    review["media"][0]["sha256"] = "0" * 64
    path.write_text(json.dumps(review))
    release.record()
    report = release.compare()
    assert report["editions"]["en"]["review"]["verdict"] == "fail"
    assert "current delivered edition" in report["editions"]["en"]["review"]["reason"]
    assert report["verdict"] == "fail"


def test_a_published_asset_that_differs_from_the_manifest_refuses_before_any_layer(release):
    (release.folder / "ddwg-zh.srt").write_text("edited\n")
    with pytest.raises(
        ReproductionError, match=r"published asset differs from the release manifest: ddwg-zh\.srt"
    ):
        release.compare()


@pytest.mark.usefixtures("release")
def test_checksums_list_every_other_asset_for_shasum():
    manifest = reproduction.load()
    lines = reproduction.checksums(manifest).splitlines()
    names = [line.split("  ", 1)[1] for line in lines]
    assert names == sorted(asset.name for asset in manifest.assets if asset.name != "SHA256SUMS")
    assert all(len(line.split("  ", 1)[0]) == 64 for line in lines)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda manifest: manifest["editions"].pop("en"), "records the editions"),
        (
            lambda manifest: manifest["assets"].pop(0),
            "does not name every published asset of the editions",
        ),
        (
            lambda manifest: manifest["editions"]["zh"].update(soundtrack_sha256="abc"),
            "is not a release manifest",
        ),
        (
            lambda manifest: manifest["editions"]["zh"]["picture_floor_db"].update(
                {"ddwg-zh.srt": 30.0}
            ),
            "records a floor for an asset that is not a film",
        ),
        (
            lambda manifest: manifest["assets"][-1].update(sha256="0" * 64),
            "SHA256SUMS differs from the assets it lists",
        ),
    ],
)
def test_an_inconsistent_manifest_is_refused(release, change, message):
    path = release.root / reproduction.MANIFEST
    manifest = json.loads(path.read_text())
    change(manifest)
    path.write_text(json.dumps(manifest))
    with pytest.raises(ReproductionError, match=message):
        reproduction.load()


@pytest.mark.usefixtures("release")
def test_each_edition_publishes_its_films_documents_cover_and_review():
    edition = production.Edition("en")
    published = reproduction.members(edition)
    assert published["ddwg-en-cover.png"] == ("document", edition.artifacts / packaging.COVER_PNG)
    assert published["ddwg-en-production-review.json"] == ("review", edition.production_review)
    assert [name for name, (layer, _) in published.items() if layer == "film"] == [
        film.name for film in edition.films
    ]
