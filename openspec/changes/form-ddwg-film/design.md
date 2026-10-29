# Design

## Context

See `proposal.md` for the motivation. The source is the private repository `ddwg-introduction-film` at `fa1e974` (ETHOS `0.2.0-alpha.18`, CPython 3.12.16): `src/ddwg_film` holds 24.3k lines, of which the film's picture composition `film.js` is 8,520; `content/` holds both editions' scripts, casts with their seeds and the pronunciation table; `assets/` holds the narrator references, covers, fonts and a vendored GSAP copy. The accepted round-24 films were rendered by HyperFrames 0.8.150 from OpenMontage's local runtime with `--gpu --browser-gpu --experimental-fast-capture`, which encodes through VideoToolbox. The renderer path, its version and the browser build were not pinned by that repository.

Measurements taken on 2026-10-29 shape this design:

- Re-synthesizing ten thoughts (Chinese segment 24 with a run-on retake, English segment 10) from their recorded seeds gave bit-identical recordings under Python 3.12.16, mlx 0.32.3, mlx-audio 0.5.8 and the Qwen3-TTS Base revision `a6eb4f68`.
- Two identical UHD captures of one composition differed in 157 of 180 frames, mean PSNR 111.8 dB and worst 106.1 dB; software capture differed in 136 of 180, worst 101.9 dB. GPU-encoded bitstreams of the same capture differed too. HyperFrames offers a Docker render for determinism, but its image is built on demand from unpinned Debian packages and renders fonts through Linux, which would change the accepted picture.

ETHOS created this repository with `ethos adopt --create` (foundation starter). Its gates come from the repository's own registry; hosted CI is a post-publication observation; native tools a gate consumes must be declared.

## Goals / Non-Goals

**Goals:**

- One repository that rebuilds both editions from its tracked sources on Apple-silicon macOS, offline after one supply step.
- An engine that a second film can use without editing it, separated now so that extracting it later is a move.
- Mature tools in place of hand-written plumbing wherever the accepted films' bytes stay identical.

**Non-Goals:**

- Byte-identical picture or film containers: the measurements above rule them out on this platform.
- Any change to either film's script, narration, picture or review.
- Linux, Intel or non-macOS rebuilds; publication before the user confirms; the engine's own repository.

## Decisions

### Snapshot import without history

The first commit after the starter imports the selected paths of `fa1e974` with `git archive`, then the repository is restructured in place. Rewriting the private history was rejected: it still publishes 262 commits of process noise, keeps the risk of leaking the organization address and the custody paths, and buys nothing a reader needs. The private repository stays an archive that no build reads.

### Layout and engine boundary

```text
src/filmkit/   engine: narration, captions, soundtrack, picture driver and audits, packaging, verification
picture/       this film's composition: film.js, film.css, index.html
content/       film.toml, scripts, casts, narration texts, players, entry page, source manifest, review prompt
assets/        narrator references, covers, fonts
tests/         engine and film tests
build/         ignored output: runtime/tool-cache, runtime/work, artifacts, evidence
```

The film declares itself in `content/film.toml`, validated by pydantic before any work: the file prefix, the Documents folder, the entry page, the source manifest, each edition's sources folder, cover and caption terms, and the review prompt, floors and scored dimensions. The ETHOS paradigm keeps the repository root to its catalog, so the declaration lives with the content. Each script already declares its edition's title, author, language, duration, frame rate and chapters; the engine reads those from the scripts rather than repeating them, and refuses scripts that disagree or a frame rate other than the 60 fps it encodes. Each edition has its own player page, so the engine no longer translates one player into another. A test scans the engine's sources for the film's identities: its prefix, Documents folder, source repository, titles, author and chapter titles. A sample film that builds end to end belongs to the engine's own repository and is built with its extraction. Packaging writes each edition's shot plan under `build/evidence/`, and the review workflow records each production review there beside its report; the verifier finds the report beside the record, so a published record keeps working wherever it is placed. Each edition's narration text stays tracked for readers; only script edits write it, and the verifier checks it against the script. A uv workspace was considered and deferred: it gives the same guarantee with more structure, and the extraction will create a separate repository anyway.

