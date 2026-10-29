## Purpose

Publish the films and their sources under clear licenses, with release assets whose identities the repository records.

## ADDED Requirements

### Requirement: Licenses are declared for every tracked file

Code SHALL be licensed MIT, the films' text, audio and images CC BY 4.0, and bundled fonts under their own licenses. The root LICENSE SHALL carry the MIT grant that the package manifests declare, NOTICE SHALL name the tracked paths under CC BY 4.0, every other tracked file being code, each license text SHALL be present, and third-party material SHALL keep its original notice.

#### Scenario: The license declarations cover the tree

- **WHEN** ETHOS checks the repository paradigm
- **THEN** the MIT grant in LICENSE is recognized, linked from the README and declared by the package manifests
- **AND** NOTICE names the license of every tracked path that is not code, and each license text it names is present

### Requirement: A release carries the films with their checksums

A release SHALL publish both editions' UHD films, captioned 1080p films, captions, transcripts, covers and review records, together with their SHA-256 sums. The repository SHALL record each published asset's name, size and SHA-256, and the digests of the soundtrack and staged picture document each edition was made from.

#### Scenario: Published assets read back

- **WHEN** a release has been published on a forge
- **THEN** each downloaded asset's SHA-256 equals the recorded one

### Requirement: The repository tracks no generated media or evidence

The tracked tree SHALL NOT contain films, recordings, renders, review outputs or build receipts. They SHALL be produced under `build/` or published as release assets.

#### Scenario: The tracked tree holds sources only

- **WHEN** the tracked files are listed
- **THEN** none is a generated film, recording, render, review output or build receipt
