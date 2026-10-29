## Purpose

Keep the film engine reusable by a second film: every film-specific value comes from that film's declaration and content, never from the engine.

## ADDED Requirements

### Requirement: A film declares its parameters

A film SHALL declare its languages, runtime, frame rate, renditions, narrator references, models, source and release metadata in one declaration. The engine SHALL validate the declaration before any work and SHALL refuse an invalid or incomplete one, naming each failing field.

#### Scenario: An invalid declaration refuses before work

- **WHEN** the declaration omits a language's script or gives a frame rate the renderer does not accept
- **THEN** the build refuses before synthesis and names each failing field

### Requirement: The engine carries no film's content

The engine SHALL NOT contain any film's title, identity, script, voice, source or picture composition. It SHALL take them from the declared film.

#### Scenario: The engine names no film

- **WHEN** the engine's sources are scanned for the identities the film declares
- **THEN** none is found

#### Scenario: A second film builds through the same engine

- **WHEN** the sample film of a few seconds is built through the engine
- **THEN** its recordings, captions, soundtrack, picture and packaged film are produced without any change to the engine
