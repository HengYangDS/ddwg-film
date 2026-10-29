"""The pinned canonical sources and their check against a local clone."""

import json
import subprocess

import pytest

import ddwg_film.repository as repository
import ddwg_film.sources as sources
from ddwg_film.sources import SourceError


@pytest.fixture
def pinned(tmp_path, monkeypatch):
    """A source clone holding the seven documents at one commit, and a manifest pinning them."""
    root = tmp_path / "film"
    monkeypatch.setattr(repository, "ROOT", root)
    monkeypatch.delenv(sources.CHECKOUT, raising=False)
    clone = tmp_path / "guidelines"
    (clone / "docs").mkdir(parents=True)
    for path in sources.SOURCES:
        (clone / path).write_text(f"# {path}\n")

    def git(*arguments):
        return subprocess.run(
            ["git", "-C", str(clone), *arguments], capture_output=True, check=True, text=True
        ).stdout.strip()

    git("init", "-q")
    git("add", ".")
    git("-c", "user.name=t", "-c", "user.email=t@example.test", "commit", "-qm", "docs")
    members = [{"path": path, "sha256": repository.sha(clone / path)} for path in sources.SOURCES]
    manifest = {"repository": "https://example.test/guidelines", "commit": git("rev-parse", "HEAD")}

    def write(rows=members):
        (root / "content").mkdir(parents=True, exist_ok=True)
        (root / sources.MANIFEST).write_text(json.dumps({**manifest, "members": rows}))

    write()
    return clone, members, write


@pytest.mark.usefixtures("pinned")
def test_without_a_clone_the_documents_are_reported_unchecked():
    assert sources.verify()["documents"] == "not_checked"
    assert sources.location().endswith("/tree/" + sources.manifest()["commit"])


def test_a_clone_verifies_each_document_at_the_pinned_commit(pinned, monkeypatch):
    clone, _members, _write = pinned
    monkeypatch.setenv(sources.CHECKOUT, str(clone))
    assert sources.verify()["documents"] == "verified"
    assert sources.location() == str(clone)
    # A later working-tree edit does not move the pinned commit.
    (clone / "docs/evolve.md").write_text("# changed\n")
    assert sources.verify()["documents"] == "verified"


def test_a_document_that_differs_at_the_commit_is_refused(pinned, monkeypatch):
    clone, members, write = pinned
    monkeypatch.setenv(sources.CHECKOUT, str(clone))
    write([*members[:-1], {**members[-1], "sha256": "0" * 64}])
    with pytest.raises(SourceError, match=r"Canonical source differs: docs/evolve\.md"):
        sources.verify()


def test_a_manifest_without_the_seven_documents_is_refused(pinned):
    _clone, members, write = pinned
    write(members[1:])
    with pytest.raises(SourceError, match="seven canonical documents"):
        sources.verify()
