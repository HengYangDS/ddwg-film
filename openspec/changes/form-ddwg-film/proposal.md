# Proposal

## Why

The DDWG introduction films, one in Chinese and one in English, each 1500 seconds, were accepted on 2026-10-28, but their repository cannot be published. Its history carries an organization address and a 7.7 GB custody archive, and its reproduction path restores retained outputs instead of rebuilding them. The user decided to publish the code under MIT and the film content under CC BY 4.0 in a clean repository that rebuilds both films from its own sources, and to reuse its engine for a later ETHOS film.

## What Changes

- Import the film's sources from the private repository at commit `fa1e974` as a snapshot: code, tests, scripts, casts, assets and configuration, without its history, evidence, custody archive or generated files.
- Separate a reusable engine package, `filmkit`, from the DDWG film's composition, content, assets and declared parameters.
- Pin every external input the build consumes: the renderer, browser automation, browser build and animation library through npm, models by Hugging Face revision, and FFmpeg as a declared native tool. Renderer telemetry is off.
- Write generated output only under `build/`, record the DDWG source as a repository URL and commit, and remove the custody archive with its restore path. **BREAKING** relative to the private repository: `restore-inputs` and the tracked `evidence/` tree do not exist here.
- Replace hand-written plumbing with mature tools wherever the films' bytes stay identical: Mise tasks for the pipeline, validated configuration, and standard subtitle, licensing and delivery tools.
- Define the reproduction standard and verify a rebuild against the accepted films.
- Add the README, licensing (MIT, CC BY 4.0, OFL fonts, third-party notices), the CI projection and the `v1.0.0` release preparation, without publishing.

## Capabilities

### New Capabilities

- `film-production`: the films' content, media, narration, sound and picture contract, carried over from the private repository.
- `film-reproduction`: rebuilding both films from tracked sources and pinned supply, and the standard a rebuild must meet.
- `film-engine`: the boundary between the reusable engine and one film's declared content and parameters.
- `film-publication`: licensing, release assets and the record of what was published.

### Modified Capabilities

None.

## Impact

- New repository `ddwg-film`, governed by ETHOS `0.2.0-alpha.19`. Its forge remotes (GitHub `HengYangDS/ddwg-film`, GitLab `dig/misc/guidelines/ddwg-film`) are added only when the user confirms the push.
- Dependencies: adds npm `hyperframes`, `puppeteer-core` and `@puppeteer/browsers`, and Python `pydantic`; removes the vendored GSAP copy and the OpenMontage runtime path.
- The private repository `ddwg-introduction-film` is never read by a build; it remains a private archive.
- Out of scope: pushing, tagging or uploading a release before the user confirms; extracting the engine into its own repository; the ETHOS film remake; any change to either film's script, narration or picture.
