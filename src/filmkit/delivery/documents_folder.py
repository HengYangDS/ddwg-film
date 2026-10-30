"""Deliver both editions to the film's Documents folder with rsync, then read them back with shasum.

The destination holds exactly the 21 delivery members: the language entry page and, per
edition, the UHD and captioned 1080p films, the cover as PNG and JPEG, SRT and VTT subtitles,
the transcript, chapters as JSON and FFmetadata, and the player. They lie below
build/artifacts/film as they lie below the destination. rsync copies each member whose bytes
differ and removes every other entry except Finder's .DS_Store files and the app-managed
.claude folder; each entry it replaces or removes moves into
build/artifacts/delivery/predecessors/<time>/, outside the destination, as the rollback copy.
shasum then checks every member against its source's SHA-256 from
build/evidence/delivery/SHA256SUMS, and the readback, which the player check reads, records
each member with the film's file prefix and duration in
build/evidence/delivery/delivery-readback.json.

The film verifier binds every member to its package records; the delivery task runs it first.
A refusal before rsync leaves the destination unchanged and exits with status 1.

Usage: python -m filmkit.delivery.documents_folder [--destination DIR] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import filmkit.repository as repository
from filmkit.delivery.packaging import BOUND_FILM, LANGUAGE_INDEX, viewing_members
from filmkit.film import FILM
from filmkit.production import CODES, Edition

DESTINATION = Path.home() / "Documents" / FILM.documents_folder
# The folder below which every member lies as it lies below the destination.
SOURCE = LANGUAGE_INDEX.parent
PREDECESSORS = Path("build/artifacts/delivery/predecessors")
SUMS = Path("build/evidence/delivery/SHA256SUMS")
READBACK = Path("build/evidence/delivery/delivery-readback.json")
FILTER = Path("build/runtime/work/delivery/members.filter")
# The destination entries a delivery preserves: Finder's files and the app-managed folder.
FINDER_METADATA = ".DS_Store"
APP_FOLDER = ".claude"
# Seconds that rsync or shasum may take.
DEADLINE = 3600
# How the rsync 3 that delivery requires begins its version report; macOS's own rsync is openrsync.
RSYNC_3 = "rsync  version 3."


class DeliveryRefusedError(Exception):
    """A delivery that cannot be made or a destination that does not read back."""


def plan(root: Path) -> list[tuple[Path, str]]:
    """Each delivery member's source and destination-relative path."""
    members = [(root / LANGUAGE_INDEX, LANGUAGE_INDEX.name)]
    for code in CODES:
        edition = Edition(code)
        names = [film.name for film in edition.films] + list(viewing_members(edition))
        folder = root / edition.artifacts.relative_to(repository.ROOT)
        members.extend((folder / name, f"{code}/{name}") for name in names)
    return members


def rsync_version() -> str:
    """The first line that the rsync on PATH reports of its version."""
    return repository.run(["rsync", "--version"]).stdout.decode().splitlines()[0]


def rules(paths: list[str]) -> str:
    """The rsync filter: protect the foreign entries, include the members, exclude the rest."""
    folders = dict.fromkeys(Path(path).parent.as_posix() for path in paths if "/" in path)
    return "".join(
        f"{rule}\n"
        for rule in (
            f"P {FINDER_METADATA}",
            f"P /{APP_FOLDER}/",
            *(f"+ /{folder}/" for folder in folders),
            *(f"+ /{path}" for path in paths),
            "- *",
        )
    )


def run(command: list[str], cwd: Path) -> subprocess.CompletedProcess:
    """Run a command without input, capturing its text output."""
    return subprocess.run(
        command,
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
        timeout=DEADLINE,
    )


