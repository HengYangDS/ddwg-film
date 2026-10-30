## Why

The full proof of the archived release head blocks the behavior gate. The repository no longer carries production Python, so its Python checks of the declaration, players, narration receipts and release manifest have no behavioral subject (`quality_behavior_scope_unrecognized`). The JavaScript gate also refuses its scope: it selects `tests/engine.mjs`, a helper that finds the installed engine's JavaScript, as a test file that `node --test` never runs, and its coverage report includes the engine's `headless-composition.mjs` from the virtual environment beside `picture/film.js`.

## What Changes

- Mark the Python checks and the engine helper as tooling carriers through the native `ethos-role` Git attribute, so the behavior gate measures the composition tests over `picture/film.js` alone.
- Limit the composition tests' coverage to `picture/film.js` with a `test:coverage` recipe that the behavior gate accepts.
- Add a `film-checks` gate to the proof sets that runs the Python checks offline with the locked toolchain, so the portable proof and hosted CI still run them.
- Record the gate in the README and the `1.1.0` changelog entry.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

None.

## Impact

- `.gitattributes`, `package.json`, `system/gates.toml`, `README.md` and `CHANGELOG.md`. No film source, build input or specification changes.
