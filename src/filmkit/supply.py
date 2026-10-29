"""Install the browser build and the speech models the engine pins, below the tool cache.

The supply is the only build step that reaches the network. The locked @puppeteer/browsers
installs the browser build that the locked renderer pins, and huggingface_hub downloads each
pinned model snapshot, from the mirror that HF_ENDPOINT names when it is set. Each is then
checked against its pinned digests, so the build that follows reads only checked inputs and
runs offline. Installing again keeps what is already in place.

Usage: python -m filmkit.supply
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from huggingface_hub import snapshot_download

import filmkit.picture.rendering as picture_rendering
import filmkit.repository as repository
from filmkit.narration.snapshots import ALIGNER, RECOGNIZER, VOICE, SnapshotError

# The locked browser installer, below the repository root.
BROWSER_INSTALLER = Path("node_modules/.bin/browsers")
# The model snapshots the narration loads, in the order they are supplied.
SNAPSHOTS = (VOICE, RECOGNIZER, ALIGNER)
# Seconds one installer or download may take.
DEADLINE = 3600


class SupplyError(ValueError):
    """A supplied tool or model differs from its pin."""


def supply_browser() -> dict:
    """Install the pinned browser build and check its executable's SHA-256."""
    product, version = picture_rendering.BROWSER
    folder = repository.ROOT / picture_rendering.TOOL_CACHE / "browsers"
    installer = [str(repository.ROOT / BROWSER_INSTALLER), "install", f"{product}@{version}"]
    repository.run([*installer, "--path", str(folder)], timeout=DEADLINE)
    executable = picture_rendering.supplied_browser()
    if not executable.is_file() or repository.sha(executable) != picture_rendering.BROWSER_SHA256:
        msg = f"The {product}@{version} browser build differs from the pinned SHA-256"
        raise SupplyError(msg)
    return {"build": f"{product}@{version}", "executable": repository.relative(executable)}


def supply_models() -> list[dict]:
    """Download each pinned model snapshot into its folder and check its weights."""
    models = []
    for snapshot in SNAPSHOTS:
        snapshot_download(
            snapshot.repo,
            revision=snapshot.revision,
            allow_patterns=list(snapshot.files),
            local_dir=repository.ROOT / snapshot.folder,
        )
        try:
            snapshot.verify()
        except SnapshotError as error:
            raise SupplyError(str(error)) from None
        models.append(
            {"repo": snapshot.repo, "revision": snapshot.revision, "folder": snapshot.folder}
        )
    return models


def main(argv: list[str] | None = None) -> None:
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args(argv)
    report = {"browser": supply_browser(), "models": supply_models()}
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
