# Design

## Context

See [proposal.md](proposal.md). ETHOS reads the publication peers from `.ethos/release.toml`; a peer's `forge_repository` is the address its Forge API is reached at. GitHub keeps redirecting the old repository name for the web, the API, Git and release downloads until another repository takes that name. In an entry document, every command in a shell block must be one the repository declares.

## Goals / Non-Goals

**Goals:**

- The release declaration and the current entry documents name the repository by its new name and title.
- A maintainer can prepare the tools, change and verify the film, rebuild and compare it, commit and release from `CONTRIBUTING.md`, without reading Agent guidance.

**Non-Goals:**

- Renaming the Python and npm packages, the film's file prefix, its Documents folder or the local checkout.
- Changing any film, script, composition, check or release asset.
- Repeating the README's account of the build, the comparison and the layout.

## Decisions

**Only the public identity moves.** The forges, the release declaration and the entry documents carry the name a reader sees. The package names are internal: renaming them would rewrite both lock files and the installed environments for no reader's benefit, so they stay `ddwg-film`, as the local checkout does.

**The title keeps the owner's colon in Markdown.** GitLab refuses a colon in a project name and shows an en dash there; the README's heading has no such limit and uses the title as the owner wrote it.

**Link definitions follow the new name; released text does not.** The Changelog's link definitions are navigation, so they point to the new address; the text of released entries stays as released.

**The guide states the film's own contract and points to ETHOS and filmkit for the rest.** It names the film contract from `AGENTS.md`, the declared Mise tasks, the declared verification command, the host gates, the commit grammar and signature ETHOS enforces, and the release order this repository has used. It does not restate ETHOS's command reference or the engine's.

## Risks / Trade-offs

- [The old name is taken by a new repository and the redirect ends] → The account owner controls that name; the tracked addresses no longer depend on the redirect.
- [The guide drifts from the repository] → It names only declared tasks and commands, which the repository's checks read.
