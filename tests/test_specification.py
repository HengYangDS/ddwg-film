"""The delivery format's values that the editions' scripts declare."""

import json

import pytest

import filmkit.repository as repository
import filmkit.specification as specification
from filmkit.production import CODES, Edition


def test_scripts_that_disagree_refuse(tmp_path, monkeypatch):
    monkeypatch.setattr(repository, "ROOT", tmp_path)
    for code, author in zip(CODES, ("One Author", "Another Author"), strict=True):
        script = tmp_path / Edition(code).script
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text(json.dumps({"author": author, "chapters": [{}, {}]}))
    assert specification.declared("chapters", len) == 2
    with pytest.raises(ValueError, match="different author values"):
        specification.declared("author", str)


def test_the_engine_renders_60_fps_only():
    assert specification.rendered_rate(60) == 60
    with pytest.raises(ValueError, match="60 fps films, not the 30 fps"):
        specification.rendered_rate(30)
