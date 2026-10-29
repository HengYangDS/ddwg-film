"""The production command runs each action's owner for the selected edition."""

import sys

import pytest

import filmkit.produce as produce
import filmkit.production as production
from filmkit.picture.rendering import PictureError


def test_an_action_runs_its_owner_for_the_selected_edition(monkeypatch):
    calls = []
    monkeypatch.setattr(produce, "assemble", calls.append)
    monkeypatch.setattr(sys, "argv", ["produce.py", "assemble", "--language", "en"])
    produce.main()
    assert calls == [production.Edition("en")]


def test_the_actions_are_the_documented_ones_in_order():
    assert [*produce.EDITION_ACTIONS] == [
        "select",
        "assemble",
        "refresh-captions",
        "stage-picture",
        "render-picture",
        "package-metadata",
        "validate-picture",
        "package-film",
    ]


def test_an_edition_action_passes_its_options_to_its_owner(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(produce, "stage_picture", lambda *arguments: calls.append(arguments))
    monkeypatch.setattr(produce, "render_picture", lambda *arguments: calls.append(arguments))
    output = tmp_path / "stage"
    stage = ["--output", str(output), "--duration", "60", "--width", "1920", "--height", "1080"]
    produce.main(["stage-picture", "--language", "zh", *stage, "--start", "12.5"])
    hyperframes = tmp_path / "hyperframes"
    hyperframes.write_text("#!/bin/sh\n")
    produce.main(["render-picture", "--language", "en", "--hyperframes", str(hyperframes)])
    assert calls == [
        (production.Edition("zh"), output, 60, 1920, 1080, 12.5),
        (production.Edition("en"), hyperframes.resolve(), 10800),
    ]


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (["render-picture", "--language", "zh"], "render-picture requires --hyperframes"),
        (["select"], "the following arguments are required: --language"),
        (["render-picture"], "the following arguments are required: --language"),
        (["package-film", "--language", "fr"], "invalid choice: 'fr'"),
    ],
)
def test_an_action_refuses_without_its_required_inputs(monkeypatch, capsys, arguments, message):
    monkeypatch.setattr(sys, "argv", ["produce.py", *arguments])
    with pytest.raises(SystemExit) as stopped:
        produce.main()
    assert stopped.value.code == 2
    assert message in capsys.readouterr().err


def test_a_refusal_ends_the_command_with_the_action_and_its_reason(monkeypatch):
    def refuse(_edition):
        msg = "The render receipt does not bind the staged picture"
        raise PictureError(msg)

    monkeypatch.setattr(produce, "validate_picture", refuse)
    with pytest.raises(SystemExit) as stopped:
        produce.main(["validate-picture", "--language", "zh"])
    assert stopped.value.code == (
        "validate-picture: The render receipt does not bind the staged picture"
    )


def test_any_other_error_keeps_its_traceback(monkeypatch):
    def defect(_edition):
        msg = "a programming error"
        raise ValueError(msg)

    monkeypatch.setattr(produce, "package_film", defect)
    with pytest.raises(ValueError, match="a programming error"):
        produce.main(["package-film", "--language", "en"])