### Pinned supply

- Mise locks Node 26.12.1, CPython 3.12.16, uv 0.13.5 and ETHOS `0.2.0-alpha.19`.
- npm locks `hyperframes` 0.8.150 with the exact dependency tree the accepted films were rendered with (every package's version and integrity equal the renderer's lock, except a patch release of `prettier` that its range admits), plus `@puppeteer/browsers`, `puppeteer-core` 25.12.0, `gsap` 3.15.0 and `prettier`. GSAP is staged from the npm package, byte-identical to the vendored copy it replaces, and the OpenMontage runtime path is removed.
- `mise run film:supply` installs chrome-headless-shell 152.0.7977.30, the build that HyperFrames 0.8.150 pins, into `build/runtime/tool-cache/browsers` through `@puppeteer/browsers`, and checks its executable's SHA-256. The renderer and the real-browser checks run it unless `FILM_CHROMIUM_PATH` names another.
- The same task downloads the voice, recognizer and aligner snapshots at their pinned revisions into `build/runtime/tool-cache/narration-*` through huggingface_hub, which honours `HF_ENDPOINT` for a mirror, and checks each weights file's SHA-256 and recorded revision. The engine loads each model only from its checked folder, so the build after the supply needs no network.
- FFmpeg, ExifTool and rsync 3 stay with their Homebrew owner, host prerequisites that the README and `AGENTS.md` name; the comparison report records the FFmpeg version.
- HyperFrames sends telemetry, checks for updates and silently upgrades itself in place by default; every render sets `HYPERFRAMES_NO_TELEMETRY`, `DO_NOT_TRACK`, `HYPERFRAMES_NO_UPDATE_CHECK` and `HYPERFRAMES_NO_AUTO_INSTALL`, and keeps its font cache under the tool cache. A render cancels itself when any ancestor process exits, so a render's wrapper must outlive it.

OpenMontage's runtime was rejected as a source: it is unpinned, licensed AGPL-3.0 and was upgraded in place. The Docker render was rejected for this release for the reasons in Context.

### The pipeline as Mise tasks

The build is a set of declared Mise tasks (`film:supply`, `film:narrate`, `film:sound`, `film:picture`, `film:package`, `film:verify`, `film:build`, `film:compare`) that call the engine's commands. Receipts stay the provenance record, written by one engine module. DVC was rejected: 42 direct dependencies including a task queue and default telemetry, a single active maintainer, and a lock that a nondeterministic picture would rewrite on every rebuild. Snakemake and doit add nothing over Mise, which the toolchain already owns.

### Reproduction standard

A rebuild is compared layer by layer with the published release:

- the soundtracks before encoding and the staged picture documents: the bytes the release manifest records;
- captions, transcripts and covers: byte-identical to the published assets;
- the films: the same frame counts, decoded audio, streams, durations, chapters and tags, and every decoded frame's PSNR against the published film. With the staged document, renderer and browser build identical, a rebuild and the published film are two renders of one stage, so the first comparison measures the capture and encoding variation: its lowest frames are inspected side by side, and its minimum becomes each film's floor in the manifest, which later rebuilds must meet.

Thought recordings are not published; the soundtrack digest binds them, and for `v1.0.0` each rebuilt recording was also compared with the accepted round's retained one. A recording that does not regenerate byte-identically is not replaced silently: it becomes a tracked source asset with its provenance. The review records bind the published films; a rebuild inherits their acceptance only through this standard.

### Mature tools, without changing bytes

