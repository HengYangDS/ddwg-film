"""The canonical sources the films explain: the manifest that pins them and their check.

The manifest names the source repository, the commit the films explain and each document's
SHA-256 at that commit. A build never reads the source repository. A local clone of it, named
by `FILM_SOURCE_CHECKOUT`, lets the check read each document at the pinned commit; without
one the documents are reported as not checked.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

import filmkit.repository as repository
from filmkit.film import FILM

MANIFEST = FILM.source_manifest
# The environment variable that names a local clone of the source repository.
CHECKOUT = "FILM_SOURCE_CHECKOUT"


class SourceError(ValueError):
    """The manifest, or a document it pins, differs from what the films were made from."""


def manifest() -> dict:
    """The source manifest, refused unless it pins a document."""
    pinned = repository.read(MANIFEST)
    if not pinned.get("members"):
        msg = "Source manifest pins no canonical document"
        raise SourceError(msg)
    return pinned


def location() -> str:
    """Where a reader finds the sources: the local clone, or the repository at its commit."""
    pinned = manifest()
    checkout = os.environ.get(CHECKOUT)
    return checkout or f"{pinned['repository']}/tree/{pinned['commit']}"


def verify() -> dict:
    """Check each pinned document at the pinned commit of a local clone, when one is named."""
    pinned = manifest()
    report = {
        "repository": pinned["repository"],
        "commit": pinned["commit"],
        "members": len(pinned["members"]),
    }
    checkout = os.environ.get(CHECKOUT)
    if not checkout:
        return {**report, "documents": "not_checked"}
    for member in pinned["members"]:
        shown = subprocess.run(
            ["git", "-C", str(Path(checkout)), "show", f"{pinned['commit']}:{member['path']}"],
            capture_output=True,
            check=False,
        )
        if shown.returncode != 0 or hashlib.sha256(shown.stdout).hexdigest() != member["sha256"]:
            msg = f"Canonical source differs: {member['path']}"
            raise SourceError(msg)
    return {**report, "documents": "verified"}
