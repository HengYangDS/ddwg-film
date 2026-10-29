"""The reference-voice model's identity and the fingerprint of each request to it.

Receipts record these values, and a retained recording is reused only when its request
fingerprint matches, so they change only with a new narration.
"""

from __future__ import annotations

import json

import ddwg_film.repository as repository

MODEL = "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-bf16"
REVISION = "a6eb4f68e4b056f1215157bb696209bc82a6db48"
# The snapshot files the model loads from the local cache.
MODEL_FILES = ["*.json", "*.txt", "*.safetensors", "README.md"]
# Bound reusable freed buffers; this is not a hard active-working-set limit.
MLX_CACHE_LIMIT_BYTES = 2 * 1024**3
NATIVE_DECODER = "official native chunked_decode"
NATIVE_STREAM = False


def request_fingerprint(request: dict) -> str:
    """Return the SHA-256 of a request's canonical JSON: sorted keys and UTF-8 text."""
    return repository.content_sha(json.dumps(request, ensure_ascii=False, sort_keys=True))
