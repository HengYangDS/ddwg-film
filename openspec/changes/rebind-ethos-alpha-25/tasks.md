## 1. Runtime

- [x] 1.1 Replace the alpha.21 declaration in `.config/mise/config.toml` with the one published with v0.2.0-alpha.25, checked against the release's `SHA256SUMS`, and lock it again with native `mise lock`; done when the lock holds alpha.25 for every platform it covers and no alpha.21 entry, and its Node, Python and uv entries are unchanged.
- [x] 1.2 Bind the repository family to the alpha.25 runtime with the locked console's `hook install --authorize`, keeping alpha.21 as the rollback; done when `ethos status` reports the lane ready under the alpha.25 runtime.

## 2. Verification

- [x] 2.1 Apply the paradigm repairs that `ethos lane repair-paradigm` reports under alpha.25, if any; done when it reports no gap and `ethos lane project --check` passes.
- [x] 2.2 Run the full proof of the lane head under alpha.25; done when every gate passes.
