# Tasks

## 1. Engine dependency

- [x] 1.1 Make the repository the film's project: depend on `filmkit` 0.1.0 through a uv Git source at `v0.1.0`, remove `src/filmkit`, and update the lock from the current one; verify that `uv sync --frozen` installs `filmkit` 0.1.0 from the tag's commit and that the lock's other package versions equal `v1.0.0`'s.
- [x] 1.2 Declare the fonts and the readings in `content/film.toml` and write `content/review/readings.json` from the engine copy's four tables; verify that the release loads the declaration and that its listening plan equals the one the engine copy derives.
- [x] 1.3 Run the Node tools through `python -m filmkit.tools` in the Mise tasks; verify that no task or check names `src/filmkit`.

## 2. Tests

- [x] 2.1 Keep the film's own tests on the installed engine and remove the engine's tests that `filmkit` carries; verify that `mise run check` passes and that the behavior gate's coverage of `picture/film.js` meets 90%.

## 3. Reproduction

- [ ] 3.1 Supply and rebuild both editions from the lane with `mise run film:supply` and `mise run film:build`, and compare them with `v1.0.0` with `mise run film:compare`; verify that every layer passes and that the tracked tree is unchanged.

## 4. Documentation

- [x] 4.1 Update the README's layout, engine and check sections, `AGENTS.md` and `CHANGELOG.md`; verify that `ethos lane repair-paradigm --json` reports no gap and that the format check passes.

## Workflow follow-up

- Archive the Change, prove the archived head once, run the film gates on it as a host observation, land it and close out.
- Publish `dev` and `main` to GitHub after the user confirms.