def entries(destination: Path, paths: list[str]) -> list[str]:
    """The destination's files and folders that are neither members nor preserved entries."""
    allowed = set(paths) | {Path(path).parent.as_posix() for path in paths}
    found = []
    for folder, subfolders, files in os.walk(destination):
        base = Path(folder).relative_to(destination)
        if APP_FOLDER in subfolders and base == Path():
            subfolders.remove(APP_FOLDER)
        names = [*subfolders, *(name for name in files if name != FINDER_METADATA)]
        found += [(base / name).as_posix() for name in names]
    return sorted(path for path in found if path not in allowed)


def readback(root: Path, destination: Path) -> dict:
    """Check every member at the destination against its source, and nothing beside them."""
    paths = [path for _, path in plan(root)]
    check = run(["shasum", "-a", "256", "-c", str(root / SUMS)], destination)
    if check.returncode != 0:
        failed = [line.rsplit(":", 1)[0] for line in check.stdout.splitlines() if "FAILED" in line]
        msg = f"The destination differs from its sources: {', '.join(failed) or check.stderr}"
        raise DeliveryRefusedError(msg)
    unexpected = entries(destination, paths)
    if unexpected:
        msg = f"The destination holds unexpected entries: {', '.join(unexpected)}"
        raise DeliveryRefusedError(msg)
    rows = []
    for path in paths:
        target = destination / path
        size = target.stat().st_size
        rows.append({"path": path, "sha256": repository.sha(target), "bytes": size})
    return {
        "destination": str(destination),
        "film": dict(BOUND_FILM),
        "delivered_at": datetime.now(UTC).isoformat(),
        "members": rows,
        "all_match": True,
        "unexpected": [],
    }


def deliver(root: Path, destination: Path, *, dry_run: bool = False) -> dict:
    """Replace the destination's delivery with the current members and read it back."""
    members = plan(root)
    missing = [path for source, path in members if not source.is_file()]
    if missing:
        msg = f"Missing delivery sources: {', '.join(missing)}"
        raise DeliveryRefusedError(msg)
    version = rsync_version()
    if not version.startswith(RSYNC_3):
        msg = f"rsync 3 is required to deliver, as Homebrew installs it; PATH holds {version}"
        raise DeliveryRefusedError(msg)
    paths = [path for _, path in members]
    for place, text in (
        (FILTER, rules(paths)),
        (SUMS, "".join(f"{repository.sha(source)}  {path}\n" for source, path in members)),
    ):
        (root / place).parent.mkdir(parents=True, exist_ok=True)
        (root / place).write_text(text)
    kept = PREDECESSORS / datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    command = [
        "rsync",
        "--archive",
        "--checksum",
        # Removals wait until every member is in place.
        "--delete-after",
        "--delete-excluded",
        "--backup",
        f"--backup-dir={root / kept}",
        f"--filter=merge {root / FILTER}",
        "--itemize-changes",
        "--mkpath",
        *(["--dry-run"] if dry_run else []),
        f"{root / SOURCE}/",
        f"{destination}/",
    ]
    synced = run(command, root)
    if synced.returncode != 0:
        msg = f"rsync failed: {synced.stderr.strip()}"
        raise DeliveryRefusedError(msg)
    changes = [line for line in synced.stdout.splitlines() if line.strip()]
    if dry_run:
        return {"destination": str(destination), "changes": changes, "dry_run": True}
    report = readback(root, destination)
    report["predecessors"] = kept.as_posix() if (root / kept).exists() else None
    report["changes"] = changes
    repository.write(root / READBACK, report)
    return report


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--destination", type=Path, default=DESTINATION)
    parser.add_argument("--dry-run", action="store_true")
    options = parser.parse_args(argv)
    destination = options.destination.expanduser().resolve()
    try:
        report = deliver(repository.ROOT, destination, dry_run=options.dry_run)
    except DeliveryRefusedError as error:
        raise SystemExit(str(error)) from None
    if options.dry_run:
        print(json.dumps(report, ensure_ascii=False))
        return
    summary = {key: report[key] for key in ("all_match", "predecessors")}
    print(json.dumps({"members": len(report["members"]), **summary}))


if __name__ == "__main__":
    main()
