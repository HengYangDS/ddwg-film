"""The supply task: the browser build and model snapshots it installs and checks."""

import json

import pytest

import filmkit.picture.rendering as picture_rendering
import filmkit.repository as repository
import filmkit.supply as supply
from filmkit.narration.snapshots import DOWNLOAD_RECORDS, Snapshot
from filmkit.supply import SupplyError


@pytest.fixture
def root(tmp_path, monkeypatch):
    """A repository root whose browser installer and model downloads are stand-ins."""
    monkeypatch.setattr(repository, "ROOT", tmp_path)
    monkeypatch.delenv("FILM_CHROMIUM_PATH", raising=False)
    calls = []
    browser = b"browser build"

    def install(command, **_options):
        calls.append(("install", command))
        path = picture_rendering.supplied_browser()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(browser)

    def download(repo, *, revision, allow_patterns, local_dir):
        calls.append(("download", repo, revision, allow_patterns, local_dir))
        (local_dir / DOWNLOAD_RECORDS).mkdir(parents=True, exist_ok=True)
        (local_dir / "model.safetensors").write_bytes(repo.encode())
        digest = repository.content_sha(repo.encode())
        (local_dir / DOWNLOAD_RECORDS / "model.safetensors.metadata").write_text(
            f"{revision}\n{digest}\n"
        )

    monkeypatch.setattr(repository, "run", install)
    monkeypatch.setattr(supply, "snapshot_download", download)
    monkeypatch.setattr(picture_rendering, "BROWSER_SHA256", repository.content_sha(browser))
    snapshots = tuple(
        Snapshot(
            name,
            f"org/{name}",
            "c" * 40,
            ("*.safetensors",),
            f"build/runtime/tool-cache/narration-{name}",
            {"model.safetensors": repository.content_sha(f"org/{name}".encode())},
        )
        for name in ("voice", "recognizer")
    )
    monkeypatch.setattr(supply, "SNAPSHOTS", snapshots)
    return tmp_path, calls


def test_the_supply_installs_and_checks_the_browser_and_every_model(root, capsys):
    folder, calls = root
    supply.main([])
    product, version = picture_rendering.BROWSER
    install = calls[0][1]
    assert install[1:] == [
        "install",
        f"{product}@{version}",
        "--path",
        str(folder / "build/runtime/tool-cache/browsers"),
    ]
    assert [call[1:4] for call in calls[1:]] == [
        ("org/voice", "c" * 40, ["*.safetensors"]),
        ("org/recognizer", "c" * 40, ["*.safetensors"]),
    ]
    report = json.loads(capsys.readouterr().out)
    assert report["browser"]["build"] == f"{product}@{version}"
    assert [model["repo"] for model in report["models"]] == ["org/voice", "org/recognizer"]


@pytest.mark.usefixtures("root")
def test_a_browser_build_of_other_bytes_is_refused(monkeypatch):
    monkeypatch.setattr(picture_rendering, "BROWSER_SHA256", "0" * 64)
    with pytest.raises(SupplyError, match="browser build differs from the pinned SHA-256"):
        supply.main([])
