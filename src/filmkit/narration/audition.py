"""Audition alternative takes of chosen thoughts and bind the selected seeds.

audition synthesizes each target thought's spoken text from the narration receipt at
seed + k * 7919, through the narration's own native ICL path and sampling, then
measures how each take begins and ends and transcribes it. The pinned aligner locates
each take's phrase ends, and those followed by heard quiet are judged as its end is. A
take qualifies when it ends naturally, cuts none of those phrase ends and its transcript
contains the target's required phrase, and a thought
that opens its recording qualifies only when its take begins in heard quiet; the
qualified take with the fewest differing units is proposed, ties going to the quietest
ending or, with --prefer slower or brisker, to the longest or the shortest take. The
receipt, by default the one the cast declares, must hold each thought's current text, so
narrate edited segments first; its recordings, thoughts and narrator are checked before
any model loads. Takes and proposals are written under
build/runtime/work/auditions/<language>/; each take records its waveform's SHA-256,
because a rerun rewrites the take's file, and existing proposals are preserved.

A run-on target is narrated on into the thought that follows it in the film. The pinned
aligner locates the thought in each whole take, which is retained beside the take, and the
take is cut in the quiet before the next words (see run_on); a take without that quiet
does not qualify. Its proposal records the run-on that a retake binds with its seed.

apply binds each proposed seed into the cast's group retakes while the thought's
current text is still the auditioned text. The retake records that text's SHA-256, so
a later script edit releases it. Rows without a proposal are reported and left alone.

Usage: python -m filmkit.narration.audition audition
    --language zh|en --targets FILE [--takes 8] [--first 11]
    [--prefer accurate|slower|brisker] [--name audition] [--receipt FILE]
       python -m filmkit.narration.audition apply
    --language zh|en --proposals FILE [--dry-run]
The targets file maps "segment.index" to the phrase the transcript must contain, such
as {"12.3": "intended use"}, or to {"required": phrase, "run_on": true} for a run-on target.
Paths are relative to the repository root.
"""

import argparse
import dataclasses
import json
import wave

import numpy as np
from mlx_audio.audio_io import write
from mlx_audio.stt.utils import load_model

import filmkit.narration.group_generation as group_generation
import filmkit.repository as repository
from filmkit.narration.alignment import verify_aligner
from filmkit.narration.narrate import ALIGNER
from filmkit.narration.receipts import bound_records
from filmkit.narration.recognition import heard_phrase, recognition_units, unit_distance
from filmkit.narration.retakes import bind_proposals, thought_text
from filmkit.narration.run_on import following_spoken_text, run_on_cut, thought_bounds
from filmkit.narration.selection import validate_voice_record
from filmkit.narration.spoken_units import AlignmentError, phrase_joins
from filmkit.narration.take_edges import ending, opening, phrase_ends
from filmkit.narration.thought_groups import validate_group_inputs
from filmkit.narration.transcription import load_asr, transcribe
from filmkit.production import CODES, Edition

AUDITIONS = "build/runtime/work/auditions"
STRIDE = 7919
SUMMARY = ("seed", "opens_quiet", "natural", "required_heard", "differing_units", "seconds")


def propose(
    takes: list[dict], prefer: str = "accurate", *, opens_recording: bool = False
) -> int | None:
    """The seed of the best qualified take, or None when no take qualifies.

    A qualified take ends naturally and cuts none of its phrase ends; a take whose phrase ends
    could not be aligned does not qualify. A thought that opens its recording qualifies only
    with a take that begins in heard quiet.
    """
    qualified = [
        take
        for take in takes
        if take["natural"]
        and take["phrase_stops"] == []
        and take["required_heard"]
        and (take["opens_quiet"] or not opens_recording)
    ]
    if not qualified:
        return None
    tiebreak = {
        "accurate": lambda take: take["end_ratio"],
        "slower": lambda take: -take["seconds"],
        "brisker": lambda take: take["seconds"],
    }[prefer]
    return min(qualified, key=lambda take: (take["differing_units"], tiebreak(take)))["seed"]


