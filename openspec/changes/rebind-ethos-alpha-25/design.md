## Context

ETHOS publishes each release with a Mise declaration that pins the runtime archive of every platform by URL and SHA-256. The repository selects its runtime through that declaration in `.config/mise/config.toml`, its lock in `.config/mise/mise.lock`, and the hooks that `ethos hook install` binds to the installed runtime. The proposal states why alpha.25 is selected.

## Decisions

- **Take the published declaration unchanged.** The alpha.21 block is replaced by the alpha.25 file as published, so its platform checksums stay the release owner's. Its checksums are compared with the release's `SHA256SUMS` before use. `mise lock` then records the new archives; the Node, Python and uv entries are not relocked.
- **Keep alpha.21 as the rollback.** `hook install --authorize` from the locked alpha.25 console makes alpha.25 the current runtime and keeps alpha.21 installed, so a regression can return to it through the same command.
- **Let the runtime name the repairs.** Repairs are applied only when `ethos lane repair-paradigm` reports a gap under alpha.25, through its own apply step where it offers one. `picture/film.js` stays one script: the format policy keeps it as an immutable carrier, the release manifest records its bytes and the proof checks them, which is the byte-bound carrier that alpha.24 exempts from the code ceiling.

## Risks

- A gate that alpha.21 accepted may fail under alpha.25. The full proof of the lane head shows it before the archive, and the fix belongs to this Change only if it is a paradigm repair; anything else stops the Change and is reported.
- The hosted CI declarations are projections of the gates. If alpha.25 projects them differently, `ethos lane project --check` names the difference and the projection is regenerated with the native command.
