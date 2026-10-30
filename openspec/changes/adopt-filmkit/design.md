# Design

## Context

`ddwg-film` `v1.0.0` carries the engine as the package `src/filmkit`, built by hatchling from this repository, with 66 source files and the engine's tests. `filmkit` 0.1.0 was formed from this repository's `37549a9` and differs from the copy only where a second film needed it: the declaration names the fonts and the listening-plan readings, the Node tools run through `python -m filmkit.tools`, and the picture tools gained two fixes. A dry run on 2026-10-30, with this repository's tracked tree minus `src/filmkit`, the two declaration fields and the filmkit lane's environment, reproduced this film's staged UHD documents, listening plan, timelines, assembly receipts, narration selections, subtitles, transcripts, chapters, players and covers byte for byte.

## Goals / Non-Goals

**Goals:**

- One owner for the engine: the film installs the `filmkit` release and tracks no engine source.
- The published films reproduce with the release under the reproduction standard.

**Non-Goals:**

- Engine changes, which go through `filmkit`'s Changes and releases.
- A new edition of the films or any change to their sources.

## Decisions

### The film's project

`pyproject.toml` names the project `ddwg-film`, declares `filmkit` as its one dependency with a uv Git source at `https://github.com/HengYangDS/filmkit` and the tag `v0.1.0`, and sets `[tool.uv] package = false`, so uv installs the dependencies without building this repository. `VERSION` stays the only version source, read by hatchling, as ETHOS requires of a repository that tags releases. The lock is updated from the current `uv.lock`, so uv keeps every locked version it can: the narration's bit-identical reproduction was verified under these versions (MLX 0.32.3 among them), and a fresh resolution would move MLX to 0.32.4 and Transformers to 5.22.0. The lock is checked to differ from `v1.0.0`'s only in the root project and the added `filmkit`.

The film stays on 0.1.0. 0.1.1, prepared for the ETHOS film, changes only how a film without covers loads and packages; this film has its covers.

### The film's declaration

`[picture] fonts` names the two full Noto Sans CJK SC faces and the two IBM Plex Sans faces in the order the engine copy staged them. `[review] readings` names `content/review/readings.json`, written once from the engine copy's `MANDARIN_READINGS`, `HETERONYMS`, `EXTRA_VARIANTS` and `GRAMMAR` by reading their syntax tree, so the listening plan the release derives equals the copy's.

### The film's tests

The engine's tests, which `filmkit` carries with its sample film, leave with `src/filmkit`. The film keeps what only it can test:

- its composition against both scripts: every authored scene paints from its own spoken cues, speech never plays over an empty picture, each scene's paints trace to their line of `film.js`, the camera frames each scene, Chinese names break only after a list or clause mark, labels without a joint are authored as their lines, and the pinned timeline engine seeks as the composition drives it;
- its retained narration receipts, which reproduce from its scripts and casts with the installed engine;
- its release manifest and film-bound sources;
- its declaration and players.

The composition tests import the engine's headless runtime from the installed release, which `tests/engine.mjs` locates through `uv run --frozen --offline --no-sync python`, so they follow the lock wherever uv keeps the environment. The behavior gate measures coverage of `picture/film.js`, the film's one production script; `test:coverage` excludes the installed engine and the tests from c8's report, which ETHOS reads from that script.

### Tasks and gates

The Mise tasks keep their names and steps; each Node tool runs through `python -m filmkit.tools`, which copies the release's tools below the film and runs them with the film's npm packages. The gate registry, the CI projection and the film gates are unchanged: they already run `python -m filmkit.<module>`.

## Risks / Trade-offs

- [The release reads a film-bound input differently from the copy] → The full rebuild and comparison with `v1.0.0` measure every layer; the dry run already found the staged documents identical.
- [A transitive package moves when the lock is updated] → The lock diff is checked against `v1.0.0` before the rebuild.
- [The film's tests lose coverage of `film.js`] → The behavior gate's 90% line threshold is measured on `film.js` alone.

## Migration Plan

1. Change the project and lock, the declaration, the readings, the tasks and the tests in this Change's lane, and check them.
2. Supply, rebuild both editions and compare them with `v1.0.0`.
3. Archive, prove, land and close out; publish `dev` and `main` to GitHub after the user confirms. A later release tag records the migration; the published films are unchanged.

Rollback: before landing, discard the lane. After landing, a revert of the Change's commits restores `src/filmkit`; the published films need nothing.
