"""Deliver the bilingual editions to Documents, retaining the delivery they replace.

The destination holds exactly the 21 delivery members: the language entry page and,
per edition, the UHD and captioned 1080p movies, the cover as PNG and JPEG, SRT and
VTT subtitles, the transcript, chapters as JSON and FFmetadata, and the player.
Finder's .DS_Store files and the app-managed .claude folder at the top are ignored;
any other entry, such as a Finder copy "ddwg-zh 2.srt", is unexpected.

retain records a verified rollback copy of the destination before it is replaced:
each member and unexpected file whose exact bytes a set-aside package already holds
is bound to that film, the others are copied under
build/artifacts/film/predecessors/<name>/, and every copy is read back. A rollback copy
is a regular file below the repository root, outside the destination and apart from the
entry it keeps, so a set-aside package that holds a linked film is refused.
deliver refuses before writing anything unless each source holds the bytes that its
edition's film or viewing package records, and the retention record holds the exact
bytes of every member and unexpected file at the destination. It removes the retained
unexpected entries, replaces each member through a staged copy beside it, and reads
the whole destination back into build/evidence/delivery/delivery-readback.json: each
member's hash, bytes and mode against its source, every entry that is not a member,
and the package records that bound the sources.

A refusal leaves the destination unchanged and exits with status 1.

Usage: python -m ddwg_film.delivery.documents_folder retain --name <name> --package <build folder>
           [--destination DIR] [--dry-run]
       python -m ddwg_film.delivery.documents_folder deliver [--retention <retention.json>]
           [--destination DIR] [--dry-run]
"""

import argparse
import json
import os
import shutil
import stat
from datetime import UTC, datetime
from pathlib import Path
from typing import NamedTuple

import ddwg_film.repository as repository
from ddwg_film.delivery.packaging import LANGUAGE_INDEX, viewing_members
from ddwg_film.production import CODES, Edition


class DeliveryRefusedError(Exception):
    """A retention or delivery that cannot be made; the destination is unchanged."""


DESTINATION = Path.home() / "Documents/ddwg-introduction-film"
PREDECESSORS = "build/artifacts/film/predecessors"
READBACK = "build/evidence/delivery/delivery-readback.json"
FINDER_METADATA = ".DS_Store"
APP_FOLDER = ".claude"


class Inventory(NamedTuple):
    """Destination entries by kind, as destination-relative POSIX paths."""

    members: list[str]
    unexpected: list[str]
    folders: list[str]
    ignored: list[str]


class Retention(NamedTuple):
    """A planned retention: its folder, the destination's entries and each entry's row."""

    target: Path
    current: Inventory
    rows: dict[str, dict]
    summary: dict


class Binding(NamedTuple):
    """The package records that bind the delivery sources, and each member's bound SHA-256."""

    records: list[dict]
    expected: dict[str, str]


class Delivery(NamedTuple):
    """A checked delivery: its members, the destination's entries and the sources' binding."""

    members: list[tuple[Path, str]]
    current: Inventory
    binding: Binding


def below(root: Path, path: Path) -> Path:
    """The place below `root` of a path that the production names below the repository root."""
    return root / path.relative_to(repository.ROOT)


def plan(root: Path) -> list[tuple[Path, str]]:
    """Return each delivery member's source and destination-relative path."""
    members = [(root / LANGUAGE_INDEX, LANGUAGE_INDEX.name)]
    for code in CODES:
        edition = Edition(code)
        names = [film.name for film in edition.films] + list(viewing_members(edition))
        folder = below(root, edition.artifacts)
        members.extend((folder / name, f"{code}/{name}") for name in names)
    return members


def unreadable(error: OSError) -> None:
    msg = f"Cannot read the destination: {error}"
    raise DeliveryRefusedError(msg)


def classify_folder(folder: Path, relative: str, members: set[str], layout: set[str]) -> str | None:
    """The inventory kind of a destination folder, or None for an edition folder.

    A linked folder and a folder in a member's place are refused.
    """
    if folder.is_symlink():
        msg = f"Destination entry is a link: {relative}"
        raise DeliveryRefusedError(msg)
    if relative in members:
        msg = f"Destination member is a folder: {relative}"
        raise DeliveryRefusedError(msg)
    if relative == APP_FOLDER:
        return "ignored"
    return None if relative in layout else "folders"


def classify_file(file: Path, relative: str, members: set[str], layout: set[str]) -> str:
    """The inventory kind of a destination file.

    A link, a special file and a file in an edition folder's place are refused.
    """
    if file.is_symlink() or not file.is_file():
        msg = f"Destination entry is not a regular file: {relative}"
        raise DeliveryRefusedError(msg)
    if relative in layout:
        msg = f"Destination edition folder is a file: {relative}"
        raise DeliveryRefusedError(msg)
    if file.name == FINDER_METADATA:
        return "ignored"
    return "members" if relative in members else "unexpected"


