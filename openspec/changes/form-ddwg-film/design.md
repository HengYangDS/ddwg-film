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
content/       scripts, casts, pronunciations, source manifest, delivery pages, review policy
assets/        narrator references, covers, fonts
film.toml      declared parameters: languages, runtime, frame rate, renditions, models, source, metadata
tests/         engine tests with a sample film, and film tests
build/         ignored output: runtime/tool-cache, runtime/work, artifacts, evidence
```

The engine reads every film-specific value from `film.toml`, validated by pydantic, and from the paths it declares. A test scans the engine's sources for the film's declared identities, and a sample film of a few seconds builds end to end through the engine. A uv workspace was considered and deferred: it gives the same guarantee with more structure, and the extraction will create a separate repository anyway.

### Pinned supply

- Mise locks Node 26.12.1, CPython 3.12.16, uv 0.13.5 and ETHOS `0.2.0-alpha.19`.
- npm locks `hyperframes` 0.8.150, the `puppeteer-core` it was accepted with, `@puppeteer/browsers`, `gsap` 3.15.0 and `prettier`. The vendored GSAP copy and the OpenMontage runtime path are removed.
- The supply task installs chrome-headless-shell 152.0.7977.30 into `build/runtime/tool-cache/` through `@puppeteer/browsers` and points the renderer and the audits at it.
- The supply task downloads the speech, aligner and recognition models from Hugging Face at their pinned revisions into `build/runtime/tool-cache/` and checks their files; the endpoint may be a mirror.
- FFmpeg stays with its Homebrew owner, declared as a native tool; each build records its version.
- `HYPERFRAMES_NO_TELEMETRY=1` and `DO_NOT_TRACK=1` are set for every render.

OpenMontage's runtime was rejected as a source: it is unpinned, licensed AGPL-3.0 and was upgraded in place. The Docker render was rejected for this release for the reasons in Context.

### The pipeline as Mise tasks

The build is a set of declared Mise tasks (`film:supply`, `film:narrate`, `film:sound`, `film:picture`, `film:package`, `film:verify`, `film:build`) that call the engine's commands. Receipts stay the provenance record, written by one engine module. DVC was rejected: 42 direct dependencies including a task queue and default telemetry, a single active maintainer, and a lock that a nondeterministic picture would rewrite on every rebuild. Snakemake and doit add nothing over Mise, which the toolchain already owns.

### Reproduction standard

A rebuild is compared layer by layer with the accepted films:

- thought recordings, captions, transcripts and the soundtracks before encoding: byte-identical;
- the picture: identical stage inputs, exact frame counts and timing, and every decoded frame within a PSNR floor of the published film; the floor is calibrated from two renders of the same stage and recorded with the comparison;
- the containers: the same streams, durations, chapters and metadata.

A recording that does not regenerate byte-identically is not replaced silently: it becomes a tracked source asset with its provenance. The review records bind the published films; a rebuild inherits their acceptance only through this standard.

### Mature tools, without changing bytes

- pydantic validates `film.toml`.
- pysubs2 writes SRT and WebVTT if its output is byte-identical to the accepted captions; otherwise the current writer stays.
- REUSE declares licenses per path (`REUSE.toml`, `LICENSES/`) and `reuse lint` checks them.
- `rsync --checksum` and `shasum -a 256 -c` replace the Documents delivery module for local delivery.
- The hand-written BS.1770-4 K-weighting stays: a library computes slightly different gains and would change the soundtracks. It moves to a later engine version together with a new edition and its review.

### Publication record

The `v1.0.0` release publishes both UHD films, both captioned 1080p films, captions, transcripts, covers, the two review records and `SHA256SUMS`. A tracked release manifest records each asset's name, size and SHA-256, so a rebuild knows what it must reproduce. The Release itself, the tag and the remotes wait for the user's confirmation.

### CI

ETHOS projects the portable gates into GitHub Actions and GitLab CI. The film-media gate needs Apple silicon, the models and the films, so it runs only in the local full proof, which is the acceptance.

## Risks / Trade-offs

- [Some recordings do not regenerate byte-identically] → They become tracked source assets with their provenance; no changed take enters silently.
- [A tolerance could hide a real picture change] → Stage inputs must hash identically, frame counts must match exactly, and the floor comes from same-stage repeats.
- [Supply hosts are unavailable] → Supply runs once and every later build is offline; the model endpoint can be a mirror.
- [Gate registry differences under alpha.19] → The registry is adapted in the first task group and proved before the archive.
- [The rename to `filmkit` breaks an import path] → The full Python and Node suites run after the move, before any other change.

## Migration Plan

The private repository is frozen at `fa1e974` and archived after this repository reproduces the films. The accepted films are copied from its ignored `build/` into this repository's `build/` only as the comparison reference. Rollback is the private repository itself, which keeps working unchanged.