def audition(
    code: str,
    targets_file: str,
    receipt_file: str | None = None,
    *,
    takes: int = 8,
    first: int = 11,
    prefer: str = "accurate",
    name: str = "audition",
) -> None:
    """Synthesize, measure and transcribe takes of each target, then write proposals."""
    edition, folder = Edition(code), repository.ROOT / AUDITIONS / code
    proposals = folder / f"{name}.json"
    if proposals.exists():
        msg = f"Preserve the existing proposals: {proposals}"
        raise FileExistsError(msg)
    targets = _targets(targets_file)
    script, cast = repository.read(edition.script), repository.read(edition.cast)
    records = bound_records(
        receipt_file or cast["performance_recording"]["receipt"], edition.language
    )
    chosen = _chosen(script, cast, records, targets)
    run_ons = {
        (record["id"], child["index"]): following_spoken_text(records, record["id"], child["index"])
        for record, child, (_, run_on) in chosen
        if run_on
    }
    model = group_generation.load_voice_model()
    asr = load_asr()
    aligner = load_aligner()
    folder.mkdir(parents=True, exist_ok=True)
    rows = []
    for record, child, (phrase, _) in chosen:
        run_on = run_ons.get((record["id"], child["index"]))
        row = {
            "segment": record["id"],
            "index": child["index"],
            "text": child["text"],
            "required": phrase,
            "current_seed": child["seed"],
            "aligner": aligner["identity"],
            **({} if run_on is None else {"run_on": run_on}),
            "takes": [],
            "proposed_seed": None,
        }
        for k in range(first, first + takes):
            seed = record["seed"] + k * STRIDE
            audio, _ = group_generation.synthesize(
                model,
                child["spoken_text"] + (run_on or ""),
                repository.ROOT / child["reference_audio"],
                child["reference_text"],
                child,
                seed,
            )
            path = folder / f"{record['id']}-{child['index']:02d}-{seed}.wav"
            heard = (aligner, asr, edition.language, child["spoken_text"], phrase)
            if run_on is None:
                write(str(path), audio, model.sample_rate)
                take = {"seed": seed, **_measured(path, *heard)}
            else:
                measured = _run_on_measured(path, audio, model, aligner, run_on, heard)
                take = {"seed": seed, **measured}
            row["takes"].append(take)
            stops = take["phrase_stops"]
            summary = {
                **{field: take[field] for field in SUMMARY},
                "phrase_stops": None if stops is None else len(stops),
            }
            print(
                json.dumps({"segment": row["segment"], "index": row["index"], **summary}),
                flush=True,
            )
        row["proposed_seed"] = propose(row["takes"], prefer, opens_recording=child["index"] == 1)
        if run_on is not None:
            row["proposed_run_on"] = next(
                (take["run_on"] for take in row["takes"] if take["seed"] == row["proposed_seed"]),
                None,
            )
        rows.append(row)
    proposals.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n")
    proposed = {f"{row['segment']}.{row['index']}": row["proposed_seed"] for row in rows}
    print(
        json.dumps(
            {"proposals": str(proposals.relative_to(repository.ROOT)), "proposed": proposed}
        ),
        flush=True,
    )


def _targets(targets_file: str) -> dict[tuple[str, int], tuple[str, bool]]:
    """The required phrase of each target thought and whether it is read on into the next.

    Targets are keyed by segment and 1-based index.
    """
    targets = {}
    for key, target in repository.read(targets_file).items():
        segment, index = key.split(".")
        if isinstance(target, str):
            targets[segment, int(index)] = (target, False)
        elif (
            isinstance(target, dict)
            and set(target) == {"required", "run_on"}
            and isinstance(target["required"], str)
            and target["run_on"] is True
        ):
            targets[segment, int(index)] = (target["required"], True)
        else:
            msg = f'{key}: a target is a phrase or {{"required": phrase, "run_on": true}}'
            raise ValueError(msg)
    return targets


def _chosen(script: dict, cast: dict, records: list[dict], targets: dict) -> list[tuple]:
    """The receipt's target thoughts, each checked against the script, its recording and cast.

    Returns:
        Each target's record, thought, and required phrase with whether it runs on.
    """
    chosen = [
        (record, child, targets[record["id"], child["index"]])
        for record in records
        for child in record.get("utterance_groups", {}).get("records", [])
        if (record["id"], child["index"]) in targets
    ]
    if len(chosen) != len(targets):
        msg = "Every target must name a thought of the receipt"
        raise ValueError(msg)
    for record, child, _ in chosen:
        if thought_text(script, record["id"], child["index"]) != child["text"]:
            msg = (
                f"{record['id']}.{child['index']}: the receipt does not hold the "
                "current thought; narrate the segment before auditioning it"
            )
            raise ValueError(msg)
    sections = {segment["id"]: segment for segment in script["segments"]}
    for record in {record["id"]: record for record, _, _ in chosen}.values():
        validate_group_inputs(record, root=repository.ROOT, section=sections[record["id"]])
        validate_voice_record(record, cast)
    return chosen


def load_aligner() -> dict:
    """Load the pinned forced aligner, which locates each take's phrase ends and run-on cut.

    Returns:
        The aligner's model and its verified identity.
    """
    folder = repository.ROOT / ALIGNER
    return {"identity": verify_aligner(folder), "model": load_model(str(folder))}


