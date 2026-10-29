"""Exercise the review round: set-aside, the player-check binding, prompts and records."""

import json
import re

import pytest

import ddwg_film.delivery.verification as delivery_verification
import ddwg_film.picture.rendering as picture_rendering
import ddwg_film.repository as repository
import ddwg_film.review.record as review_record
import ddwg_film.review.round as review_round
import ddwg_film.sources as sources
import ddwg_film.specification as specification
from ddwg_film.production import CODES, Edition
from ddwg_film.review import ReviewError

SCORES = dict.fromkeys(review_record.DIMENSIONS, 92)
PURPOSE = "superseded by its repairs"


@pytest.fixture
def review(put):
    """Write one edition's review and report into a round directory."""

    def write(folder, code, *, media=None, findings=(), **edition):
        media = media or [
            {"path": str(film), "sha256": repository.sha(film)} for film in Edition(code).films
        ]
        edition = {
            "media": media,
            "scores": SCORES,
            "overall": 92.0,
            "findings": list(findings),
            "human_listening_checklist": ["Listen to 24.3 in its clause."],
        } | edition
        put(folder / f"review-{code}.json", {"reviewer": "Reviewer", "editions": {code: edition}})
        put(folder / f"{code}-review.md", f"# {code} review\n")

    return write


def test_set_aside_refuses_before_moving_then_reads_back_each_member(root, review):
    reviews = root / "build/evidence/reviews/round-3"
    review(reviews, "zh")
    review(reviews, "en", media=[{"path": "other.mp4", "sha256": "0" * 64}])
    with pytest.raises(ReviewError, match="en: the packaged films are not the ones round 3"):
        review_round.plan_set_aside(3, PURPOSE, reviews)
    review(reviews, "en")
    Edition("zh").picture.unlink()
    with pytest.raises(ReviewError, match="missing build/artifacts/film/zh/ddwg-final-picture"):
        review_round.plan_set_aside(3, PURPOSE, reviews)
    assert Edition("zh").film("uhd").is_file()
    assert not (root / "build/artifacts/film/superseded").exists()

    plans = review_round.plan_set_aside(3, PURPOSE, reviews, picture=False)
    assert not (root / "build/artifacts/film/superseded").exists()
    sources = {
        code: [
            f"build/artifacts/film/{code}/ddwg-{code}-uhd.mp4",
            f"build/artifacts/film/{code}/ddwg-{code}-1080p-captioned.mp4",
            f"build/evidence/editions/{code}/film-package.json",
        ]
        for code in CODES
    }
    before = {path: repository.sha(root / path) for paths in sources.values() for path in paths}
    review_round.move_aside(plans)
    for code in CODES:
        target = root / "build/artifacts/film/superseded/round-3" / code
        manifest = json.loads((target / "manifest.json").read_text())
        assert list(manifest) == ["purpose", "consumer", "exit_condition", "moved_at", "members"]
        assert manifest["purpose"] == f"{code} package and picture reviewed in round 3: {PURPOSE}"
        consumer = f"build/evidence/reviews/round-3/review-{code}.json"
        assert manifest["consumer"] == f"{consumer} binds the two film hashes"
        assert manifest["exit_condition"] == "Retire after the successor delivery is accepted"
        assert manifest["moved_at"]
        assert [member["source"] for member in manifest["members"]] == sources[code]
        for member in manifest["members"]:
            moved = root / member["path"]
            assert not (root / member["source"]).exists()
            assert moved.parent == target
            assert member["sha256"] == before[member["source"]] == repository.sha(moved)
            assert member["bytes"] == moved.stat().st_size
    assert Edition("en").picture.is_file()
    with pytest.raises(ReviewError, match="round-3/zh exists; inspect it"):
        review_round.plan_set_aside(3, PURPOSE, reviews)