def inventory(destination: Path, members: set[str]) -> Inventory:
    """Classify destination entries; refuse links, special files, displaced members."""
    layout = {Path(path).parent.as_posix() for path in members} - {"."}
    found: dict[str, list[str]] = {kind: [] for kind in Inventory._fields}
    if not destination.exists():
        return Inventory(**found)
    for folder, subfolders, files in os.walk(destination, onerror=unreadable):
        base = Path(folder).relative_to(destination)
        for name in sorted(subfolders):
            relative = (base / name).as_posix()
            kind = classify_folder(Path(folder, name), relative, members, layout)
            if kind == "ignored":
                subfolders.remove(name)
            if kind is not None:
                found[kind].append(relative)
        for name in sorted(files):
            relative = (base / name).as_posix()
            found[classify_file(Path(folder, name), relative, members, layout)].append(relative)
    return Inventory(**found)


def rollback_copy(root: Path, destination: Path, row: dict) -> Path:
    """The verified rollback copy that a retention row names for its destination entry.

    The copy is named by a relative path that resolves below the root, is no link, lies
    outside the destination, is another file than the entry it keeps and holds the row's
    bytes; any other copy is refused.
    """
    named = Path(row["copy"])
    try:
        copy = (root / named).resolve(strict=True)
    except OSError as error:
        msg = f"{row['copy']}: no rollback copy: {error}"
        raise DeliveryRefusedError(msg) from error
    entry = destination / row["path"]
    if named.is_absolute() or not copy.is_relative_to(root.resolve()):
        msg = f"{row['copy']}: a rollback copy is a relative path below {root}"
    elif (root / named).is_symlink():
        msg = f"{row['copy']}: a rollback copy is not a link"
    elif copy.is_relative_to(destination.resolve()):
        msg = f"{row['copy']}: a rollback copy lies outside the destination"
    elif entry.exists() and copy.samefile(entry):
        msg = f"{row['copy']}: a rollback copy is another file than {row['path']}"
    elif not copy.is_file() or repository.sha(copy) != row["sha256"]:
        msg = f"{root / named}: retained copy differs from the destination entry"
    else:
        return copy
    raise DeliveryRefusedError(msg)


def held_films(package: Path, sizes: set[int]) -> dict[str, Path]:
    """The set-aside package's films of the given sizes by SHA-256; a linked film is refused."""
    held = {}
    for film in package.rglob("*.mp4"):
        if film.is_symlink():
            msg = f"The set-aside package holds a linked film: {film}"
            raise DeliveryRefusedError(msg)
        if film.is_file() and film.stat().st_size in sizes:
            held[repository.sha(film)] = film
    return held


def planned_retention(root: Path, destination: Path, name: str, package: Path) -> Retention:
    """Refuse a retention that cannot be made, else plan each entry's rollback copy."""
    if Path(name).name != name or name in ("", ".", ".."):
        msg = f"A predecessor name is one folder name: {name!r}"
        raise DeliveryRefusedError(msg)
    target = root / PREDECESSORS / name
    if target.exists():
        msg = f"{target} already exists; inspect it before retaining again"
        raise DeliveryRefusedError(msg)
    package = root / package
    if not package.is_dir() or not package.resolve().is_relative_to(root.resolve()):
        msg = f"The set-aside package must be a folder under {root}: {package}"
        raise DeliveryRefusedError(msg)
    current = inventory(destination, {path for _, path in plan(root)})
    entries = current.members + current.unexpected
    if not entries:
        msg = f"{destination} holds no delivery to retain"
        raise DeliveryRefusedError(msg)
    held = held_films(package, {(destination / path).stat().st_size for path in entries})
    rows = {}
    for path in entries:
        value = repository.sha(destination / path)
        bound = held.get(value)
        rows[path] = {
            "path": path,
            "sha256": value,
            "bytes": (destination / path).stat().st_size,
            "source": "copied-from-documents" if bound is None else "set-aside-package",
            "copy": (target / path if bound is None else bound).relative_to(root).as_posix(),
        }
        if bound is not None:
            rollback_copy(root, destination, rows[path])
    summary = {
        "target": target.relative_to(root).as_posix(),
        "members": len(current.members),
        "unexpected": len(current.unexpected),
        "copied": sum(row["source"] == "copied-from-documents" for row in rows.values()),
        "bound": sum(row["source"] == "set-aside-package" for row in rows.values()),
    }
    return Retention(target, current, rows, summary)


