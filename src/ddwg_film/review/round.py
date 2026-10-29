"""Prepare and record one independent review round of both editions.

A round sets the reviewed packages aside before the next render, binds the packaged
members for the real-browser player check, writes each edition's reviewer prompt with
the exact media hashes and the previous round's findings, and records the finished
reviews as the production reviews that `ddwg_film.delivery.verification` accepts. A
round's directory defaults to build/evidence/reviews/round-<n>/. Setting aside and
recording are planned and checked in full before anything moves or is written, and
--dry-run stops after the plan. A refused input raises `ReviewError`, which each command
reports as its refusal.

Usage: python -m ddwg_film.review.round set-aside --round <n> --purpose <text>
           [--review-dir <dir>] [--without-picture] [--dry-run]
       python -m ddwg_film.review.round bind --out <file>
       python -m ddwg_film.review.round prompts --round <n> --previous <dir>
           [--changes <file>] [--out-dir <dir>]
       python -m ddwg_film.review.round record --round-dir <dir> [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import NamedTuple

import ddwg_film.repository as repository
import ddwg_film.sources as sources
import ddwg_film.specification as specification
from ddwg_film.picture.rendering import COMPOSITION_SCRIPT
from ddwg_film.production import CODES, Edition
from ddwg_film.review import ReviewError
from ddwg_film.review.record import DIMENSIONS, SCHEMA_VERSION, overall

EXIT_CONDITION = "Retire after the successor delivery is accepted"
HUMAN_LISTENING = (
    "Audio is scored from automated evidence: recognition, word timings, rate, the "
    "pause hierarchy, quiet edges, thought levels, endings and waveforms. Human "
    "listening is a separate acceptance after delivery and does not affect the scores."
)
# The round's own inputs that each reviewer prompt names.
ROUND_INPUTS = (
    "pronunciation-listening-plan.json",
    "measurements.json",
    "player-check-artifacts.json",
)
# A reported overall score may differ from the mean of its scores by this much rounding.
OVERALL_ROUNDING = 0.05


class SetAside(NamedTuple):
    """One edition's reviewed members, the folder they move to and its manifest."""

    code: str
    target: Path
    sources: list[Path]
    manifest: dict


class ProductionReview(NamedTuple):
    """One edition's production review record, its place and the report it copies."""

    target: Path
    report: Path
    record: dict


def cited(path: Path) -> str:
    """A path as the prompts cite it: ROOT/<path> inside the repository."""
    text = repository.relative(path)
    return text if Path(text).is_absolute() else f"ROOT/{text}"


def present(paths: list[Path]) -> list[Path]:
    """The given files, refused when any is missing."""
    missing = [repository.relative(path) for path in paths if not path.is_file()]
    if missing:
        msg = f"missing {', '.join(missing)}"
        raise ReviewError(msg)
    return paths


def round_directory(number: int) -> Path:
    return repository.ROOT / "build/evidence/reviews" / f"round-{number}"


def edition_review(path: Path, code: str) -> tuple[dict, dict]:
    """A round's review file and its entry for one edition, refused when either is absent."""
    review = repository.read(present([path])[0])
    entry = review.get("editions", {}).get(code)
    if not isinstance(entry, dict):
        msg = f"{repository.relative(path)} reviews no {code} edition"
        raise ReviewError(msg)
    return review, entry


