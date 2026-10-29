"""The verifier's binding of the rendered picture, its geometry and its shot plan."""

import pytest

import ddwg_film.delivery.verification as delivery_verification
import ddwg_film.repository as repository
from ddwg_film.delivery.verification import VerificationError


def test_the_current_picture_passes(inputs):
    edition = inputs.edition
    assert delivery_verification.verify_picture(edition) == {
        "picture_sha256": repository.sha(edition.picture),
        "geometry_frames": 60,
        "browser": "Chromium",
    }


# The short films last two seconds at 60 fps, so geometry of every second frame checks 60.
@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("format", "frame-audit"),
        ("passed", False),
        ("findings", [{"frame": 12}]),
        ("errors", ["timeout"]),
        ("index_sha256", "0" * 64),
        ("width", 1920),
        ("duration", 3),
        ("fps", 30),
        ("step_frames", 3),
        ("checked", 120),
    ],
)
def test_geometry_that_does_not_cover_the_staged_film_is_refused(inputs, key, value):
    inputs.change(inputs.edition.picture_geometry, key, value=value)
    with pytest.raises(VerificationError, match="does not cover the current staged film"):
        delivery_verification.verify_picture(inputs.edition)


def test_a_restaged_picture_is_refused(inputs):
    (inputs.edition.picture_stage / "index.html").write_text("<html>restaged</html>")
    with pytest.raises(VerificationError, match="does not cover the current staged film"):
        delivery_verification.verify_picture(inputs.edition)


@pytest.mark.parametrize("key", ["script_sha256", "composition_sha256", "timeline_sha256"])
def test_a_shot_plan_of_other_picture_inputs_is_refused(inputs, key):
    inputs.change(inputs.root / inputs.edition.shot_plan, key, value="0" * 64)
    with pytest.raises(VerificationError, match="Shot plan differs"):
        delivery_verification.verify_picture(inputs.edition)
