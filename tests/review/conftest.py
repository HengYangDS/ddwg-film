"""Fixtures of the review tool tests: a repository root and a writer of its fixture files."""

import json

import pytest

import ddwg_film.repository as repository
from ddwg_film.production import CODES, Edition


def write_fixture(path, data):
    """Write bytes, text or JSON to a fixture file, creating its folders."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, dict):
        data = json.dumps(data, ensure_ascii=False)
    path.write_bytes(data if isinstance(data, bytes) else data.encode())
    return path


@pytest.fixture
def put():
    """Write bytes, text or JSON to a fixture file, creating its folders: `put(path, data)`."""
    return write_fixture


@pytest.fixture
def root(tmp_path, monkeypatch):
    """A repository root holding both packaged editions as tiny stand-in files."""
    root = tmp_path.resolve()
    monkeypatch.setattr(repository, "ROOT", root)
    for code in CODES:
        edition = Edition(code)
        for path in (*edition.films, edition.picture, edition.film_package):
            write_fixture(path, f"{code} {path.name}")
    return root
