## Why

ddwg-film selects the ETHOS v0.2.0-alpha.21 runtime, four releases behind v0.2.0-alpha.25, which the other governed repositories on this workstation now select. The releases since alpha.21 bound every authored code file by the code ceiling and exempt byte-bound carriers that format selection freezes under a proof gate, select the `unspecified-encoding` lint, and make ETHOS read and write text as UTF-8 on every host. alpha.25 is published with its own Mise declaration, whose platform checksums equal the release's `SHA256SUMS`.

## What Changes

- Replace the alpha.21 declaration in `.config/mise/config.toml` with the declaration published with v0.2.0-alpha.25, unchanged, and lock it again with native `mise lock`. The Node, Python and uv locks stay as they are.
- Bind the repository family to the alpha.25 runtime through the locked console's `hook install`, keeping the alpha.21 runtime as the rollback.
- Apply the paradigm repairs that alpha.25 reports for this repository, if any.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

None. The films, their build and their checks are unchanged, so `.openspec.yaml` sets `skip_specs: true`.

## Impact

Only the tooling declaration, its lock, the runtime selection and any reported paradigm repair change. No film source, build input or published asset changes, so the published `v1.1.0` release stays the one a rebuild reproduces. Publishing the landed commits waits for the user's approval. Later ETHOS releases are out of scope.
