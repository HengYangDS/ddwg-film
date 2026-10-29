"""The verifier's bilingual film set."""

import pytest

import ddwg_film.delivery.verification as delivery_verification
import ddwg_film.production as production
import ddwg_film.repository as repository
from ddwg_film.delivery.verification import VerificationError


def test_bilingual_acceptance_needs_exactly_both_current_edition_pairs(tmp_path, monkeypatch):
    monkeypatch.setattr(repository, "ROOT", tmp_path)
    films = [film for code in production.CODES for film in production.Edition(code).films]
    groups = delivery_verification.bilingual_inputs(list(reversed(films)))
    assert groups == {code: production.Edition(code).films for code in production.CODES}
    for files in (
        films[1:],
        [*films, tmp_path / "build/artifacts/film/zh/extra.mp4"],
        [*films[1:], films[1]],
        [tmp_path / "elsewhere" / film.name for film in films],
    ):
        with pytest.raises(VerificationError, match="both current edition pairs"):
            delivery_verification.bilingual_inputs(files)
