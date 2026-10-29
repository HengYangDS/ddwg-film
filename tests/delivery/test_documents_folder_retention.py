"""Exercise retention of the Documents delivery: rollback copies, set-aside films and refusals."""

import hashlib
import json
import os
from pathlib import Path

import pytest

import ddwg_film.delivery.documents_folder as delivery_documents_folder
from ddwg_film.delivery.documents_folder import DeliveryRefusedError


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_retain_binds_set_aside_films_and_copies_the_rest(film):
    root, destination = film
    delivery_documents_folder.deliver(root, destination, None)
    film.write(root / film.package / "zh/ddwg-zh-uhd.mp4", "current zh/ddwg-zh-uhd.mp4\n")
    film.write(root / film.package / "en/unrelated.mp4", "another film\n")
    film.write(destination / ".DS_Store", "finder\n")
    film.write(destination / ".claude/state", "app\n")
    summary = delivery_documents_folder.retain(root, destination, "previous", film.package)
    assert {key: summary[key] for key in ("members", "unexpected", "bound", "copied")} == {
        "members": 21,
        "unexpected": 0,
        "bound": 1,
        "copied": 20,
    }
    assert list(summary) == [
        "target",
        "members",
        "unexpected",
        "copied",
        "bound",
        "dry_run",
        "retention",
        "sha256",
    ]
    manifest = root / summary["retention"]
    assert summary["sha256"] == hashlib.sha256(manifest.read_bytes()).hexdigest()
    record = json.loads(manifest.read_text())
    assert list(record) == [
        "purpose",
        "consumer",
        "exit_condition",
        "created_at",
        "documents_root",
        "members",
        "unexpected",
    ]
    assert record["documents_root"] == str(destination)
    assert record["unexpected"] == []
    rows = {row["path"]: row for row in record["members"]}
    assert list(rows) == [path for _, path in delivery_documents_folder.plan(root)]
    assert rows["zh/ddwg-zh-uhd.mp4"]["source"] == "set-aside-package"
    assert rows["zh/ddwg-zh-uhd.mp4"]["copy"] == "build/runtime/work/package/zh/ddwg-zh-uhd.mp4"
    assert rows["en/index.html"] == {
        "path": "en/index.html",
        "sha256": sha("current en/index.html\n"),
        "bytes": len("current en/index.html\n"),
        "source": "copied-from-documents",
        "copy": "build/artifacts/film/predecessors/previous/en/index.html",
    }
    assert (root / rows["en/index.html"]["copy"]).read_text() == "current en/index.html\n"
    with pytest.raises(DeliveryRefusedError, match="already exists"):
        delivery_documents_folder.retain(root, destination, "previous", film.package)


def test_retain_refuses_bad_names_and_empty_destinations_and_dry_runs(film):
    root, destination = film
    with pytest.raises(DeliveryRefusedError, match="one folder name"):
        delivery_documents_folder.retain(root, destination, "../outside", film.package)
    with pytest.raises(DeliveryRefusedError, match="holds no delivery to retain"):
        delivery_documents_folder.retain(root, destination, "previous", film.package)
    with pytest.raises(DeliveryRefusedError, match="must be a folder under"):
        delivery_documents_folder.plan_retention(root, destination, "previous", Path("absent"))
    delivery_documents_folder.deliver(root, destination, None)
    summary = delivery_documents_folder.plan_retention(root, destination, "previous", film.package)
    assert summary == {
        "target": "build/artifacts/film/predecessors/previous",
        "members": 21,
        "unexpected": 0,
        "copied": 21,
        "bound": 0,
        "dry_run": True,
    }
    assert not (root / delivery_documents_folder.PREDECESSORS).exists()


