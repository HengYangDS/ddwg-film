# Proposal

## Why

On 2026-11-01 the owner renamed the repository `data-department-work-guidelines-film` on GitHub and GitLab, so that it corresponds to the repository it explains, `data-department-work-guidelines`, and gave it the title "Data Department Work Guidelines: Film". The release declaration, the README, NOTICE and the Changelog's links still use the old name, which GitHub only redirects. The repository also has no contributing guide, although it is public and the owner expects one in every governed repository.

## What Changes

- `.ethos/release.toml` names the GitHub peer at `https://github.com/HengYangDS/data-department-work-guidelines-film`.
- The README takes the title "Data Department Work Guidelines: Film", and the README, NOTICE and the Changelog's link definitions use the new address. NOTICE keeps the wording of its attribution and links it to the new address.
- `CONTRIBUTING.md` explains how to prepare the tools, change the film in an ETHOS Work Lane, verify a change, rebuild and compare the films, commit, and cut and publish a release. The README's checks section points to it.
- The Changelog records the rename and the guide under Unreleased.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

None. No film, script, composition or check changes, so `.openspec.yaml` sets `skip_specs: true`.

## Impact

- `.ethos/release.toml`, `README.md`, `NOTICE`, `CONTRIBUTING.md`, `CHANGELOG.md`, and `package.json`, whose Markdown formatter commands gain the guide.
- Out of scope: the Python and npm package names and the local checkout's directory, which keep `ddwg-film`; the released films and their metadata, which carry no repository address; and the text of released Changelog entries.
- The local `github` remote already points at the new address. The change lands on the local `dev`; publication waits for the user's approval.