def plan_retention(root: Path, destination: Path, name: str, package: Path) -> dict:
    """Summarize the retention that `retain` would record, writing nothing."""
    return {**planned_retention(root, destination, name, package).summary, "dry_run": True}


def retain(root: Path, destination: Path, name: str, package: Path) -> dict:
    """Record a verified rollback copy of every member and unexpected file."""
    planned = planned_retention(root, destination, name, package)
    for row in planned.rows.values():
        if row["source"] == "copied-from-documents":
            copy = root / row["copy"]
            copy.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(destination / row["path"], copy)
        rollback_copy(root, destination, row)
    order = [path for _, path in plan(root)]
    record = {
        "purpose": "Rollback copy of the Documents delivery that the next successor "
        "delivery replaces, and of every unexpected entry beside it.",
        "consumer": "Documents delivery rollback until the successor delivery is accepted",
        "exit_condition": "User acceptance of the successor delivery; then retire the "
        "copied members.",
        "created_at": datetime.now(UTC).isoformat(),
        "documents_root": str(destination),
        "members": [planned.rows[path] for path in order if path in planned.rows],
        "unexpected": [planned.rows[path] for path in sorted(planned.current.unexpected)],
    }
    manifest = planned.target / "retention.json"
    repository.write(manifest, record)
    return {
        **planned.summary,
        "dry_run": False,
        "retention": manifest.relative_to(root).as_posix(),
        "sha256": repository.sha(manifest),
    }


def holds_rollback_copy(root: Path, destination: Path, path: str, row: dict | None) -> bool:
    """Whether a retention row holds a verified rollback copy of an entry's current bytes."""
    if row is None or "copy" not in row or row["sha256"] != repository.sha(destination / path):
        return False
    try:
        rollback_copy(root, destination, row)
    except DeliveryRefusedError:
        return False
    return True


def unretained(root: Path, destination: Path, entries: list[str], retention: Path) -> list[str]:
    """Return the entries whose exact bytes the retention record does not hold."""
    if not retention.is_file():
        msg = f"No retention record at {retention}"
        raise DeliveryRefusedError(msg)
    record = json.loads(retention.read_text())
    if record.get("documents_root") != str(destination):
        msg = f"{retention} retains {record.get('documents_root')}, not {destination}"
        raise DeliveryRefusedError(msg)
    rows = {row["path"]: row for row in record["members"] + record.get("unexpected", [])}
    return [
        path for path in entries if not holds_rollback_copy(root, destination, path, rows.get(path))
    ]


def package_records(root: Path) -> list[dict]:
    """Each edition's film and viewing package record with the member bytes that it binds.

    A film package binds its films, a viewing package its members and the language entry
    page that it records, each by destination-relative path.
    """
    records = []
    for code in CODES:
        edition = Edition(code)
        for place, field in (
            (edition.film_package, "editions"),
            (edition.viewing_package, "members"),
        ):
            path = below(root, place)
            if not path.is_file():
                msg = f"No package record at {path.relative_to(root).as_posix()}"
                raise DeliveryRefusedError(msg)
            data = path.read_bytes()
            body = json.loads(data)
            binds = {f"{code}/{member['path']}": member["sha256"] for member in body[field]}
            index = body.get("language_index", {})
            if index.get("path") == LANGUAGE_INDEX.as_posix():
                binds[LANGUAGE_INDEX.name] = index["sha256"]
            records.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "sha256": repository.content_sha(data),
                    "binds": binds,
                }
            )
    return records


def bind_sources(root: Path, members: list[tuple[Path, str]]) -> Binding:
    """Refuse unless every source holds the bytes that each package record binding it holds."""
    records = package_records(root)
    expected, differing = {}, []
    for source, path in members:
        value = repository.sha(source)
        recorded = [record["binds"][path] for record in records if path in record["binds"]]
        if not recorded or any(bound != value for bound in recorded):
            differing.append(path)
        expected[path] = value
    if differing:
        msg = f"Delivery sources differ from their package records: {differing}"
        raise DeliveryRefusedError(msg)
    return Binding(records, expected)


def checked_delivery(root: Path, destination: Path, retention: Path | None) -> Delivery:
    """Refuse a delivery that cannot be made, else return what it places and replaces."""
    members = plan(root)
    missing = [source.relative_to(root).as_posix() for source, _ in members if not source.is_file()]
    if missing:
        msg = f"Missing delivery sources: {missing}"
        raise DeliveryRefusedError(msg)
    binding = bind_sources(root, members)
    current = inventory(destination, {path for _, path in members})
    entries = current.members + current.unexpected
    if entries:
        if retention is None:
            msg = f"{destination} holds a delivery; retain it and pass --retention"
            raise DeliveryRefusedError(msg)
        lacking = unretained(root, destination, entries, retention)
        if lacking:
            msg = f"No verified rollback copy in {retention} for: {lacking}"
            raise DeliveryRefusedError(msg)
    return Delivery(members, current, binding)