def test_a_linked_set_aside_film_is_refused_and_the_previous_film_kept(film):
    root, destination = film
    delivery_documents_folder.deliver(root, destination, None)
    linked = root / film.package / "zh/ddwg-zh-uhd.mp4"
    linked.parent.mkdir(parents=True)
    linked.symlink_to(destination / "zh/ddwg-zh-uhd.mp4")
    for retain in (delivery_documents_folder.plan_retention, delivery_documents_folder.retain):
        with pytest.raises(DeliveryRefusedError, match=r"holds a linked film: .*ddwg-zh-uhd\.mp4"):
            retain(root, destination, "previous", film.package)
    linked.unlink()
    os.link(destination / "zh/ddwg-zh-uhd.mp4", linked)
    with pytest.raises(DeliveryRefusedError, match=r"another file than zh/ddwg-zh-uhd\.mp4"):
        delivery_documents_folder.retain(root, destination, "previous", film.package)
    assert not (root / delivery_documents_folder.PREDECESSORS).exists()
    linked.unlink()
    # A retention record that names the link itself as the rollback copy holds nothing.
    retention = (
        root
        / delivery_documents_folder.retain(root, destination, "previous", film.package)["retention"]
    )
    record = json.loads(retention.read_text())
    linked.symlink_to(destination / "zh/ddwg-zh-uhd.mp4")
    record["members"][1]["copy"] = linked.relative_to(root).as_posix()
    retention.write_text(json.dumps(record))
    film.better()
    before = film.tree(destination)
    with pytest.raises(
        DeliveryRefusedError, match=r"No verified rollback copy .*\['zh/ddwg-zh-uhd"
    ):
        delivery_documents_folder.deliver(root, destination, retention)
    assert film.tree(destination) == before


@pytest.fixture
def copies(film):
    """A delivered root with candidate rollback copies of the delivered UHD film."""
    root, destination = film
    delivery_documents_folder.deliver(root, destination, None)
    entry = destination / "zh/ddwg-zh-uhd.mp4"
    kept = film.write(root / film.package / "zh/ddwg-zh-uhd.mp4", entry.read_text())
    film.write(root.parent / "outside.mp4", entry.read_text())
    (root / "build/link.mp4").symlink_to(kept)
    os.link(entry, root / "build/hard-link.mp4")
    film.write(root / "build/other.mp4", "other bytes\n")
    # A destination below the root, whose own entry would be its rollback copy.
    film.write(root / "build/delivered/zh/ddwg-zh-uhd.mp4", entry.read_text())
    return root, destination, kept, {"path": "zh/ddwg-zh-uhd.mp4", "sha256": file_sha(entry)}


@pytest.mark.parametrize(
    ("copy", "inside", "message"),
    [
        ("absolute", False, "a relative path below"),
        ("../outside.mp4", False, "a relative path below"),
        ("build/link.mp4", False, "not a link"),
        ("build/delivered/zh/ddwg-zh-uhd.mp4", True, "lies outside the destination"),
        ("build/hard-link.mp4", False, "another file than zh/ddwg-zh-uhd.mp4"),
        ("build/missing.mp4", False, "no rollback copy"),
        ("build/other.mp4", False, "retained copy differs from the destination entry"),
    ],
)
def test_a_rollback_copy_is_a_separate_regular_file_below_the_root(copies, copy, inside, message):
    root, destination, kept, row = copies
    at = root / "build/delivered" if inside else destination
    named = str(kept) if copy == "absolute" else copy
    with pytest.raises(DeliveryRefusedError, match=message):
        delivery_documents_folder.rollback_copy(root, at, {**row, "copy": named})


def test_a_regular_copy_below_the_root_is_a_rollback_copy(copies):
    root, destination, kept, row = copies
    copy = {**row, "copy": kept.relative_to(root).as_posix()}
    assert delivery_documents_folder.rollback_copy(root, destination, copy) == kept.resolve()


