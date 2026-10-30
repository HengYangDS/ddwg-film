## Purpose

Keep the film engine reusable by a second film: every film-specific value comes from that film's declaration and content, never from the engine.

## ADDED Requirements

### Requirement: A film declares its parameters

A film SHALL declare, in one declaration, its file prefix, delivery folder, entry page, source manifest, each edition's sources folder, cover and caption terms, and its review prompt, floors and scored dimensions. Each edition's script SHALL declare the edition's title, author, language, duration, frame rate and chapters. The engine SHALL check the declaration and the scripts before any work and SHALL refuse an invalid or incomplete declaration, naming each failing field.

#### Scenario: An invalid declaration refuses before work

- **WHEN** the declaration omits an edition, names a file that is missing, gives a malformed file prefix or a review floor outside 0 to 100
- **THEN** the engine refuses when it loads, before any synthesis, and names each failing field

#### Scenario: Scripts that disagree refuse before work

- **WHEN** the editions' scripts declare different durations, authors or chapter counts, or a frame rate other than the 60 fps the engine encodes
- **THEN** the engine refuses when it loads and names the value

### Requirement: The engine carries no film's content

The engine SHALL NOT contain any film's title, identity, script, voice, source, player page, review policy or picture composition. It SHALL take them from the declared film.

#### Scenario: The engine names no film

- **WHEN** the engine's sources are scanned for the film's file prefix, delivery folder, source repository, titles, author and chapter titles
- **THEN** none is found
