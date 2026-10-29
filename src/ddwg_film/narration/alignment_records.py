"""Where each narration recording's alignment is cached.

An alignment is cached under its recording's waveform and the aligner revision that made it,
so a recording aligned again by another aligner revision never reuses or replaces it. The
aligner caches records here, under the build directory.
"""

CACHE = "build/evidence/alignment-records"


def alignment_record(language: str, record_id: str, wav_sha256: str, aligner_revision: str) -> str:
    """The root-relative path of one recording's alignment by one aligner revision."""
    return f"{CACHE}/{language.lower()}/{record_id}-{wav_sha256[:12]}-{aligner_revision[:12]}.json"
