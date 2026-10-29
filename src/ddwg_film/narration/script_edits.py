"""Apply exact text edits to the film scripts and keep mirrors, speech and retakes bound.

An edits file maps "replace" and "split" to per-edition lists. A replacement
[thought, old, new] replaces a phrase that occurs exactly once in the thought; a split
[thought, seam] cuts the thought after a seam that occurs exactly once inside it. A
thought is "segment.index" (1-based), indexed as before the edits. Each changed
segment's text is rebuilt from its thoughts and its spoken text derived through the
script's pronunciation contract, the narration mirror is rewritten, and each bound retake
follows its exact text to its new index; a retake whose text no longer occurs exactly once
is released. Nothing is written unless every edit of every edition applies.

Usage: python -m ddwg_film.narration.script_edits --edits FILE [--dry-run]
An edits file: {"replace": {"en": [["13.5", "proves no", "does not prove"]]},
    "split": {"en": [["07.2", "the evidence."]]}}
Paths are relative to the repository root.
"""

import argparse
import copy
import json

import ddwg_film.repository as repository
from ddwg_film.narration.pronunciation import pronunciation_contract, pronunciation_text
from ddwg_film.narration.retakes import rebind
from ddwg_film.production import CODES, Edition


def edit(
    script: dict, cast: dict, replace: list, split: list, *, contract: dict, code: str
) -> tuple[dict, dict, list[dict]]:
    """Apply one edition's edits to copies of its script and cast.

    Args:
        script: The edition's script.
        cast: The edition's cast, whose thought retakes follow their text.
        replace: The [thought, old, new] replacements.
        split: The [thought, seam] splits.
        contract: The edition's pronunciation contract, which derives each spoken text.
        code: The edition's code, which names it in a refusal.

    Returns:
        The edited script and cast, and a report of each changed segment.
    """
    script, cast = copy.deepcopy(script), copy.deepcopy(cast)
    thoughts = {
        segment["id"]: segment.get("utterance_groups", []) for segment in script["segments"]
    }
    before = {sid: list(groups) for sid, groups in thoughts.items()}
    for key, old, new in replace:
        _replace(thoughts, key, old, new, code)
    # Split later thoughts first so that the indices of earlier ones stay valid.
    for key, seam in sorted(
        split, key=lambda item: (item[0].split(".")[0], -int(item[0].split(".")[1]))
    ):
        _split(thoughts, key, seam, code)
    changed = []
    for segment in script["segments"]:
        sid, groups = segment["id"], thoughts[segment["id"]]
        if groups == before[sid]:
            continue
        segment["text"] = "".join(groups)
        segment["spoken_text"] = pronunciation_text({"text": segment["text"]}, contract)
        bound = cast.get("retakes", {}).get(sid, {}).get("groups", {})
        moved, released = rebind(bound, groups)
        if bound:
            cast["retakes"][sid]["groups"] = moved
        changed.append(_change_report(sid, before[sid], groups, moved, released))
    return script, cast, changed


def _thought(thoughts: dict, key: str, code: str) -> tuple[list[str], int]:
    """The thoughts of the segment a key names, and the key's 0-based place among them."""
    segment, index = key.split(".")
    groups = thoughts.get(segment, [])
    if not 1 <= int(index) <= len(groups):
        msg = f"{code} {key}: no such thought"
        raise ValueError(msg)
    return groups, int(index) - 1


def _replace(thoughts: dict, key: str, old: str, new: str, code: str) -> None:
    """Replace a phrase that occurs exactly once in a thought."""
    groups, at = _thought(thoughts, key, code)
    if groups[at].count(old) != 1:
        msg = f"{code} {key}: phrase not found exactly once: {old}"
        raise ValueError(msg)
    groups[at] = groups[at].replace(old, new)


def _split(thoughts: dict, key: str, seam: str, code: str) -> None:
    """Cut a thought in two after a seam that occurs exactly once inside it."""
    groups, at = _thought(thoughts, key, code)
    text = groups[at]
    if text.count(seam) != 1 or text.endswith(seam):
        msg = f"{code} {key}: seam not found exactly once inside the thought: {seam}"
        raise ValueError(msg)
    cut = text.index(seam) + len(seam)
    groups[at : at + 1] = [text[:cut], text[cut:]]


def _change_report(
    segment: str, before: list[str], after: list[str], moved: dict, released: list[str]
) -> dict:
    """What an edit changed in one segment: its thoughts and its retakes."""
    return {
        "segment": segment,
        "thoughts_before": len(before),
        "thoughts_after": len(after),
        "new_thoughts": [index for index, text in enumerate(after, 1) if text not in before],
        "retakes_moved": {index: take["seed"] for index, take in moved.items()},
        "retakes_released": released,
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Apply exact edits to the scripts.")
    parser.add_argument("--edits", required=True, help="Edits JSON file")
    parser.add_argument("--dry-run", action="store_true", help="Report the edits without writing")
    options = parser.parse_args(argv)
    edits = repository.read(options.edits)
    if set(edits) - {"replace", "split"} or any(
        set(lists) - set(CODES) for lists in edits.values()
    ):
        msg = 'An edits file maps "replace" and "split" to editions'
        raise ValueError(msg)
    edited = {}
    for code in CODES:
        replace = edits.get("replace", {}).get(code, [])
        split = edits.get("split", {}).get(code, [])
        if replace or split:
            edition = Edition(code)
            script = repository.read(edition.script)
            contract, _ = pronunciation_contract(script, edition.language)
            cast = repository.read(edition.cast)
            edited[code] = edit(script, cast, replace, split, contract=contract, code=code)
    if not options.dry_run:
        for code, (script, cast, changed) in edited.items():
            if changed:
                _write(Edition(code), script, cast)
    report = {code: changed for code, (_, _, changed) in edited.items()}
    print(
        json.dumps(
            {"dry_run": options.dry_run, "editions": report},
            ensure_ascii=False,
            indent=1,
        )
    )


def _write(edition: Edition, script: dict, cast: dict) -> None:
    """Write an edition's edited script and cast, and its narration mirror."""
    repository.write(edition.script, script)
    repository.write(edition.cast, cast)
    (repository.ROOT / edition.mirror).write_text(
        "\n\n".join(segment["text"] for segment in script["segments"]) + "\n"
    )


if __name__ == "__main__":
    main()