def test_set_aside_records_its_members_before_the_first_move(root, review, monkeypatch):
    # An interrupted set-aside leaves a manifest that names every member it was moving.
    reviews = root / "build/evidence/reviews/round-3"
    review(reviews, "zh")
    review(reviews, "en")
    plans = review_round.plan_set_aside(3, PURPOSE, reviews)
    rename = review_round.Path.rename
    moved = []

    def interrupted(self, target):
        if moved:
            message = "interrupted"
            raise OSError(message)
        moved.append(self)
        return rename(self, target)

    monkeypatch.setattr(review_round.Path, "rename", interrupted)
    with pytest.raises(OSError, match="interrupted"):
        review_round.move_aside(plans)
    target = root / "build/artifacts/film/superseded/round-3/zh"
    manifest = json.loads((target / "manifest.json").read_text())
    assert manifest["moved_at"] is None
    assert [member["path"] for member in manifest["members"]] == [
        f"build/artifacts/film/superseded/round-3/zh/{name}"
        for name in ("ddwg-zh-uhd.mp4", "ddwg-zh-1080p-captioned.mp4", "film-package.json")
    ] + ["build/artifacts/film/superseded/round-3/zh/ddwg-final-picture.mp4"]


def test_cli_defaults_the_round_directory_and_reports_refusals(root, review, capsys):
    review(review_round.round_directory(3), "zh")
    review(review_round.round_directory(3), "en")
    review_round.main(["set-aside", "--round", "3", "--purpose", "superseded", "--dry-run"])
    printed = json.loads(capsys.readouterr().out)
    assert printed == {
        "dry_run": True,
        "editions": [
            {
                "language": code,
                "target": f"build/artifacts/film/superseded/round-3/{code}",
                "members": [
                    f"build/artifacts/film/superseded/round-3/{code}/{name}"
                    for name in (
                        f"ddwg-{code}-uhd.mp4",
                        f"ddwg-{code}-1080p-captioned.mp4",
                        "film-package.json",
                        "ddwg-final-picture.mp4",
                    )
                ],
            }
            for code in CODES
        ],
    }
    assert not (root / "build/artifacts/film/superseded").exists()
    with pytest.raises(SystemExit, match="set-aside: missing build/evidence/reviews/round-4"):
        review_round.main(["set-aside", "--round", "4", "--purpose", "superseded"])
    review_round.main(["set-aside", "--round", "3", "--purpose", "superseded"])
    assert json.loads(capsys.readouterr().out)["dry_run"] is False
    assert (root / "build/artifacts/film/superseded/round-3/en/manifest.json").is_file()


@pytest.mark.usefixtures("root")
def test_the_command_reports_only_its_own_refusals(put):
    # A malformed review is a fault to see in full, not a refusal to report.
    put(review_round.round_directory(3) / "review-zh.json", "{")
    with pytest.raises(json.JSONDecodeError):
        review_round.main(["set-aside", "--round", "3", "--purpose", PURPOSE, "--dry-run"])


def test_bind_names_the_language_entry_and_each_packaged_member(root, put):
    put(root / "build/artifacts/film/index.html", "entry")
    for code in CODES:
        names = ["ddwg-cover.png", f"ddwg-{code}.srt", "index.html"]
        for name in names:
            put(root / "build/artifacts/film" / code / name, f"{code} {name}")
        put(
            Edition(code).viewing_package,
            {"members": [{"path": name, "sha256": "recorded"} for name in names]},
        )
    assert review_round.bind(root / "binding.json") == {
        "members": 11,
        "binding": "binding.json",
    }
    binding = json.loads((root / "binding.json").read_text())
    assert binding["destination"] == str(root / "build/artifacts/film")
    assert [member["path"] for member in binding["members"]] == [
        "index.html",
        *[
            f"{code}/{name}"
            for code in CODES
            for name in (
                f"ddwg-{code}-uhd.mp4",
                f"ddwg-{code}-1080p-captioned.mp4",
                "ddwg-cover.png",
                f"ddwg-{code}.srt",
                "index.html",
            )
        ],
    ]
    for member in binding["members"]:
        assert member["sha256"] == repository.sha(root / "build/artifacts/film" / member["path"])
    (root / "build/artifacts/film/en/index.html").unlink()
    with pytest.raises(ReviewError, match=re.escape("missing build/artifacts/film/en/index.html")):
        review_round.bind(root / "binding.json")