- pydantic validates `content/film.toml`.
- The current writer keeps writing SRT and WebVTT. pysubs2 1.9.0, given the accepted cues, ends an SRT with an extra blank line and numbers every WebVTT cue, so its output differs from the accepted captions; trimming its output would cost more code than the writer it replaces.
- REUSE was measured and rejected: the ETHOS paradigm admits only its catalogued entries at the repository root and `REUSE.toml` is not one of them, so `reuse lint` could not cover the root manifests and locks. ETHOS's own license contract declares the licenses instead, as Publication describes.
- `rsync --checksum` places the Documents delivery and moves every entry it replaces or removes into a predecessor folder under `build/`, and `shasum -a 256 -c` reads the delivery back; this replaces the hand-written retention and copy code. The delivery task runs the film verifier first, which binds every member to its package records. The engine requires rsync 3, which Homebrew installs.
- The hand-written BS.1770-4 K-weighting stays: a library computes slightly different gains and would change the soundtracks. It moves to a later engine version together with a new edition and its review.

### Publication and the comparison

The `v1.0.0` release publishes, per edition, `<prefix>-uhd.mp4`, `<prefix>-1080p-captioned.mp4`, `<prefix>.srt`, `<prefix>.vtt`, `<prefix>-transcript.md`, `<prefix>-cover.png`, `<prefix>-production-review.json` and `<prefix>-production-review.md`, plus `SHA256SUMS`. The tracked manifest `content/release.json` records each asset's name, size and SHA-256, each edition's soundtrack and staged-document digests, and each film's PSNR floor once it is calibrated. Its `v1.0.0` values are recorded once from the accepted round-24 files; a later film assembles its release from its own reviewed build when the engine gains that command. The Release itself, the tag and the remotes wait for the user's confirmation.

A rebuild cannot carry the review, because its films differ from the reviewed bytes by render variation. `film:build` therefore ends with the technical verification, and `film:compare` compares the rebuild with the published assets in `build/artifacts/release/`, downloaded from the release or placed there by the maintainer, and writes its report under `build/evidence/reproduction/`. The `film-media` gate runs the technical verification and a `film-reproduction` gate runs the comparison, so the two local film gates show that the checkout's build reproduces what was published.

The root `LICENSE` carries the MIT text that ETHOS recognizes, and `pyproject.toml` declares the same identifier. `NOTICE`, a catalogued root entry, names the content paths that `LICENSES/CC-BY-4.0.txt`, the Creative Commons legal code marked vendored, covers; every other tracked file is code. It also names the fonts' OFL-1.1 texts beside them, the third-party software and models the build installs under their own licenses, and the narrator's provenance. Because the repository tags releases, ETHOS keeps `VERSION` as the only version source: `pyproject.toml` declares the version dynamic and hatchling reads it from `VERSION`, since uv_build supports no dynamic version. `CHANGELOG.md` follows Keep a Changelog, its `1.0.0` entry is the Release's notes, and `.ethos/release.toml` declares the `v*` tags and the GitHub and GitLab peers without creating any remote.

### CI

ETHOS projects its full proof into GitHub Actions and GitLab CI, on Apple-silicon macOS runners, so hosted CI and a local proof run the same gates. The proof sets therefore hold only the portable gates: static analysis, the Python and Node suites and source integrity. The `film-media` and `film-reproduction` gates need the supplied models, an hour-long rebuild and the published release, so they stay registered outside both proof sets and run locally through `ethos prove --gate film-media --gate film-reproduction --execute`, which is the films' acceptance. Keeping them in the full proof was rejected: every hosted run would fail on inputs CI cannot have.

## Risks / Trade-offs

- [Some recordings do not regenerate byte-identically] → They become tracked source assets with their provenance; no changed take enters silently.
- [A tolerance could hide a real picture change] → The staged document must hash identically, frame counts must match exactly, and the lowest frames are inspected side by side before the floor is recorded.
- [Supply hosts are unavailable] → Supply runs once and every later build is offline; the model endpoint can be a mirror.
- [Gate registry differences under alpha.19] → The registry is adapted in the first task group and proved before the archive.
- [The rename to `filmkit` breaks an import path] → The full Python and Node suites run after the move, before any other change.

## Migration Plan

The private repository is frozen at `fa1e974` and archived after this repository reproduces the films. The accepted films are copied from its ignored `build/` into this repository's `build/` only as the comparison reference. Rollback is the private repository itself, which keeps working unchanged.
