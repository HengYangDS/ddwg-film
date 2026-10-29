"""The verifier's binding of both films and the viewing package to their inputs."""

import json

import pytest

import ddwg_film.delivery.packaging as delivery_packaging
import ddwg_film.delivery.verification as delivery_verification
from ddwg_film.delivery.verification import VerificationError


def test_the_current_packages_pass(inputs):
    assert delivery_verification.verify_package(inputs.edition) == {
        "films": ["ddwg-zh-1080p-captioned.mp4", "ddwg-zh-uhd.mp4"],
        "viewing_members": 8,
    }


def film_changed(inputs):
    inputs.edition.film("uhd").write_text("re-encoded\n")


def edition_repeated(inputs):
    films = json.loads(inputs.edition.film_package.read_text())
    films["editions"][1] = films["editions"][0]
    inputs.edition.film_package.write_text(json.dumps(films))


def member_changed(inputs):
    (inputs.edition.artifacts / "ddwg-zh.vtt").write_text("WEBVTT\n")


def cover_differs_from_its_source(inputs):
    (inputs.root / inputs.edition.cover).write_bytes(b"another cover")


def entry_page_changed(inputs):
    (inputs.root / delivery_packaging.LANGUAGE_INDEX).write_text("<another entry page>")


def entry_template_changed(inputs):
    (inputs.root / delivery_packaging.INDEX).write_text("<another template>")


def films(*keys, value):
    return lambda inputs: inputs.change(inputs.edition.film_package, *keys, value=value)


def viewing(*keys, value):
    return lambda inputs: inputs.change(inputs.edition.viewing_package, *keys, value=value)


@pytest.mark.parametrize(
    ("damage", "message"),
    [
        (films("script_sha256", value="0"), "Film package differs"),
        (films("soundtrack_sha256", value="0"), "Film package differs"),
        (films("picture_sha256", value="0"), "Film package differs"),
        (films("cover_sha256", value="0"), "Film package differs"),
        (films("chapters_sha256", value="0"), "Film package differs"),
        (films("editions", "1", "path", value="ddwg-zh-1080p.mp4"), "Film package differs"),
        (edition_repeated, "Film package differs"),
        (film_changed, "Film package differs"),
        (viewing("members", "3", "path", value="ddwg-zh.ass"), "declared viewing members"),
        (viewing("members", value=[]), "declared viewing members"),
        (viewing("script_sha256", value="0"), "Viewing package differs"),
        (viewing("timeline_sha256", value="0"), "Viewing package differs"),
        (viewing("player_source_sha256", value="0"), "Viewing package differs"),
        (viewing("author", value="Someone else"), "Viewing package differs"),
        (viewing("chapters", value=7), "Viewing package differs"),
        (member_changed, "Viewing package differs"),
        (cover_differs_from_its_source, "Viewing package differs"),
        (viewing("language_index", "source", value="src/delivery-index.html"), "language index"),
        (viewing("language_index", "source_sha256", value="0"), "language index"),
        (viewing("language_index", "path", value="build/index.html"), "language index"),
        (viewing("language_index", "sha256", value="0"), "language index"),
        (viewing("language_index", "languages", value=["zh"]), "language index"),
        (viewing("language_index", value={}), "language index"),
        (entry_page_changed, "language index"),
        (entry_template_changed, "language index"),
    ],
)
def test_package_refusals(inputs, damage, message):
    damage(inputs)
    with pytest.raises(VerificationError, match=message):
        delivery_verification.verify_package(inputs.edition)