def test_prompts_cite_the_exact_media_previous_findings_and_round_inputs(
    root, review, put, monkeypatch
):
    policies = {
        "zh": {
            "inner_pause_cap_seconds": 0.33,
            "inner_pause_floors_seconds": {"。？！": 0.31, "，": 0.155},
            "inner_breath": {"longest_group_seconds": 7.5, "pause_seconds": 0.26},
            "thought_level_tolerance_db": 0.75,
            "thought_boundary_ratio": 1.2,
            "thought_boundary_margin_seconds": 0.04,
            "coda_thought_pause_seconds": 1.4,
        },
        "en": {
            "inner_pause_cap_seconds": 0.33,
            "inner_pause_caps_seconds": {",": 0.22},
            "thought_level_tolerance_db": 0.75,
            "thought_boundary_ratio": 1.62,
            "coda_thought_pause_seconds": 0.9,
        },
    }
    for code, policy in policies.items():
        put(root / Edition(code).script, {"voice_performance": policy})
        put(
            Edition(code).audio_assembly,
            {"program_level": {"policy": {"integrated_lufs": -16.5}}},
        )
    put(
        root / "content/source-manifest.json",
        {
            "repository": "https://example.test/guidelines",
            "commit": "abc",
            "members": [{"path": path} for path in sources.SOURCES],
        },
    )
    monkeypatch.setenv(sources.CHECKOUT, "/source/guidelines")
    previous = root / "build/evidence/reviews/round-4"
    findings = [
        {"id": "R4-1", "severity": "minor"},
        {"id": "R4-2", "severity": "note"},
        {"id": "R4-3", "severity": "note"},
    ]
    review(previous, "zh", findings=findings)
    review(previous, "en")
    (previous / "zh").mkdir()
    out = root / "build/evidence/reviews/round-5"
    changes = put(root / "changes.md", "- Repairs: 07.6 names all seven checks.\n\n")
    with pytest.raises(ReviewError, match="missing build/evidence/reviews/round-5/pronun"):
        review_round.prompts(previous, out, changes)
    for name in review_round.ROUND_INPUTS:
        put(out / name, {})
    assert review_round.prompts(previous, out, changes) == {
        "prompts": [
            "build/evidence/reviews/round-5/prompt-zh.md",
            "build/evidence/reviews/round-5/prompt-en.md",
        ]
    }
    zh, en = ((out / f"prompt-{code}.md").read_text() for code in CODES)
    uhd = Edition("zh").film("uhd")
    for expected in (
        f"- {uhd} (SHA-256 {repository.sha(uhd)})",
        "business source /source/guidelines. ",
        (
            "the seven documents in /source/guidelines/docs/ (charter, decide, data, deliver, "
            "human-agent, communicate, evolve)."
        ),
        (
            "ROOT/build/evidence/reviews/round-4/zh-review.md and "
            "ROOT/build/evidence/reviews/round-4/review-zh.json "
            "(findings: minor R4-1; note R4-2, R4-3)."
        ),
        "independently.\n- Repairs: 07.6 names all seven checks.\n- Pronunciation plan",
        "Write only under ROOT/build/evidence/reviews/round-5/.",
        "ROOT/build/evidence/reviews/round-5/measurements.json: speaking rate",
        "inner cap (0.33 s Chinese; 0.33 s (0.22 s at commas) English)",
        "floors (Chinese 。？！ 0.31 s, ， 0.155 s; English none declared)",
        "breath group (Chinese 7.5 s with a 0.26 s pause; English none declared)",
        "tolerance (0.75 dB Chinese, 0.75 dB English)",
        "boundary ratio and margin (1.2 and 0.04 s Chinese, 1.62 and 0.00 s English)",
        "coda pause (1.40 s Chinese, 0.90 s English)",
        "both soundtracks reach -16.5 LUFS integrated",
        "working files are in ROOT/build/evidence/reviews/round-4/zh/; you may copy",
        "\n1. subject_and_faithfulness: DDWG remains the subject;",
        "\n8. credits_and_deliverable_craft: covers and Yang HENG metadata;",
        "and ROOT/build/evidence/reviews/round-5/review-zh.json with:",
        "Put working files under ROOT/build/evidence/reviews/round-5/zh/.",
        # The delivery format is the specification's.
        (
            f"Each edition: exactly {specification.DURATION} s, 16:9 pure 2D, "
            f"{specification.FPS} fps, UHD master and a captioned 1080p viewing edition, "
            f"{specification.RATE // 1000} kHz stereo narration, no music."
        ),
    ):
        assert expected in zh
    assert "(no findings)" in en
    assert "working files are in" not in en
    assert "the Chinese soundtrack ROOT/build/artifacts/film/zh/ddwg-zh-narration.wav" in en
    for text in (zh, en):
        assert not re.search(r"\{[a-z_]+\}", text)
        assert "runtime/work" not in text
        # Both prompts carry the score anchors and the accepted specification's path.
        assert "\n- 97-100: nothing a careful first-time viewer would notice." in text
        accepted = "`ROOT/openspec/specs/film-production/spec.md` is the accepted specification."
        assert accepted in text
    monkeypatch.setattr(specification, "DURATION", 1260)
    monkeypatch.setattr(specification, "RATE", 44100)
    review_round.prompts(previous, out, changes)
    assert "exactly 1260 s, 16:9 pure 2D" in (out / "prompt-en.md").read_text()
    assert "44.1 kHz stereo narration" in (out / "prompt-en.md").read_text()
    Edition("en").film("uhd").unlink()
    with pytest.raises(
        ReviewError, match=re.escape("missing build/artifacts/film/en/ddwg-en-uhd.mp4")
    ):
        review_round.prompts(previous, out, changes)


