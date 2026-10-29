# Tasks

## 1. Import and supply

- [x] 1.1 Import the private repository's code, tests, scripts, casts, assets and configuration from `fa1e974` without its history, `evidence/` or custody code, and verify every imported file's SHA-256 equals its blob at `fa1e974`.
- [x] 1.2 Bind the toolchain: the Mise configuration and lock for Node 26.12.1, CPython 3.12.16, uv 0.13.5 and ETHOS `0.2.0-alpha.19`, plus the uv and npm locks; verify `mise install --locked`, `uv sync --frozen` and `npm ci` succeed.
- [x] 1.3 Adapt `AGENTS.md`, the gate registry and the check policies to this repository, naming FFmpeg, ExifTool and rsync 3 as Homebrew host prerequisites; verify `ethos status` passes and the Python and Node suites pass.

## 2. Engine boundary

- [x] 2.1 Move the reusable pipeline into `src/filmkit` and the film's composition into `picture/`, update every import, command and test, and verify both suites pass.
- [x] 2.2 Declare the film in `content/film.toml`, validated by pydantic; move the delivery pages and review prompt into `content/` with a player page per edition; read every film-specific value from the declaration or the scripts; verify the boundary scan finds no film identity in `src/filmkit` and the rebuilt player and entry pages equal the accepted ones.
- [x] 2.3 Remove the custody archive, `restore-inputs` and the tracked evidence consumers; move the source manifest into `content/` with the DDWG repository URL and commit; write shot plans and review records under `build/evidence/` with each review report beside its record; verify by the suite that each edition's plan and record lie under `build/`.

## 3. Pinned supply

- [x] 3.1 Declare `hyperframes`, `puppeteer-core`, `@puppeteer/browsers` and `gsap` in npm with the accepted renderer's dependency tree, remove the vendored GSAP copy and the OpenMontage paths, turn off renderer telemetry, update checks and self-installs, and verify a stage renders with the locked renderer.
- [x] 3.2 Add the supply task for the browser build and the three model revisions in `build/runtime/tool-cache/`, with digest checks, and verify a build after supply runs offline.
- [x] 3.3 Declare the pipeline as Mise tasks and verify each task runs its engine command for one edition.

## 4. Mature tools

- [x] 4.1 Write SRT and WebVTT through pysubs2 if its output is byte-identical to the accepted captions, otherwise keep the current writer; verify with the accepted captions.
- [x] 4.2 Replace the Documents delivery module with `rsync --checksum` and `shasum -a 256 -c` in a Mise task, and verify a delivery reads back.

## 5. Reproduction

- [x] 5.1 Rebuild every thought recording of both editions from its seeds and verify byte identity with the accepted recordings; track any exception as a source asset with its provenance.
- [x] 5.2 Rebuild captions, transcripts and soundtracks, and verify byte identity with the accepted ones.
- [x] 5.3 Record the release manifest from the accepted films with each edition's soundtrack and staged-document digests, and add the comparison of a rebuild with the published release as an engine command, the `film:compare` task and the `film-reproduction` gate, with `film:build` ending in the technical verification; verify by the suite.
- [x] 5.4 Render, package and verify both editions, confirm the tracked tree is unchanged, and compare them with the accepted films: inspect the lowest frames side by side, record each film's floor in the manifest, and confirm every layer passes.

## 6. Publication

- [ ] 6.1 Write the README with the supply, build and comparison steps, and verify each documented command that needs no published release runs as written.
- [x] 6.2 Declare the licenses through the ETHOS license contract: the MIT grant in `LICENSE` and `pyproject.toml`; in `NOTICE` the CC BY 4.0 content paths, the fonts' OFL-1.1 and the third-party notices, including the GSAP license terms and the narrator's provenance; and the CC BY 4.0 legal code in `LICENSES/`. Verify that `ethos lane repair-paradigm --json` reports no gap.
- [x] 6.3 Project the portable gates into GitHub Actions and GitLab CI through ETHOS, and verify the generated workflows validate.
- [x] 6.4 Prepare `v1.0.0`: `VERSION` as the only version source, `CHANGELOG.md` whose `1.0.0` entry is the release notes, `.ethos/release.toml` with the tags and peers, and the release folder with `SHA256SUMS`; verify the folder against the release manifest.

## Workflow follow-up

- Archive the Change, prove the archived head once, land it and close out.
- Add the forge remotes, push, tag `v1.0.0` and upload the release only after the user confirms; then run the README's download command and read back every asset and `SHA256SUMS` on both forges.