def plan_set_aside(
    number: int, purpose: str, review_dir: Path, *, picture: bool = True
) -> list[SetAside]:
    """Plan moving a reviewed round's packages aside before the next render and package.

    package-film refuses to extend a package bound to changed inputs, and the next
    render would overwrite the reviewed picture. Each edition's two films and package
    record, and its rendered picture unless picture is false (when the successor's
    render has already replaced it; the UHD film carries the same picture stream), are
    to be renamed within the volume into build/artifacts/film/superseded/round-<n>/<code>/
    and recorded in manifest.json with their hashes, consumer and exit condition. The plan
    is refused unless, for both editions, the target is new, every member exists on the
    target's volume and the round's review binds both film hashes.
    """
    plans = []
    for code in CODES:
        edition = Edition(code)
        target = repository.ROOT / "build/artifacts/film/superseded" / f"round-{number}" / code
        if target.exists():
            msg = f"{repository.relative(target)} exists; inspect it before setting aside again"
            raise ReviewError(msg)
        sources = [*edition.films, edition.film_package, *([edition.picture] if picture else [])]
        present(sources)
        volume = next(parent for parent in target.parents if parent.exists()).stat().st_dev
        if any(path.stat().st_dev != volume for path in sources):
            msg = f"{code}: a member lies outside the volume of {repository.relative(target)}"
            raise ReviewError(msg)
        review = review_dir / f"review-{code}.json"
        bound = {item["sha256"] for item in edition_review(review, code)[1].get("media", [])}
        hashes = {path: repository.sha(path) for path in sources}
        if not all(hashes[film] in bound for film in edition.films):
            msg = f"{code}: the packaged films are not the ones round {number} reviewed"
            raise ReviewError(msg)
        members = [
            {
                "source": repository.relative(path),
                "path": repository.relative(target / path.name),
                "sha256": hashes[path],
                "bytes": path.stat().st_size,
            }
            for path in sources
        ]
        manifest = {
            "purpose": f"{code} package and picture reviewed in round {number}: {purpose}",
            "consumer": f"{repository.relative(review)} binds the two film hashes",
            "exit_condition": EXIT_CONDITION,
            "moved_at": None,
            "members": members,
        }
        plans.append(SetAside(code, target, sources, manifest))
    return plans


def move_aside(plans: list[SetAside]) -> None:
    """Move each planned member aside and read it back by its hash.

    Each target's manifest is written before its first move, with moved_at null, so an
    interrupted set-aside still names every member it was moving; once every member has
    moved, the manifest records when.
    """
    for plan in plans:
        plan.target.mkdir(parents=True)
        repository.write(plan.target / "manifest.json", plan.manifest)
        for source, member in zip(plan.sources, plan.manifest["members"], strict=True):
            moved = source.rename(plan.target / source.name)
            if source.exists() or repository.sha(moved) != member["sha256"]:
                msg = f"{member['path']}: set-aside readback differs"
                raise ReviewError(msg)
        moved_at = datetime.now(UTC).isoformat()
        repository.write(plan.target / "manifest.json", {**plan.manifest, "moved_at": moved_at})


def set_aside_report(plans: list[SetAside], *, dry_run: bool) -> dict:
    """Each edition's set-aside target and members, as the command prints them."""
    return {
        "dry_run": dry_run,
        "editions": [
            {
                "language": plan.code,
                "target": repository.relative(plan.target),
                "members": [member["path"] for member in plan.manifest["members"]],
            }
            for plan in plans
        ],
    }


def bind(out: Path) -> dict:
    """Bind the packaged delivery members for the real-browser player check.

    The members are the neutral language entry and, for each edition, its two films and
    the viewing package its package record names. Writes the destination and each
    member's path and SHA-256, the shape the player check reads.
    """
    destination = repository.ROOT / "build/artifacts/film"
    paths = ["index.html"]
    for code in CODES:
        edition = Edition(code)
        viewing = repository.read(present([edition.viewing_package])[0])
        paths += [f"{code}/{film.name}" for film in edition.films]
        paths += [f"{code}/{member['path']}" for member in viewing["members"]]
    present([destination / path for path in paths])
    members = [{"path": path, "sha256": repository.sha(destination / path)} for path in paths]
    repository.write(out, {"destination": str(destination), "members": members})
    return {"members": len(members), "binding": repository.relative(out)}


# The reviewer prompt, filled per edition: a str.format template beside this module.
TEMPLATE = Path(__file__).with_name("prompt.md").read_text(encoding="utf-8")


