"""Delivery of the Documents folder through rsync, and its readback through shasum."""

import hashlib
import json
from pathlib import Path

import pytest

import filmkit.delivery.documents_folder as delivery_documents_folder
import filmkit.repository as repository
from filmkit.delivery.documents_folder import DeliveryRefusedError
from filmkit.production import CODES


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def members(root: Path) -> list[str]:
    return [path for _, path in delivery_documents_folder.plan(root)]


def test_the_delivery_members_are_the_entry_page_then_each_editions_films_and_viewing_package():
    root = Path("/root")
    assert members(root) == [
        "index.html",
        *(
            f"{code}/{name}"
            for code in CODES
            for name in (
                f"ddwg-{code}-uhd.mp4",
                f"ddwg-{code}-1080p-captioned.mp4",
                "ddwg-cover.png",
                "ddwg-cover.jpg",
                f"ddwg-{code}.srt",
                f"ddwg-{code}.vtt",
                f"ddwg-{code}-transcript.md",
                "chapters.json",
                "chapters.ffmeta",
                "index.html",
            )
        ),
    ]
    sources = [source for source, _ in delivery_documents_folder.plan(root)]
    assert sources[0] == root / "build/artifacts/film/index.html"
    assert sources[1] == root / "build/artifacts/film/zh/ddwg-zh-uhd.mp4"


@pytest.mark.rsync
def test_a_first_delivery_places_and_reads_back_every_member(film):
    root, destination = film
    report = delivery_documents_folder.deliver(root, destination)
    assert len(report["members"]) == 21
    assert report["members"][1] == {
        "path": "zh/ddwg-zh-uhd.mp4",
        "sha256": sha("current zh/ddwg-zh-uhd.mp4\n"),
        "bytes": len("current zh/ddwg-zh-uhd.mp4\n"),
    }
    assert (report["all_match"], report["unexpected"], report["predecessors"]) == (True, [], None)
    assert report["film"] == {"slug": "ddwg", "duration": 1500}
    assert report["destination"] == str(destination)
    assert json.loads((root / delivery_documents_folder.READBACK).read_text()) == report
    assert film.tree(destination) == {path: f"current {path}\n" for path in members(root)}
    sums = (root / delivery_documents_folder.SUMS).read_text().splitlines()
    assert sums[0] == f"{sha('current index.html' + chr(10))}  index.html"


@pytest.mark.rsync
def test_a_delivery_keeps_what_it_replaces_or_removes_and_the_foreign_entries(film):
    root, destination = film
    delivery_documents_folder.deliver(root, destination)
    film.write(destination / "zh/ddwg-zh (copy).srt", "copy\n")
    film.write(destination / ".DS_Store", "finder\n")
    film.write(destination / "en/.DS_Store", "finder\n")
    film.write(destination / ".claude/state.json", "{}\n")
    film.better()
    report = delivery_documents_folder.deliver(root, destination)
    assert film.tree(destination) == {
        ".DS_Store": "finder\n",
        ".claude/state.json": "{}\n",
        "en/.DS_Store": "finder\n",
        **{path: f"better {path}\n" for path in members(root)},
    }
    kept = root / report["predecessors"]
    assert kept.is_relative_to(root / delivery_documents_folder.PREDECESSORS)
    assert film.tree(kept) == {
        "zh/ddwg-zh (copy).srt": "copy\n",
        **{path: f"current {path}\n" for path in members(root)},
    }
    assert report["all_match"]


@pytest.mark.rsync
def test_an_unchanged_delivery_replaces_nothing(film):
    root, destination = film
    delivery_documents_folder.deliver(root, destination)
    report = delivery_documents_folder.deliver(root, destination)
    assert (report["predecessors"], report["changes"]) == (None, [])


@pytest.mark.rsync
def test_a_dry_run_reports_the_changes_and_writes_nothing(film):
    root, destination = film
    report = delivery_documents_folder.deliver(root, destination, dry_run=True)
    assert report["dry_run"]
    assert "zh/ddwg-zh-uhd.mp4" in "\n".join(report["changes"])
    assert not destination.exists()
    assert not (root / delivery_documents_folder.READBACK).exists()


def test_missing_sources_refuse_before_any_change(film):
    root, destination = film
    (root / "build/artifacts/film/en/chapters.json").unlink()
    with pytest.raises(DeliveryRefusedError, match=r"Missing delivery sources: en/chapters\.json"):
        delivery_documents_folder.deliver(root, destination)
    assert not destination.exists()


@pytest.mark.rsync
def test_the_readback_refuses_a_member_that_differs_at_the_destination(film):
    root, destination = film
    delivery_documents_folder.deliver(root, destination)
    (destination / "en/ddwg-en.vtt").write_text("WEBVTT\n")
    with pytest.raises(DeliveryRefusedError, match=r"differs from its sources: en/ddwg-en\.vtt"):
        delivery_documents_folder.readback(root, destination)


@pytest.mark.rsync
def test_the_readback_refuses_an_entry_beside_the_members(film):
    root, destination = film
    delivery_documents_folder.deliver(root, destination)
    film.write(destination / "notes.txt", "notes\n")
    with pytest.raises(DeliveryRefusedError, match=r"unexpected entries: notes\.txt"):
        delivery_documents_folder.readback(root, destination)


def test_an_rsync_other_than_rsync_3_is_refused(film, monkeypatch):
    monkeypatch.setattr(delivery_documents_folder, "rsync_version", lambda: "openrsync 2.6.9")
    with pytest.raises(DeliveryRefusedError, match="rsync 3 is required"):
        delivery_documents_folder.deliver(*film)
    assert not film.destination.exists()


@pytest.mark.rsync
def test_the_command_reports_the_readback_summary(film, monkeypatch, capsys):
    monkeypatch.setattr(repository, "ROOT", film.root)
    delivery_documents_folder.main(["--destination", str(film.destination)])
    assert json.loads(capsys.readouterr().out) == {
        "members": 21,
        "all_match": True,
        "predecessors": None,
    }
    film.write(film.root / "build/artifacts/film/index.html", "edited\n")
    delivery_documents_folder.main(["--destination", str(film.destination)])
    summary = json.loads(capsys.readouterr().out)
    assert summary["predecessors"].startswith(str(delivery_documents_folder.PREDECESSORS))
    (film.root / "build/artifacts/film/en/index.html").unlink()
    with pytest.raises(SystemExit, match="Missing delivery sources"):
        delivery_documents_folder.main(["--destination", str(film.destination)])
