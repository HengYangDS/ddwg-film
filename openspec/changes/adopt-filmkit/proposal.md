# Proposal

## Why

`ddwg-film` builds its films with its own copy of the engine in `src/filmkit`. The engine now has its own repository, which released and published `filmkit` 0.1.0 with a sample film, the engine's tests and the boundary that lets a second film use it, and the ETHOS film already builds on it. Two copies would give the engine two owners.

## What Changes

- Depend on `filmkit` 0.1.0 through a uv Git source at its tag `v0.1.0`, keeping every other locked package version, and remove `src/filmkit` with the tests that moved to `filmkit`. The film keeps the tests of its own content: its composition against both scripts, its retained narration receipts, its release manifest, and its declaration and players.
- Declare `[picture] fonts` and `[review] readings` in `content/film.toml`; `content/review/readings.json` carries the Mandarin readings, heteronyms, variants and grammar that the engine copy held.
- Run the Node tools through `python -m filmkit.tools`.
- Rebuild both editions with the release and compare them with `v1.0.0` under the reproduction standard.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `film-engine`: the engine is the pinned `filmkit` release instead of a package in this repository, and the declaration also names the fonts and the listening-plan readings.

## Impact

- `pyproject.toml` becomes the film's project, depending on `filmkit`; no package is built here any more, and `VERSION` stays the only version source.
- The films, captions, transcripts, covers and staged picture documents stay as `v1.0.0` published them; the comparison proves it.
- Out of scope: any engine change, which goes through `filmkit`'s own Change and release.