def place(source: Path, target: Path) -> None:
    """Copy a member beside its target, then rename it into place."""
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.with_name(f".{target.name}.delivering")
    try:
        shutil.copy2(source, staging)
        staging.replace(target)
    finally:
        staging.unlink(missing_ok=True)


def readback(root: Path, destination: Path, binding: Binding | None = None) -> dict:
    """Read the whole destination back against the current member sources.

    Given the binding that a delivery checked, every member must also hold its bound bytes,
    and the report keeps the package records.
    """
    members = plan(root)
    found = inventory(destination, {path for _, path in members})
    rows = []
    for source, path in members:
        row = {"path": path, "source": source.relative_to(root).as_posix()}
        expected = (
            repository.sha(source),
            source.stat().st_size,
            oct(stat.S_IMODE(source.stat().st_mode)),
        )
        if path in found.members:
            target = destination / path
            row["sha256"] = repository.sha(target)
            row["bytes"] = target.stat().st_size
            row["mode"] = oct(stat.S_IMODE(target.stat().st_mode))
        else:
            row["sha256"] = row["bytes"] = row["mode"] = None
        row["matches_source"] = (row["sha256"], row["bytes"], row["mode"]) == expected
        rows.append(row)
    unexpected = sorted(found.unexpected + found.folders)
    bound = binding is None or all(row["sha256"] == binding.expected[row["path"]] for row in rows)
    report = {
        "destination": str(destination),
        "delivered_at": datetime.now(UTC).isoformat(),
        "members": rows,
        "all_match": all(row["matches_source"] for row in rows) and not unexpected and bound,
        "foreign_preserved": sorted(found.ignored),
        "unexpected": unexpected,
    }
    if binding is not None:
        report["package_records"] = binding.records
    return report


def plan_delivery(root: Path, destination: Path, retention: Path | None) -> dict:
    """Summarize what `deliver` would place and remove, writing nothing."""
    members, current, _ = checked_delivery(root, destination, retention)
    return {
        "destination": str(destination),
        "members": [path for _, path in members],
        "remove": sorted(current.unexpected + current.folders),
        "dry_run": True,
    }


def deliver(root: Path, destination: Path, retention: Path | None) -> dict:
    """Replace the destination's delivery with the current members and read it back."""
    members, current, binding = checked_delivery(root, destination, retention)
    for path in current.unexpected:
        (destination / path).unlink()
    # The walk lists a folder before its subfolders; reversed, it empties them first.
    for path in reversed(current.folders):
        (destination / path / FINDER_METADATA).unlink(missing_ok=True)
        (destination / path).rmdir()
    for source, path in members:
        place(source, destination / path)
    report = readback(root, destination, binding)
    repository.write(root / READBACK, report)
    return report


def arguments() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    keep = commands.add_parser("retain", help="record a rollback copy of the destination")
    keep.add_argument("--name", required=True, help=f"predecessor folder under {PREDECESSORS}")
    keep.add_argument("--package", required=True, type=Path, help="set-aside package holding films")
    send = commands.add_parser("deliver", help="replace the delivery and read it back")
    send.add_argument("--retention", type=Path, help="retention record of the destination")
    for command in (keep, send):
        command.add_argument("--destination", type=Path, default=DESTINATION)
        command.add_argument("--dry-run", action="store_true")
    return parser


def run(options: argparse.Namespace) -> dict:
    """Plan or make the chosen retention or delivery; return its summary or readback."""
    destination = options.destination.expanduser().resolve()
    if options.command == "retain":
        keep = plan_retention if options.dry_run else retain
        return keep(repository.ROOT, destination, options.name, options.package)
    retention = repository.ROOT / options.retention if options.retention else None
    send = plan_delivery if options.dry_run else deliver
    return send(repository.ROOT, destination, retention)


def main(argv: list[str] | None = None) -> None:
    options = arguments().parse_args(argv)
    try:
        report = run(options)
    except DeliveryRefusedError as error:
        raise SystemExit(str(error)) from None
    if options.command == "retain" or options.dry_run:
        print(json.dumps(report))
        return
    print(
        json.dumps(
            {
                "members": len(report["members"]),
                "all_match": report["all_match"],
                "unexpected": report["unexpected"],
            }
        )
    )
    if not report["all_match"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