def _run_on_measured(path, audio: np.ndarray, model, aligner: dict, run_on: str, heard) -> dict:
    """A run-on take cut in the quiet after its thought, measured as a take of the thought.

    The whole take is retained beside the cut one, and its alignment locates the thought. A
    take without heard quiet before its next words is measured whole and does not qualify.
    """
    _, _, language, spoken_text, _ = heard
    whole = path.with_name(f"{path.stem}-run-on.wav")
    write(str(whole), audio, model.sample_rate)
    with wave.open(str(whole)) as source:
        pcm = np.frombuffer(source.readframes(source.getnframes()), dtype="<i2")
    items = aligner["model"].generate(str(whole), text=spoken_text + run_on, language=language)
    bounds = thought_bounds([dataclasses.asdict(item) for item in items.items], spoken_text, run_on)
    cut = run_on_cut(pcm, model.sample_rate, *bounds)
    taken = {
        "thought_end": bounds[0],
        "next_start": bounds[1],
        "run_on_take": {
            "path": str(whole.relative_to(repository.ROOT)),
            "wav_sha256": repository.sha(whole),
        },
    }
    if cut is None:
        return {**_measured(whole, *heard), **taken, "natural": False, "run_on": None}
    write(str(path), pcm[:cut], model.sample_rate)
    return {
        **_measured(path, *heard),
        **taken,
        "run_on": {"spoken_text": run_on, "cut_sample": cut},
    }


def _measured(path, aligner: dict, asr, language: str, spoken_text: str, phrase: str) -> dict:
    """A written take's waveform hash, its opening, ending and phrase ends, and what was heard."""
    with wave.open(str(path)) as source:
        rate = source.getframerate()
        pcm = np.frombuffer(source.readframes(source.getnframes()), dtype="<i2")
    heard = transcribe(asr, path, language)
    return {
        "path": str(path.relative_to(repository.ROOT)),
        "wav_sha256": repository.sha(path),
        **opening(pcm, rate),
        **ending(pcm, rate),
        "phrase_stops": _phrase_stops(path, pcm, rate, aligner, language, spoken_text),
        "heard": heard,
        "required_heard": heard_phrase(heard, phrase),
        "differing_units": unit_distance(recognition_units(spoken_text), recognition_units(heard)),
    }


def _phrase_stops(path, pcm, rate: int, aligner: dict, language: str, spoken_text: str):
    """The take's phrase ends that it cuts, or None when its alignment misses its text."""
    found = aligner["model"].generate(str(path), text=spoken_text, language=language)
    items = [dataclasses.asdict(item) for item in found.items]
    try:
        joins = phrase_joins(spoken_text, items, [spoken_text])
    except AlignmentError:
        return None
    ends = [round(items[join.left]["end_time"] * rate) for join in joins]
    return [end for end in phrase_ends(pcm, rate, ends) if end["stops"]]


def apply(code: str, proposals_file: str, *, dry_run: bool = False) -> dict:
    """Bind a proposals file into the edition's cast, writing it unless a dry run."""
    edition = Edition(code)
    script, cast = repository.read(edition.script), repository.read(edition.cast)
    rows = json.loads((repository.ROOT / proposals_file).read_text())
    cast, bound, skipped = bind_proposals(script, cast, rows)
    if not dry_run:
        repository.write(edition.cast, cast)
    return {"language": code, "applied": bound, "skipped": skipped, "dry_run": dry_run}


def main(argv: list[str] | None = None) -> None:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--language", choices=CODES, required=True)
    parser = argparse.ArgumentParser(
        description="Audition alternative takes and bind the selected seeds."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    trial = commands.add_parser(
        "audition", parents=[common], help="Synthesize, measure and rank takes"
    )
    trial.add_argument(
        "--targets",
        required=True,
        help='JSON file mapping "segment.index" to a required phrase',
    )
    trial.add_argument("--takes", type=int, default=8, help="Takes per thought")
    trial.add_argument("--first", type=int, default=11, help="First seed multiple k")
    trial.add_argument(
        "--prefer",
        choices=("accurate", "slower", "brisker"),
        default="accurate",
        help="Break ties by the quietest ending, or by the longest or the shortest take",
    )
    trial.add_argument("--name", default="audition", help="Proposals file stem")
    trial.add_argument(
        "--receipt", help="Narration receipt holding the thoughts (default: the cast's)"
    )
    binding = commands.add_parser(
        "apply", parents=[common], help="Bind proposed seeds into the cast"
    )
    binding.add_argument("--proposals", required=True, help="Proposals JSON written by audition")
    binding.add_argument("--dry-run", action="store_true", help="Report without writing the cast")
    options = parser.parse_args(argv)
    if options.command == "audition":
        audition(
            options.language,
            options.targets,
            options.receipt,
            takes=options.takes,
            first=options.first,
            prefer=options.prefer,
            name=options.name,
        )
    else:
        print(json.dumps(apply(options.language, options.proposals, dry_run=options.dry_run)))


if __name__ == "__main__":
    main()
