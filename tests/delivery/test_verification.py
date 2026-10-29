"""The verifier's qualification of an edition and its command."""

import json

import pytest

import filmkit.delivery.verification as delivery_verification
import filmkit.production as production
import filmkit.repository as repository
from filmkit.delivery.verification import VerificationError


@pytest.fixture
def qualified(tmp_path, monkeypatch):
    """Every check of an edition replaced by a marker of its call."""
    monkeypatch.setattr(repository, "ROOT", tmp_path)
    for name in ("sources", "narration", "picture", "package"):
        monkeypatch.setattr(delivery_verification, f"verify_{name}", lambda *_, n=name: n)
    monkeypatch.setattr(
        delivery_verification, "verify_media", lambda _edition, path, size: (path.name, size)
    )
    monkeypatch.setattr(
        delivery_verification,
        "verify_review",
        lambda edition, files: (edition.code, [path.name for path in files]),
    )


@pytest.mark.usefixtures("qualified")
def test_an_edition_is_qualified_as_its_two_current_films():
    edition = production.Edition("en")
    films = list(reversed(edition.films))
    report = delivery_verification.qualify(edition, films)
    assert list(report) == [
        "verdict",
        "scope",
        "language",
        "sources",
        "narration",
        "picture",
        "package",
        "media",
        "review",
        "limits",
    ]
    assert (report["verdict"], report["scope"], report["language"]) == ("pass", "acceptance", "en")
    assert report["media"] == [
        ("ddwg-en-1080p-captioned.mp4", (1920, 1080)),
        ("ddwg-en-uhd.mp4", (3840, 2160)),
    ]
    assert report["review"] == ("en", sorted(film.name for film in films))
    technical = delivery_verification.qualify(edition, films, technical_only=True)
    assert (technical["scope"], technical["review"]) == ("technical", {"verdict": "not_reviewed"})
    for files in (
        films[:1],
        [*films, edition.artifacts / "ddwg-en-uhd.mp4"],
        [edition.artifacts.parent / "zh" / film.name for film in films],
        production.Edition("zh").films,
    ):
        with pytest.raises(VerificationError, match="two current delivered formats"):
            delivery_verification.qualify(edition, files)


@pytest.mark.usefixtures("qualified")
def test_the_command_prints_each_editions_report_and_writes_nothing(tmp_path, capsys):
    films = [str(film) for code in production.CODES for film in production.Edition(code).films]
    delivery_verification.main(["--read-only", "--technical-only", "--language", "all", *films])
    reports = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [(report["language"], report["scope"]) for report in reports] == [
        ("zh", "technical"),
        ("en", "technical"),
    ]
    delivery_verification.main(["--language", "en", *films[2:]])
    (report,) = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert (report["language"], report["scope"]) == ("en", "acceptance")
    assert list(tmp_path.rglob("*")) == []
    # Without named films, each selected edition's current delivered films are verified.
    delivery_verification.main(["--technical-only", "--language", "all"])
    reports = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [report["language"] for report in reports] == ["zh", "en"]
    delivery_verification.main(["--technical-only", "--language", "en"])
    (report,) = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    english = sorted(film.name for film in production.Edition("en").films)
    assert [name for name, _size in report["media"]] == english
    with pytest.raises(VerificationError, match="both current edition pairs"):
        delivery_verification.main(["--language", "all", *films[1:]])
    with pytest.raises(SystemExit):
        delivery_verification.main(["--language", "fr", *films])
