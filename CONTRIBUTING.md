# Contributing

This guide is for maintainers who change, rebuild or release the films. Watching the films needs only the [release assets](https://github.com/HengYangDS/data-department-work-guidelines-film/releases); Agents start at the [Agent entry](AGENTS.md).

| Your task                      | Read next                               |
| ------------------------------ | --------------------------------------- |
| Prepare a checkout             | [Prepare the tools](#prepare-the-tools) |
| Change a script, cast or scene | [Change the films](#change-the-films)   |
| Check a change                 | [Verify a change](#verify-a-change)     |
| Rebuild and compare the films  | [Rebuild the films](#rebuild-the-films) |
| Record a change                | [Commit](#commit)                       |
| Cut and publish a release      | [Release](#release)                     |

## What the repository owns

The repository holds the two introduction films' sources: the scripts, casts, narration texts, players, the picture composition and the assets. The engine is the [filmkit](https://github.com/HengYangDS/filmkit) release that `pyproject.toml` and `uv.lock` pin. Never patch the installed engine or copy it here: an engine change goes through filmkit's own Change and release, and then a lock update here.

The scripts, casts and composition are the reviewed films. Each edition is exactly 1500 seconds of native 60 fps 2D picture with the selected narrator, small single-line captions and no music, and natural phrase tails and thought-group pauses are kept; a runtime is never reached by deleting necessary punctuation or forcing a uniform pace.

## Prepare the tools

The films build on an Apple-silicon Mac. [Mise](https://mise.jdx.dev) installs the locked Node, CPython, uv and ETHOS that the [project configuration](.config/mise/config.toml) and its [lock](.config/mise/mise.lock) declare, and Homebrew supplies Mise itself, FFmpeg with VideoToolbox, ExifTool and rsync 3:

```bash
brew install mise ffmpeg exiftool rsync
mise install --locked
mise run bootstrap
```

`bootstrap` prepares the frozen Python environment and the locked npm packages. Run ETHOS through `mise exec --locked --` or with Mise activated in your shell, so that the declared release answers rather than another installation.

## Change the films

Every change is an OpenSpec Change, worked in its own ETHOS Work Lane:

1. Run `ethos status --json` in the canonical checkout and follow the next action it reports.
2. Start a Work Lane with `ethos lane start`, then create the Change in it with OpenSpec. Its `proposal.md` says why and what changes, `design.md` how, and `tasks.md` lists the work in order; `tasks.md` is the only progress record.
3. Before you edit a tracked file, obtain `ethos lane prewrite` admission for its exact path.
4. Adopt the complete bilingual text of a script change before any narration, qualify the new recordings before the picture follows them, and rebuild, review and accept the films before release. A change to a script, cast or the composition reopens the independent review; a rebuild inherits the published films' review only by meeting the reproduction standard in [`openspec/specs/film-reproduction`](openspec/specs/film-reproduction).
5. When the tasks are done, archive the Change, prove the archived head once, then land it and close out as `ethos status` directs.

Generated output belongs under the ignored `build/`; the tracked tree holds sources only, and the films are published as release assets.

## Verify a change

```bash
mise run check
```

The check confirms that the locks are current, runs the picture and Python suites and checks the Markdown format without writing; `mise run fix` applies the Markdown formatter. A committed head must then pass the full proof, which runs every gate the repository declares in [`system/gates.toml`](system/gates.toml), the film's own checks included:

```bash
ethos prove --host --execute --full --json
```

GitHub Actions runs the same portable proof.

## Rebuild the films

`film:supply` is the only step that reaches the network; `film:build` then narrates, assembles, renders, packages and verifies both editions offline, writing only below `build/`:

```bash
mise run film:supply
mise run film:build
```

With the published release assets in `build/artifacts/release/`, as the README describes, compare the rebuild under the reproduction standard, then verify the films and their reproduction with the host gates:

```bash
mise run film:compare
ethos prove --host --gate film-media --gate film-reproduction --execute
```

A reviewed edition is delivered to its Documents folder with `mise run film:deliver`, which reads every delivered file back.

## Commit

Sign every commit with your own SSH key; ETHOS's hooks check each commit's signature, subject and admission. Set `ETHOS_ACTOR` to the Lease holder and `ETHOS_CHANGE` to the Change's name when you commit. The subject is a Conventional Commit whose type is `build`, `chore`, `ci`, `docs`, `feat`, `fix`, `perf`, `refactor`, `revert` or `test`, with an optional kebab-case scope and `!` for a breaking change, as in `fix(picture): keep the scene inside the safe area`.

## Release

`VERSION` holds the version, and `CHANGELOG.md` follows Keep a Changelog: record each change under `Unreleased` as it lands, and date its heading only when the release is cut. [`content/release.json`](content/release.json) records every published asset and the sources each film was made from. A release is a signed `v*` tag that `ethos land --release` cuts from the accepted head, and `ethos publish` sends the branches and the tag to the peer that [`.ethos/release.toml`](.ethos/release.toml) declares. A release that changes the films publishes them as release assets with their captions, transcripts, covers, review records and `SHA256SUMS`; one that changes only how they are built publishes none and names the release whose films it rebuilds.

## License

Code contributions are licensed under the [MIT License](LICENSE), and contributions to the films' content under [Creative Commons Attribution 4.0 International](LICENSES/CC-BY-4.0.txt). [NOTICE](NOTICE) names the content's paths, the fonts and the software and models a build installs.
