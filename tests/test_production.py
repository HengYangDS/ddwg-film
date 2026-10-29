"""Where each edition's generated plans and records live."""

import filmkit.repository as repository
from filmkit.production import CODES, Edition


def test_generated_plans_and_records_live_under_build():
    for code in CODES:
        edition = Edition(code)
        for path in (edition.shot_plan, edition.production_review):
            assert path.is_relative_to(repository.ROOT / "build"), path
