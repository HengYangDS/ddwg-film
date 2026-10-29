"""Fixtures shared by the narration tests that edit, audition or rebind an edition's thoughts."""

import pytest

import ddwg_film.repository as repository
from ddwg_film.production import Edition

CONTRACT = "content/voice-performance.json"


@pytest.fixture
def write_edition(tmp_path, monkeypatch):
    """Write tiny editions under a temporary root.

    Each edition gets a script of authored thoughts bound to a shared pronunciation
    contract, a cast holding only its retakes, and its narration mirror.
    """
    monkeypatch.setattr(repository, "ROOT", tmp_path)

    def write(code: str, thoughts: dict, retakes: dict, normalization: tuple = ()) -> dict:
        edition = Edition(code)
        contract = (
            repository.read(CONTRACT)
            if (tmp_path / CONTRACT).exists()
            else {"pronunciation": {"languages": {}}}
        )
        contract["pronunciation"]["languages"][edition.language] = {
            "normalization": list(normalization)
        }
        repository.write(CONTRACT, contract)
        segments = [
            {
                "id": sid,
                "text": "".join(groups),
                "spoken_text": "".join(groups),
                "utterance_groups": groups,
            }
            for sid, groups in thoughts.items()
        ]
        repository.write(edition.script, {"pronunciation_contract": CONTRACT, "segments": segments})
        repository.write(edition.cast, {"retakes": retakes})
        mirror = tmp_path / edition.mirror
        mirror.write_text("\n\n".join(segment["text"] for segment in segments) + "\n")
        return {
            "script": tmp_path / edition.script,
            "cast": tmp_path / edition.cast,
            "mirror": mirror,
        }

    return write
