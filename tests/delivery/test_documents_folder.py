"""Exercise delivery of the Documents folder: source binding, replacement and readback."""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import ddwg_film.delivery.documents_folder as delivery_documents_folder
import ddwg_film.repository as repository
from ddwg_film.delivery.documents_folder import DeliveryRefusedError
from ddwg_film.production import CODES


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_the_delivery_members_are_the_entry_page_then_each_editions_films_and_viewing_package():
    root = Path("/root")
    assert [path for _, path in delivery_documents_folder.plan(root)] == [
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


def test_first_delivery_reads_every_member_back(film):
    root, destination = film
    report = delivery_documents_folder.deliver(root, destination, None)
    members = [path for _, path in delivery_documents_folder.plan(root)]
    assert len(members) == 21
    assert list(report) == [
        "destination",
        "delivered_at",
        "members",
        "all_match",
        "foreign_preserved",
        "unexpected",
        "package_records",
    ]
    assert report["all_match"]
    assert report["unexpected"] == report["foreign_preserved"] == []
    assert report["members"][1] == {
        "path": "zh/ddwg-zh-uhd.mp4",
        "source": "build/artifacts/film/zh/ddwg-zh-uhd.mp4",
        "sha256": sha("current zh/ddwg-zh-uhd.mp4\n"),
        "bytes": len("current zh/ddwg-zh-uhd.mp4\n"),
        "mode": oct((root / "build/artifacts/film/zh/ddwg-zh-uhd.mp4").stat().st_mode & 0o777),
        "matches_source": True,
    }
    assert [row["path"] for row in report["members"]] == members
    assert json.loads((root / delivery_documents_folder.READBACK).read_text()) == report
    assert film.tree(destination) == {path: f"current {path}\n" for path in members}


def test_the_readback_records_the_package_records_that_bound_the_sources(film):
    root, destination = film
    report = delivery_documents_folder.deliver(root, destination, None)
    paths = [path for code in CODES for path in film.records(code)]
    assert [record["path"] for record in report["package_records"]] == [
        path.relative_to(root).as_posix() for path in paths
    ]
    assert [record["sha256"] for record in report["package_records"]] == [
        file_sha(path) for path in paths
    ]
    films, viewing = report["package_records"][:2]
    assert films["binds"] == {
        f"zh/ddwg-zh-{kind}.mp4": sha(f"current zh/ddwg-zh-{kind}.mp4\n")
        for kind in ("uhd", "1080p-captioned")
    }
    assert viewing["binds"]["index.html"] == sha("current index.html\n")
    assert len(viewing["binds"]) == 9
    bound = {path for record in report["package_records"] for path in record["binds"]}
    assert bound == {row["path"] for row in report["members"]}


def test_deliver_refuses_sources_that_their_package_records_do_not_hold(film):
    root, destination = film
    # A film left by an interrupted packaging step: in place, but not the recorded bytes.
    (root / "build/artifacts/film/zh/ddwg-zh-uhd.mp4").write_text("unrecorded film\n")
    with pytest.raises(
        DeliveryRefusedError,
        match=r"differ from their package records: \['zh/ddwg-zh-uhd\.mp4'\]",
    ):
        delivery_documents_folder.plan_delivery(root, destination, None)
    with pytest.raises(DeliveryRefusedError, match="differ from their package records"):
        delivery_documents_folder.deliver(root, destination, None)
    assert not destination.exists()
    assert not (root / delivery_documents_folder.READBACK).exists()
    film.bind()
    films, viewing = film.records("en")
    body = json.loads(viewing.read_text())
    body["language_index"]["sha256"] = sha("older entry page\n")
    viewing.write_text(json.dumps(body))
    with pytest.raises(DeliveryRefusedError, match=r"package records: \['index\.html'\]"):
        delivery_documents_folder.deliver(root, destination, None)
    body["language_index"]["path"] = "src/delivery-index.html"
    viewing.write_text(json.dumps(body))
    body = json.loads(films.read_text())
    body["editions"].pop()
    films.write_text(json.dumps(body))
    # The zh viewing package still binds the entry page; the en viewing film is unrecorded.
    with pytest.raises(DeliveryRefusedError, match=r"\['en/ddwg-en-1080p-captioned\.mp4'\]"):
        delivery_documents_folder.deliver(root, destination, None)
    films.unlink()
    with pytest.raises(DeliveryRefusedError, match=r"No package record at .*en/film-package"):
        delivery_documents_folder.deliver(root, destination, None)
    assert not destination.exists()


def test_a_source_changed_during_the_delivery_fails_its_readback(film, monkeypatch):
    root, destination = film
    original = delivery_documents_folder.place

    def change_then_place(source, target):
        if target.name == "ddwg-en.srt":
            source.write_text("changed after the binding check\n")
        original(source, target)

    monkeypatch.setattr(delivery_documents_folder, "place", change_then_place)
    report = delivery_documents_folder.deliver(root, destination, None)
    rows = {row["path"]: row for row in report["members"]}
    assert rows["en/ddwg-en.srt"]["matches_source"]
    assert not report["all_match"]


def test_replacing_a_delivery_requires_its_retention(film):
    root, destination = film
    delivery_documents_folder.deliver(root, destination, None)
    before = film.tree(destination)
    film.better()
    with pytest.raises(DeliveryRefusedError, match="retain it and pass --retention"):
        delivery_documents_folder.deliver(root, destination, None)
    assert film.tree(destination) == before


def test_readback_reports_changed_members_and_unexpected_entries(film):
    root, destination = film
    delivery_documents_folder.deliver(root, destination, None)
    (destination / "zh/index.html").chmod(0o600)
    (destination / "en/ddwg-en.vtt").write_text("tampered\n")
    (destination / "en/chapters.json").unlink()
    film.write(destination / "en/ddwg-en 2.vtt", "copy\n")
    report = delivery_documents_folder.readback(root, destination)
    rows = {row["path"]: row for row in report["members"]}
    assert [path for path, row in rows.items() if not row["matches_source"]] == [
        "zh/index.html",
        "en/ddwg-en.vtt",
        "en/chapters.json",
    ]
    assert rows["zh/index.html"]["mode"] == "0o600"
    assert rows["en/chapters.json"]["sha256"] is None
    assert report["unexpected"] == ["en/ddwg-en 2.vtt"]
    assert "package_records" not in report
    assert not report["all_match"]


def test_links_and_displaced_members_are_refused(film):
    root, destination = film
    delivery_documents_folder.deliver(root, destination, None)
    (destination / "zh/extra.mp4").symlink_to(root / "build/artifacts/film/zh/ddwg-zh-uhd.mp4")
    with pytest.raises(DeliveryRefusedError, match=r"not a regular file: zh/extra\.mp4"):
        delivery_documents_folder.retain(root, destination, "previous", film.package)
    with pytest.raises(DeliveryRefusedError, match=r"not a regular file: zh/extra\.mp4"):
        delivery_documents_folder.deliver(root, destination, None)
    (destination / "zh/extra.mp4").unlink()
    (destination / "old").symlink_to(root, target_is_directory=True)
    with pytest.raises(DeliveryRefusedError, match="entry is a link: old"):
        delivery_documents_folder.deliver(root, destination, None)
    (destination / "old").unlink()
    (destination / "en/index.html").unlink()
    (destination / "en/index.html").mkdir()
    with pytest.raises(DeliveryRefusedError, match=r"member is a folder: en/index\.html"):
        delivery_documents_folder.deliver(root, destination, None)
    (destination / "en/index.html").rmdir()
    (destination / "en").rename(destination / "en-moved")
    film.write(destination / "en", "a file in the edition folder's place\n")
    with pytest.raises(DeliveryRefusedError, match="edition folder is a file: en"):
        delivery_documents_folder.deliver(root, destination, None)


@pytest.mark.skipif(os.geteuid() == 0, reason="the superuser reads folders without permission")
def test_unreadable_folders_are_refused(film):
    root, destination = film
    delivery_documents_folder.deliver(root, destination, None)
    locked = destination / "locked"
    locked.mkdir(mode=0o000)
    try:
        with pytest.raises(DeliveryRefusedError, match="Cannot read the destination"):
            delivery_documents_folder.readback(root, destination)
    finally:
        locked.chmod(0o755)


def test_delivery_command_fails_when_the_readback_differs(film, monkeypatch, capsys):
    root, destination = film
    monkeypatch.setattr(repository, "ROOT", root)
    monkeypatch.setattr(
        delivery_documents_folder, "place", lambda _source, target: film.write(target, "lost\n")
    )
    with pytest.raises(SystemExit) as failure:
        delivery_documents_folder.main(["deliver", "--destination", str(destination)])
    assert failure.value.code == 1
    assert json.loads(capsys.readouterr().out) == {
        "members": 21,
        "all_match": False,
        "unexpected": [],
    }
    assert not json.loads((root / delivery_documents_folder.READBACK).read_text())["all_match"]


def test_the_commands_print_dry_runs_and_refuse_with_the_refusal_text(film, monkeypatch, capsys):
    root, destination = film
    monkeypatch.setattr(repository, "ROOT", root)
    target = ["--destination", str(destination)]
    delivery_documents_folder.main(["deliver", "--dry-run", *target])
    assert json.loads(capsys.readouterr().out)["remove"] == []
    assert not destination.exists()
    delivery_documents_folder.main(["deliver", *target])
    capsys.readouterr()
    keep = ["retain", "--name", "previous", "--package", str(film.package), *target]
    delivery_documents_folder.main([*keep, "--dry-run"])
    assert json.loads(capsys.readouterr().out)["dry_run"] is True
    assert not (root / delivery_documents_folder.PREDECESSORS).exists()
    with pytest.raises(SystemExit) as refusal:
        delivery_documents_folder.main(["deliver", *target])
    assert refusal.value.code == f"{destination} holds a delivery; retain it and pass --retention"


def test_a_refusal_exits_with_status_one_and_its_text_on_stderr(tmp_path):
    refused = subprocess.run(
        [
            sys.executable,
            "-m",
            "ddwg_film.delivery.documents_folder",
            "retain",
            "--name",
            "../outside",
            "--package",
            "build",
            "--destination",
            str(tmp_path / "Documents"),
        ],
        cwd=repository.ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert refused.returncode == 1
    assert refused.stderr == "A predecessor name is one folder name: '../outside'\n"
    assert refused.stdout == ""
