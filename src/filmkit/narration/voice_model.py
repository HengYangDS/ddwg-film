"""The reference-voice model's identity and the fingerprint of each request to it.

Receipts record these values, and a retained recording is reused only when its request
fingerprint matches, so they change only with a new narration.
"""

from __future__ import annotations

import json

import filmkit.repository as repository
from filmkit.narration.snapshots import VOICE

# The pinned snapshot's identity, as receipts and request fingerprints record it.
MODEL = VOICE.repo
REVISION = VOICE.revision
# Bound reusable freed buffers; this is not a hard active-working-set limit.
MLX_CACHE_LIMIT_BYTES = 2 * 1024**3
NATIVE_DECODER = "official native chunked_decode"
NATIVE_STREAM = False


def request_fingerprint(request: dict) -> str:
    """Return the SHA-256 of a request's canonical JSON: sorted keys and UTF-8 text."""
    return repository.content_sha(json.dumps(request, ensure_ascii=False, sort_keys=True))