def test_record_writes_reviews_that_verify_film_accepts(root, review, put, capsys):
    for code in CODES:
        put(root / Edition(code).script, f"{code} script")
    put(root / picture_rendering.COMPOSITION_SCRIPT, "composition")
    folder = root / "build/evidence/reviews/round-5"
    relative = [
        {"path": str(film.relative_to(root)), "sha256": repository.sha(film)}
        for film in Edition("en").films
    ]
    review(folder, "zh", findings=[{"id": "R5-1", "severity": "minor"}])
    review(folder, "en", media=relative, overall=93.0)
    with pytest.raises(
        ReviewError, match=re.escape("en: reported overall 93.0 is not the mean 92.0")
    ):
        review_round.review_records(folder)
    review(folder, "en", media=relative)
    put(Edition("zh").film("uhd"), "zh uhd changed")
    with pytest.raises(ReviewError, match="zh: reviewed media differ"):
        review_round.review_records(folder)
    review(folder, "zh", findings=[{"id": "R5-1", "severity": "minor"}])
    review_round.main(["record", "--round-dir", str(folder), "--dry-run"])
    assert json.loads(capsys.readouterr().out)["dry_run"] is True
    assert not (root / "evidence").exists()

    review_round.main(["record", "--round-dir", str(folder)])
    assert json.loads(capsys.readouterr().out) == {
        "dry_run": False,
        "editions": [
            {"language": "zh", "overall": 92.0, "minimum": 92, "material": 0},
            {"language": "en", "overall": 92.0, "minimum": 92, "material": 0},
        ],
    }
    record = json.loads(Edition("zh").production_review.read_text())
    assert list(record) == [
        "schema_version",
        "language",
        "reviewer",
        "recorded_at",
        "media",
        "script_sha256",
        "composition_sha256",
        "scores",
        "overall",
        "findings",
        "human_listening",
        "report",
        "source_review",
    ]
    films = Edition("zh").films
    assert record["media"] == [
        {"path": str(film.relative_to(root)), "sha256": repository.sha(film)}
        for film in films[::-1]
    ]
    assert record["human_listening"]["checklist"] == ["Listen to 24.3 in its clause."]
    assert record["source_review"] == {
        "path": "build/evidence/reviews/round-5/review-zh.json",
        "sha256": repository.sha(folder / "review-zh.json"),
    }
    for code in CODES:
        edition = Edition(code)
        accepted = delivery_verification.verify_review(edition, sorted(edition.films))
        assert accepted["overall"] == 92.0
        assert root / accepted["path"] == edition.production_review


def test_record_requires_each_review_to_report_its_overall(root, review):
    # The prompt asks for the overall score, so a review without one is incomplete.
    folder = root / "build/evidence/reviews/round-5"
    review(folder, "zh", overall=None)
    review(folder, "en")
    with pytest.raises(ReviewError, match="zh: a review reports its overall score"):
        review_round.review_records(folder)