def test_unretained_entries_are_refused_before_anything_is_written(film):
    root, destination = film
    delivery_documents_folder.deliver(root, destination, None)
    retention = (
        root
        / delivery_documents_folder.retain(root, destination, "previous", film.package)["retention"]
    )
    film.write(destination / "zh/ddwg-zh 2.srt", "finder copy\n")
    film.better()
    before, readback = (
        film.tree(destination),
        (root / delivery_documents_folder.READBACK).read_text(),
    )
    with pytest.raises(
        DeliveryRefusedError, match=r"No verified rollback copy .*'zh/ddwg-zh 2\.srt'\]"
    ):
        delivery_documents_folder.deliver(root, destination, retention)
    (destination / "zh/ddwg-zh 2.srt").unlink()
    (destination / "en/ddwg-en.srt").write_text("edited after retention\n")
    with pytest.raises(
        DeliveryRefusedError, match=r"No verified rollback copy .*\['en/ddwg-en\.srt'\]"
    ):
        delivery_documents_folder.deliver(root, destination, retention)
    record = json.loads(retention.read_text())
    record["documents_root"] = "/elsewhere"
    retention.write_text(json.dumps(record))
    with pytest.raises(DeliveryRefusedError, match="retains /elsewhere"):
        delivery_documents_folder.deliver(root, destination, retention)
    before["en/ddwg-en.srt"] = "edited after retention\n"
    del before["zh/ddwg-zh 2.srt"]
    assert film.tree(destination) == before
    assert (root / delivery_documents_folder.READBACK).read_text() == readback


def test_retained_unexpected_entries_are_archived_then_removed(film):
    root, destination = film
    delivery_documents_folder.deliver(root, destination, None)
    film.write(destination / "zh/ddwg-zh 2.srt", "finder copy\n")
    # A staged copy left by an interrupted delivery has the name the next one stages.
    film.write(destination / "zh/.ddwg-zh-uhd.mp4.delivering", "partial\n")
    film.write(destination / "old/notes/draft.txt", "draft\n")
    film.write(destination / "old/.DS_Store", "finder\n")
    (destination / "empty").mkdir()
    film.write(destination / "zh/.DS_Store", "finder\n")
    film.write(destination / ".claude/state", "app\n")
    summary = delivery_documents_folder.retain(root, destination, "previous", film.package)
    assert (summary["members"], summary["unexpected"]) == (21, 3)
    retention = root / summary["retention"]
    record = json.loads(retention.read_text())
    assert [row["path"] for row in record["unexpected"]] == [
        "old/notes/draft.txt",
        "zh/.ddwg-zh-uhd.mp4.delivering",
        "zh/ddwg-zh 2.srt",
    ]
    film.better()
    planned = delivery_documents_folder.plan_delivery(root, destination, retention)
    assert planned == {
        "destination": str(destination),
        "members": [path for _, path in delivery_documents_folder.plan(root)],
        "remove": [
            "empty",
            "old",
            "old/notes",
            "old/notes/draft.txt",
            "zh/.ddwg-zh-uhd.mp4.delivering",
            "zh/ddwg-zh 2.srt",
        ],
        "dry_run": True,
    }
    report = delivery_documents_folder.deliver(root, destination, retention)
    assert report["all_match"]
    assert report["unexpected"] == []
    assert report["foreign_preserved"] == [".claude", "zh/.DS_Store"]
    assert film.tree(destination) == {
        **{path: f"better {path}\n" for _, path in delivery_documents_folder.plan(root)},
        ".claude/state": "app\n",
        "zh/.DS_Store": "finder\n",
    }
    archive = root / delivery_documents_folder.PREDECESSORS / "previous"
    assert (archive / "zh/ddwg-zh 2.srt").read_text() == "finder copy\n"
    assert (archive / "zh/index.html").read_text() == "current zh/index.html\n"


def test_absent_retention_records_are_refused(film):
    root, destination = film
    delivery_documents_folder.deliver(root, destination, None)
    with pytest.raises(DeliveryRefusedError, match="No retention record at"):
        delivery_documents_folder.deliver(root, destination, root / "build/absent/retention.json")
