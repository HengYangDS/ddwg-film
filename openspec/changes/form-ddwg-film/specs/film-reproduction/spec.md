## Purpose

Let anyone with an Apple-silicon Mac rebuild both films from this repository's tracked sources and pinned supply, and know exactly how a rebuild compares with the published films.

## ADDED Requirements

### Requirement: Films rebuild from tracked sources

The repository SHALL rebuild both editions from its tracked sources and its declared supply on Apple-silicon macOS. A build SHALL NOT read another repository, a retained output or an archive, and SHALL refuse before synthesis when a declared supply input is missing.

#### Scenario: A clean checkout rebuilds both films

- **WHEN** a clean checkout runs the declared supply step and then the declared build
- **THEN** both editions' recordings, captions, soundtracks, pictures and packaged films are produced under `build/`
- **AND** no path outside the checkout and its declared tool cache is read

#### Scenario: Missing supply refuses early

- **WHEN** a model revision, the browser build or a locked package is absent
- **THEN** the build refuses before any synthesis or render and names the missing input

### Requirement: Every external input is pinned

The build SHALL consume only the language runtimes, packages, browser build, models and renderer versions the repository declares, each checked against its declared digest or revision. It SHALL reach the network only in the supply step, and renders SHALL run with renderer telemetry disabled.

#### Scenario: A build after supply runs offline

- **WHEN** the supply step has completed and the network is unavailable
- **THEN** the full build completes
- **AND** each consumed tool and model reports the version or revision the repository declares

### Requirement: Generated output stays under build

A build SHALL write generated files only under the ignored `build/` directory. It SHALL NOT modify any tracked file.

#### Scenario: A full build leaves the tracked tree unchanged

- **WHEN** the full build finishes
- **THEN** the repository's tracked files are byte-identical to the commit that was built
- **AND** every generated file lies under `build/`

### Requirement: A rebuild meets the reproduction standard

A rebuild SHALL be compared layer by layer with the published release. Each edition's soundtrack before encoding and staged picture document SHALL hold the bytes the release manifest records, its captions, transcript and cover SHALL be byte-identical to the published ones, and each film SHALL have the published film's frame count, decoded audio, streams, durations, chapters and tags.

#### Scenario: A faithful rebuild passes

- **WHEN** the comparison runs on a rebuild and the published release
- **THEN** it reports every layer with its measured result and passes

#### Scenario: A changed layer refuses

- **WHEN** a soundtrack, staged document, caption, transcript or cover differs by one byte, or a film's frame count, decoded audio, streams, durations, chapters or tags differ
- **THEN** the comparison fails and names the edition, layer and asset
- **AND** the rebuild does not inherit the published films' review

### Requirement: Pictures stay within a calibrated floor

Every decoded frame's PSNR between a rebuilt film and its published film SHALL be measured. After the first comparison's lowest frames are inspected side by side, the release manifest SHALL record each film's floor at or below that comparison's minimum, and later rebuilds SHALL keep every decoded frame at or above it.

#### Scenario: The first comparison calibrates the floor

- **WHEN** the release manifest records no floor for a film
- **THEN** the comparison reports the film's minimum and lowest frames and does not pass

#### Scenario: A frame below the floor refuses

- **WHEN** a decoded frame of a rebuilt film falls below its recorded floor
- **THEN** the comparison fails and names the film and the frame

### Requirement: Only the reviewed published films carry acceptance

The comparison SHALL refuse a published asset whose bytes differ from the release manifest. It SHALL accept a published review only when the review binds its edition's published films and the current script and composition and meets the declared floors, and a rebuild SHALL inherit that review only through the comparison.

#### Scenario: A published asset that differs refuses

- **WHEN** a published asset's size or SHA-256 differs from the release manifest
- **THEN** the comparison refuses before comparing any layer and names the asset

#### Scenario: A review that does not bind refuses

- **WHEN** a published review covers other film bytes or another script or composition, or scores below a declared floor
- **THEN** the comparison fails and names the edition

### Requirement: Film-bound sources stay as published

The release manifest SHALL record the SHA-256 of each film-bound source, a tracked file whose exact bytes the build reads and that no formatter rewrites. The portable proof SHALL check every film-bound source against the manifest, and the comparison SHALL refuse before comparing any layer when one differs.

#### Scenario: A changed film-bound source refuses

- **WHEN** a film-bound source differs by one byte from the release manifest
- **THEN** the portable proof fails and names the source
- **AND** the comparison refuses before comparing any layer and names the source

#### Scenario: Every source kept from formatters is recorded

- **WHEN** the format policy keeps a tracked file from every formatter
- **THEN** the release manifest records that file's SHA-256
