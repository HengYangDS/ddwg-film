# Proposal

## Why

`ddwg-film` cannot tag its first release yet. It was formed by `ethos adopt --create` under ETHOS v0.2.0-alpha.19, whose closeout does not create the absent `main`; v0.2.0-alpha.21 creates that branch at the candidate head in the same closeout transaction. The repository also declares a GitLab peer that cannot receive it: the instance refuses any push whose pack exceeds 20 MiB, the first commit carries 33 MB of fonts, the history is already public on GitHub and cannot be rewritten, and the user cannot raise the instance's limit. On 2026-10-30 the user therefore chose to publish this repository on GitHub only.

## What Changes

- Replace the alpha.19 declaration in `.config/mise/config.toml` with the declaration published with v0.2.0-alpha.21, unchanged, and lock it again with native `mise lock`. The Node, Python and uv locks stay as they are.
- Bind the repository to the alpha.21 runtime through the locked console's `hook install`, keeping the earlier runtime as the rollback.
- Remove the GitLab peer from `.ethos/release.toml`, its CI projection and runner declarations, and the generated `.gitlab-ci.yml`, and say in `CHANGELOG.md` that the portable proof is projected into GitHub Actions.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

None. The films, their sources and their checks are unchanged, so `.openspec.yaml` sets `skip_specs: true`.

## Impact

Only the tooling declaration, its lock, the runtime selection and the publication topology change. This Change's closeout creates `main` at its landed head, where `v1.0.0` is then tagged, so the tagged tree declares the runtime that proved it and the one forge it is published to. A later Change can add GitLab again if the instance's push limit is raised. `tasks.md` is the sole progress ledger.
