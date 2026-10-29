"""The verifier's acceptance of the recorded independent review."""

import json

import pytest

import filmkit.delivery.verification as delivery_verification
import filmkit.picture.rendering as picture_rendering
import filmkit.production as production
import filmkit.repository as repository
import filmkit.review.record as review_record
from filmkit.delivery.verification import VerificationError


@pytest.fixture
def current_review(tmp_path, monkeypatch):
    monkeypatch.setattr(repository, "ROOT", tmp_path)
    edition = production.Edition("zh")
    for name, body in (
        ("content/film-script.json", "{}"),
        (str(picture_rendering.COMPOSITION_SCRIPT), "/* film */"),
        ("evidence/reviews/production-review.md", "# Review\n"),
        ("build/artifacts/film/zh/ddwg-zh-uhd.mp4", "uhd"),
        ("build/artifacts/film/zh/ddwg-zh-1080p-captioned.mp4", "viewing"),
    ):
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(body)
    files = sorted((tmp_path / "build/artifacts/film/zh").glob("*.mp4"))
    record = {
        "schema_version": 2,
        "language": "zh",
        "reviewer": "independent reviewer",
        "media": [
            {"path": str(f.relative_to(tmp_path)), "sha256": repository.sha(f)} for f in files
        ],
        "script_sha256": repository.sha(tmp_path / edition.script),
        "composition_sha256": repository.sha(tmp_path / picture_rendering.COMPOSITION_SCRIPT),
        "scores": dict.fromkeys(review_record.DIMENSIONS, 96),
        "overall": 96.0,
        "findings": [{"severity": "minor"}],
        "human_listening": {"state": "not_performed"},
        "report": {
            "path": "evidence/reviews/production-review.md",
            "sha256": repository.sha(tmp_path / "evidence/reviews/production-review.md"),
        },
    }
    path = tmp_path / "evidence/reviews/production-review.json"

    def check(**changes):
        path.write_text(json.dumps({**record, **changes}))
        return delivery_verification.verify_review(edition, files)

    return check, record, files


def test_review_accepts_only_current_media_above_thresholds(current_review):
    check, record, files = current_review
    accepted = check()
    assert (accepted["overall"], accepted["minimum_dimension"]) == (96.0, 96)
    # Every dimension at 90 qualifies; 95 overall is a later plan, not this gate.
    floor = check(scores=dict.fromkeys(review_record.DIMENSIONS, 90), overall=90.0)
    assert (floor["overall"], floor["minimum_dimension"]) == (90.0, 90)
    low = {**record["scores"], "composition_and_typography": 89}
    with pytest.raises(VerificationError, match="below the acceptance thresholds"):
        check(scores=low, overall=round(sum(low.values()) / len(low), 1))
    with pytest.raises(VerificationError, match="mean of its dimensions"):
        check(overall=97.0)
    missing = dict(list(record["scores"].items())[1:])
    with pytest.raises(VerificationError, match="every declared dimension"):
        check(scores=missing)
    with pytest.raises(VerificationError, match="unresolved material finding"):
        check(findings=[{"severity": "material"}])
    with pytest.raises(VerificationError, match="current delivered edition"):
        check(schema_version=1)
    files[0].write_text("re-encoded")
    with pytest.raises(VerificationError, match="current delivered edition"):
        check()