def inner_caps(policy: dict) -> str:
    marks = policy.get("inner_pause_caps_seconds") or {}
    names = {",": "commas", "，": "commas", "、": "enumeration commas"}
    extra = ", ".join(f"{value:.2f} s at {names.get(mark, mark)}" for mark, value in marks.items())
    cap = f"{policy['inner_pause_cap_seconds']:.2f} s"
    return f"{cap} ({extra})" if extra else cap


def inner_floors(policy: dict) -> str:
    floors = policy.get("inner_pause_floors_seconds")
    if not floors:
        return "none declared"
    return ", ".join(f"{marks} {value:.3g} s" for marks, value in floors.items())


def inner_breath(policy: dict) -> str:
    breath = policy.get("inner_breath")
    if not breath:
        return "none declared"
    seconds, pause = breath["longest_group_seconds"], breath["pause_seconds"]
    return f"{seconds:g} s with a {pause:g} s pause"


def boundary(policy: dict) -> str:
    """A script's declared thought boundary ratio and the margin each floored boundary adds."""
    margin = policy.get("thought_boundary_margin_seconds", 0)
    return f"{policy['thought_boundary_ratio']} and {margin:.2f} s"


def finding_index(findings: list[dict]) -> str:
    """Finding identifiers grouped by severity, in order of first appearance."""
    groups: dict[str, list[str]] = {}
    for finding in findings:
        groups.setdefault(finding["severity"], []).append(finding["id"])
    return "; ".join(f"{severity} {', '.join(ids)}" for severity, ids in groups.items())


def prompt_context(out_dir: Path, previous: Path, changes: Path | None) -> dict:
    """The template fields both editions' prompts share.

    They name the canonical source, the round's places, the delivery format and the pause
    and level policies the current scripts and assemblies declare.
    """
    zh, en = (repository.read(Edition(code).script)["voice_performance"] for code in CODES)
    manifest = sources.manifest()
    assemblies = [repository.read(Edition(code).audio_assembly) for code in CODES]
    levels = {item["program_level"]["policy"]["integrated_lufs"] for item in assemblies}
    if len(levels) != 1:
        msg = f"the soundtracks declare different program levels: {sorted(levels)}"
        raise ReviewError(msg)
    return {
        "root": repository.ROOT,
        "source": sources.location(),
        "documents": ", ".join(Path(member["path"]).stem for member in manifest["members"]),
        "out": cited(out_dir),
        "previous": cited(previous),
        "changes": "" if changes is None else changes.read_text().strip() + "\n",
        "duration": specification.DURATION,
        "fps": specification.FPS,
        "rate": f"{specification.RATE / 1000:g}",
        "program": f"{levels.pop():g}",
        "caps": f"{inner_caps(zh)} Chinese; {inner_caps(en)} English",
        "floors": f"Chinese {inner_floors(zh)}; English {inner_floors(en)}",
        "breath": f"Chinese {inner_breath(zh)}; English {inner_breath(en)}",
        "tolerances": f"{zh['thought_level_tolerance_db']} dB Chinese, "
        f"{en['thought_level_tolerance_db']} dB English",
        "ratios": f"{boundary(zh)} Chinese, {boundary(en)} English",
        "codas": f"{zh['coda_thought_pause_seconds']:.2f} s Chinese, "
        f"{en['coda_thought_pause_seconds']:.2f} s English",
        "dimensions": "\n".join(
            f"{index}. {name}: {text}" for index, (name, text) in enumerate(DIMENSIONS.items(), 1)
        ),
    }


