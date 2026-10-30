# Changelog

All notable changes to the DDWG introduction films and their build are recorded here. The format follows [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/), and releases follow [Semantic Versioning 2.0.0](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.1.0] - 2026-10-31

### Changed

- The films are built by the published `filmkit` 0.1.0 release, which `pyproject.toml` pins by its tag `v0.1.0` and `uv.lock` by its commit, instead of the engine copy in `src/filmkit`. Every other locked package keeps its version. The declaration names the fonts the picture stages and the listening plan's readings, which `content/review/readings.json` holds, and the Mise tasks run the Node tools through `python -m filmkit.tools`.
- A rebuild with filmkit 0.1.0 on an Apple M5 Max reproduces the published `1.0.0` editions: every soundtrack, staged picture document, caption, transcript and cover is byte-identical, and each film has the published frame count, decoded audio and container, with every frame at or above the 45 dB PSNR floor; the lowest frame measured 51.6 dB.

### Removed

- `src/filmkit` and the engine's tests, which filmkit carries with its sample film. The film keeps the tests of its own composition, narration receipts, release manifest, declaration and players.

## [1.0.0] - 2026-10-30

### Added

- The Chinese and English introduction films to the Data Department Work Guidelines at commit `2c59ac0`, each exactly 1500 seconds at 60 fps, as accepted on 2026-10-28. The independent review scored each edition 95.9, with every dimension at 95 or above. Each edition is published as a UHD master and a captioned 1080p film, with SRT and WebVTT captions, a transcript, a cover and its review record, and `SHA256SUMS` lists every asset. Each Chinese film carries two one-frame encoding glitches, at 8:55.35 and 10:42.65, that are invisible at normal speed and that a rebuild does not reproduce.
- The `filmkit` engine and the Mise tasks that rebuild both editions from the tracked sources: `film:supply` installs the pinned browser build and speech models, `film:build` narrates, assembles, renders, packages and verifies both editions offline, and `film:compare` compares a rebuild with the published release.
- A rebuild on an Apple M5 Max reproduces the published editions: every soundtrack, caption, transcript, cover and staged picture document is byte-identical, and each film has the published frame count, decoded audio, streams, chapters and tags, with every frame at or above the 45 dB PSNR floor; the lowest frame measured 51.5 dB.
- ETHOS governance, with its portable proof projected into GitHub Actions.
- The MIT License for the code and CC BY 4.0 for the films' content, with the third-party notices and the narrator's provenance in `NOTICE`.

[Unreleased]: https://github.com/HengYangDS/ddwg-film/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/HengYangDS/ddwg-film/releases/tag/v1.1.0
[1.0.0]: https://github.com/HengYangDS/ddwg-film/releases/tag/v1.0.0
