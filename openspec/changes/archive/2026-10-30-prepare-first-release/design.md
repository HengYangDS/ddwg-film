# Design

## Context

The repository declares the ETHOS runtime once, as the release's Mise declaration in `.config/mise/config.toml`, and `mise.lock` pins it for every platform. The first release needs a closeout that creates `main`, which alpha.21 provides. `.ethos/release.toml` declares two peers, GitHub and GitLab, and the CI projection writes a workflow for each. The GitLab instance refuses this repository's first push for its size.

## Goals / Non-Goals

**Goals:**

- Bind alpha.21 through its published declaration and native locks, so the tagged tree, hosted CI and contributors install the runtime that proved the release.
- Declare only the forge the repository is published to, so publication, proof projection and release checks name no peer that can never receive it.

**Non-Goals:**

- Moving Node, Python or uv, or any film source, recording or check.
- Moving to later ETHOS releases.
- Deleting the empty GitLab project, which stays the user's.

## Decisions

- **Use the release's declaration unchanged.** Copying the published block keeps its URLs and checksums owned by the release; editing version strings by hand was rejected because it would detach the checksums from the release's `SHA256SUMS`.
- **Lock with native Mise.** `MISE_LOCKED=0 mise lock` runs once, because `locked = true` refuses a version absent from the lock; it prunes the alpha.19 entry.
- **Keep the earlier runtime as the rollback.** `hook install` switches the selection and keeps the previous one, so a regression returns to it without a source change.
- **Publish on GitHub only.** Pushing the fonts in pieces through temporary refs, or letting GitLab import the repository from GitHub, would put remote effects outside `ethos publish` and let one peer source another, which ETHOS's publication model forbids. A declared peer that never receives the objects would stay divergent. The GitLab peer, its projection, its runner declarations and `.gitlab-ci.yml` are removed through `ethos lane project`.

## Risks / Trade-offs

- [`mise lock` stalls on GitHub] → One call with `MISE_HTTP_TIMEOUT=180` and `MISE_JOBS=2`.
- [The new runtime rejects a gate the old one passed] → The archived head's full proof runs under alpha.21 before landing; a failure compensates the archive and keeps the rollback selected.
- [Collaborators expected the organization's GitLab copy] → The README already points to GitHub; a later Change can add the peer again once the push limit allows it.
