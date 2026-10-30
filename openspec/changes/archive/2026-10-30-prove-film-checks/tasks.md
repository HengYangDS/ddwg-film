# Tasks

## 1. Behavior scope

- [x] 1.1 Mark `tests/**/*.py` and `tests/engine.mjs` as tooling with the `ethos-role` attribute before the final `.gitattributes` pattern, and add the `test:coverage` recipe that limits coverage to `picture/film.js`; verify that a replica of the gate's coverage report holds exactly `picture/film.js` and that `git check-attr ethos-role` reports the roles.
- [x] 1.2 Add the `film-checks` gate to the proof sets; verify that it passes on the lane and leaves the tree unchanged.

## 2. Documentation

- [x] 2.1 Record the gate in the README's Checks section and the `1.1.0` changelog entry; verify the Markdown format check.