def prompts(previous: Path, out_dir: Path, changes: Path | None = None) -> dict:
    """Write each edition's independent reviewer prompt for one round.

    Each prompt names the exact packaged films with their SHA-256, the previous round's
    review and its findings, the round's own inputs and the pause policy the current
    scripts declare. changes holds Markdown context bullets for this round, such as the
    repairs since the previous review and their dispositions. The previous review is
    context to verify, never a score to inherit. Nothing is written unless both
    editions' films and previous reviews and the round's inputs exist.
    """
    present([out_dir / name for name in ROUND_INPUTS])
    context = prompt_context(out_dir, previous, changes)
    texts = {}
    for code in CODES:
        edition = Edition(code)
        other = next(name for name in CODES if name != code)
        media = "\n".join(
            f"- {film} (SHA-256 {repository.sha(film)})" for film in present(edition.films)
        )
        review = present([previous / f"review-{code}.json", previous / f"{code}-review.md"])[0]
        findings = edition_review(review, code)[1]["findings"]
        working = previous / code
        scripts = (
            f" The previous reviewer's working files are in {cited(working)}/; you may "
            "copy and adapt its scripts under your own output directory."
            if working.is_dir()
            else ""
        )
        texts[code] = TEMPLATE.format(
            **context,
            language=edition.language,
            code=code,
            other=other,
            other_language=Edition(other).language,
            media=media,
            findings=f"findings: {finding_index(findings)}" if findings else "no findings",
            scripts=scripts,
        )
    written = []
    for code, text in texts.items():
        path = out_dir / f"prompt-{code}.md"
        path.write_text(text)
        written.append(repository.relative(path))
    return {"prompts": written}


def reviewed_scores(code: str, review: dict) -> dict:
    """A review's scores in record order.

    They must be exactly the declared dimensions, and the review must report their mean
    as its overall score.
    """
    if set(review.get("scores", {})) != set(DIMENSIONS):
        msg = f"{code}: a review scores exactly the eight declared dimensions"
        raise ReviewError(msg)
    scores = {name: review["scores"][name] for name in DIMENSIONS}
    mean, reported = overall(scores), review.get("overall")
    if not isinstance(reported, int | float) or isinstance(reported, bool):
        msg = f"{code}: a review reports its overall score"
        raise ReviewError(msg)
    if abs(reported - mean) > OVERALL_ROUNDING:
        msg = f"{code}: reported overall {reported} is not the mean {mean}"
        raise ReviewError(msg)
    return scores


def review_records(round_dir: Path) -> list[ProductionReview]:
    """Each edition's production review record from a finished round, checked, not written.

    Reads review-<code>.json and <code>-review.md from the round directory and derives
    the schema 2 record that the film verifier accepts beside a copy of the report: the
    exact reviewed media, script and composition hashes, the eight scores and their
    mean, every finding and the human-listening state. Both reviews must cover the
    current delivered films, score exactly the eight dimensions and report their mean.
    """
    records = []
    for code in CODES:
        edition = Edition(code)
        source, report = present(
            [round_dir / f"review-{code}.json", round_dir / f"{code}-review.md"]
        )
        review, entry = edition_review(source, code)
        current = {
            repository.relative(film): repository.sha(film) for film in present(edition.films)
        }
        reviewed = {
            repository.relative(repository.ROOT / item["path"]): item["sha256"]
            for item in entry.get("media", [])
        }
        if reviewed != current:
            msg = f"{code}: reviewed media differ from the current delivered films"
            raise ReviewError(msg)
        scores = reviewed_scores(code, entry)
        target = edition.production_review
        record = {
            "schema_version": SCHEMA_VERSION,
            "language": code,
            "reviewer": review["reviewer"],
            "recorded_at": datetime.now(UTC).isoformat(),
            "media": [{"path": path, "sha256": sha} for path, sha in sorted(current.items())],
            "script_sha256": repository.sha(edition.script),
            "composition_sha256": repository.sha(repository.ROOT / COMPOSITION_SCRIPT),
            "scores": scores,
            "overall": overall(scores),
            "findings": entry["findings"],
            "human_listening": {
                "state": "not_performed",
                "basis": HUMAN_LISTENING,
                "checklist": entry.get("human_listening_checklist", []),
            },
            "report": {
                "path": repository.relative(target.with_name("production-review.md")),
                "sha256": repository.sha(report),
            },
            "source_review": {
                "path": repository.relative(source),
                "sha256": repository.sha(source),
            },
        }
        records.append(ProductionReview(target, report, record))
    return records


