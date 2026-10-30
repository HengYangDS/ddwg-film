# Tasks

## 1. Runtime

- [ ] 1.1 Replace the alpha.19 declaration in `.config/mise/config.toml` with the one published with v0.2.0-alpha.21, checked against the release's `SHA256SUMS`, and lock it again with native `mise lock`; done when the lock holds alpha.21 for every platform it covers and no alpha.19 entry, and its Node, Python and uv entries are unchanged.
- [ ] 1.2 Bind the repository to the alpha.21 runtime with the locked console's `hook install --authorize`, keeping the earlier runtime as the rollback; done when `ethos status` reports the lane ready under the alpha.21 runtime.

## 2. Publication topology

- [ ] 2.1 Remove the GitLab peer from `.ethos/release.toml`, the GitLab projection and runner declarations from the CI configuration, and the generated `.gitlab-ci.yml`, and project the gates again with `ethos lane project`; done when `ethos lane project --check` and `ethos lane repair-paradigm --json` report no gap and `CHANGELOG.md` names GitHub Actions only.

## Workflow follow-up

- Archive the Change, prove the archived head once, land it and close out, so that `main` is created at the landed head.
- Tag `v1.0.0` at that head, publish `dev`, `main` and the tag to GitHub, and attach the published films, captions, transcripts, covers, review records and `SHA256SUMS` to the release.
