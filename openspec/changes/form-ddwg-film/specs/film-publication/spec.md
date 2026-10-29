## Purpose

Publish the films and their sources under clear licenses, with release assets whose identities the repository records.

## ADDED Requirements

### Requirement: Licenses are declared for every tracked file

Code SHALL be licensed MIT, the films' text, audio and images CC BY 4.0, and bundled fonts under their own licenses. Every tracked file SHALL carry a machine-readable license declaration, and third-party material SHALL keep its original notice.

#### Scenario: The license check covers the tree

- **WHEN** the license check runs on the repository
- **THEN** every tracked file resolves to a declared license and copyright
- **AND** each license text the declarations use is present

### Requirement: A release carries the films with their checksums

A release SHALL publish both editions' UHD films, captioned 1080p films, captions, transcripts, covers and review records, together with their SHA-256 sums. The repository SHALL record each published asset's name, size and SHA-256.

#### Scenario: Published assets read back

- **WHEN** a release has been published on a forge
- **THEN** each downloaded asset's SHA-256 equals the recorded one

### Requirement: The repository tracks no generated media or evidence

The tracked tree SHALL NOT contain films, recordings, renders, review outputs or build receipts. They SHALL be produced under `build/` or published as release assets.

#### Scenario: The tracked tree holds sources only

- **WHEN** the tracked files are listed
- **THEN** none is a generated film, recording, render, review output or build receipt