def write_review_records(records: list[ProductionReview]) -> None:
    """Write each production review record beside a copy of its report."""
    for review in records:
        review.target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(review.report, review.target.with_name("production-review.md"))
        repository.write(review.target, review.record)


def record_report(records: list[ProductionReview], *, dry_run: bool) -> dict:
    """Each edition's recorded overall, lowest score and material findings, as printed."""
    return {
        "dry_run": dry_run,
        "editions": [
            {
                "language": review.record["language"],
                "overall": review.record["overall"],
                "minimum": min(review.record["scores"].values()),
                "material": sum(f.get("severity") == "material" for f in review.record["findings"]),
            }
            for review in records
        ],
    }


def run_set_aside(options: argparse.Namespace) -> dict:
    review_dir = (options.review_dir or round_directory(options.round)).resolve()
    plans = plan_set_aside(
        options.round, options.purpose, review_dir, picture=not options.without_picture
    )
    if not options.dry_run:
        move_aside(plans)
    return set_aside_report(plans, dry_run=options.dry_run)


def run_bind(options: argparse.Namespace) -> dict:
    return bind(options.out.resolve())


def run_prompts(options: argparse.Namespace) -> dict:
    return prompts(
        options.previous.resolve(),
        (options.out_dir or round_directory(options.round)).resolve(),
        options.changes.resolve() if options.changes else None,
    )


def run_record(options: argparse.Namespace) -> dict:
    records = review_records(options.round_dir.resolve())
    if not options.dry_run:
        write_review_records(records)
    return record_report(records, dry_run=options.dry_run)


def command_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    aside = commands.add_parser("set-aside", help="move a reviewed round's packages aside")
    aside.add_argument("--round", type=int, required=True, metavar="N")
    aside.add_argument(
        "--purpose",
        required=True,
        metavar="TEXT",
        help="why the reviewed packages are superseded, recorded in each manifest",
    )
    aside.add_argument(
        "--review-dir",
        type=Path,
        metavar="DIR",
        help="the round's reviews (default build/evidence/reviews/round-N)",
    )
    aside.add_argument(
        "--without-picture",
        action="store_true",
        help="leave the rendered picture in place once its successor has replaced it",
    )
    aside.add_argument("--dry-run", action="store_true", help="plan without moving anything")
    aside.set_defaults(run=run_set_aside)
    binding = commands.add_parser("bind", help="bind the packaged members for the player check")
    binding.add_argument("--out", type=Path, required=True, metavar="FILE")
    binding.set_defaults(run=run_bind)
    prompt = commands.add_parser("prompts", help="write the round's reviewer prompts")
    prompt.add_argument("--round", type=int, required=True, metavar="N")
    prompt.add_argument(
        "--previous",
        type=Path,
        required=True,
        metavar="DIR",
        help="the previous round's review directory",
    )
    prompt.add_argument(
        "--changes",
        type=Path,
        metavar="FILE",
        help="Markdown context bullets: the repairs since the previous review",
    )
    prompt.add_argument(
        "--out-dir",
        type=Path,
        metavar="DIR",
        help="the round's directory (default build/evidence/reviews/round-N)",
    )
    prompt.set_defaults(run=run_prompts)
    recorder = commands.add_parser(
        "record", help="record the round's reviews as production reviews"
    )
    recorder.add_argument("--round-dir", type=Path, required=True, metavar="DIR")
    recorder.add_argument("--dry-run", action="store_true", help="check without writing")
    recorder.set_defaults(run=run_record)
    return parser


def main(argv: list[str] | None = None) -> None:
    options = command_parser().parse_args(argv)
    try:
        result = options.run(options)
    except ReviewError as error:
        msg = f"{options.command}: {error}"
        raise SystemExit(msg) from None
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
