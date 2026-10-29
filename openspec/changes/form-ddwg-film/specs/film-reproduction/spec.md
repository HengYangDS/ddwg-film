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

A rebuild SHALL be compared layer by layer with the published films. Thought recordings, captions, transcripts and the soundtracks before encoding SHALL be byte-identical. Pictures SHALL have identical stage inputs, exact frame counts and every decoded frame within the recorded PSNR floor. Containers SHALL carry the same streams, durations, chapters and metadata.

#### Scenario: A faithful rebuild passes

- **WHEN** the comparison runs on a rebuild and the published films
- **THEN** it reports every layer with its measured result and passes

#### Scenario: A changed layer refuses

- **WHEN** any recording, caption or soundtrack differs by one byte, a frame count differs, or a decoded frame falls below the floor
- **THEN** the comparison fails and names the edition, layer and position
- **AND** the rebuild does not inherit the published films' review
