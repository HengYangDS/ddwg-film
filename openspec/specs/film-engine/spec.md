# film-engine Specification

## Purpose

Keep the film engine reusable by a second film: every film-specific value comes from that film's declaration and content, never from the engine.

## Requirements

### Requirement: A film declares its parameters

A film SHALL declare, in one declaration, its file prefix, delivery folder, entry page, source manifest, each edition's sources, cover and caption terms, its picture fonts, its review prompt, floors and dimensions, and its listening-plan readings. Each edition's script SHALL declare its title, author, language, duration, frame rate and chapters. The engine SHALL refuse an invalid or incomplete declaration or script before any work, naming each failing field.

#### Scenario: An invalid declaration refuses before work

- **WHEN** the declaration omits an edition, names a file that is missing, gives a malformed file prefix or a review floor outside 0 to 100
- **THEN** the engine refuses when it loads, before any synthesis, and names each failing field

#### Scenario: Scripts that disagree refuse before work

- **WHEN** the editions' scripts declare different durations, authors or chapter counts, or a frame rate other than the 60 fps the engine encodes
- **THEN** the engine refuses when it loads and names the value

#### Scenario: The film's readings derive its listening plan

- **WHEN** the listening plan is derived from the current scripts
- **THEN** it takes the film's Mandarin readings, heteronyms, variants and grammar from the declared readings file
- **AND** it equals the plan that the engine copy of `v1.0.0` derives from the same scripts

### Requirement: The engine is a pinned release

The film SHALL take its engine from one filmkit release, pinned by its tag and commit in the lock, and SHALL NOT track a copy of the engine's sources. The lock SHALL keep the versions of the packages that reproduced the published films.

#### Scenario: The lock pins the engine's release

- **WHEN** the dependencies are installed from the lock
- **THEN** the installed filmkit reports the version of the release the lock names, built from that tag's commit
- **AND** no engine source file is tracked in the repository

#### Scenario: A rebuild with the release reproduces the published films

- **WHEN** both editions are rebuilt with the pinned release from a clean checkout and its declared supply
- **THEN** the comparison with the published `v1.0.0` release passes every layer of the reproduction standard
