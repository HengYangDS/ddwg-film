## Context

The behavior gate requires, for every observed code language, native tests over production code of that language. Before `adopt-filmkit`, `src/filmkit` gave Python its production code and in-repository JavaScript beside `picture/film.js`. Now the engine is installed from its release: the Python files are checks of the film's sources through the engine, and the only production JavaScript is the composition.

## Goals / Non-Goals

**Goals:**

- The full proof measures the composition tests' coverage of `picture/film.js` and runs the Python checks, in the portable proof and in hosted CI.

**Non-Goals:**

- Any change to the checks themselves, the films, the engine release or the specifications.

## Decisions

- Declare roles with the native `ethos-role` Git attribute, as the ETHOS repository does for its own tooling, placed before the final `* text=auto eol=lf` pattern. The Python checks and the engine helper are tooling for this repository: they verify its sources and find the engine, and no production code of their language lives here.
- Run the Python checks as a command gate in the proof sets, `uv run --python 3.12 --frozen --offline --group dev python -B -m pytest -p no:cacheprovider -q tests`, so they write no bytecode or cache into the tree. Removing them from the proof was rejected: hosted CI would then never run them.
- Limit coverage with `c8 --include=picture/film.js npm test`, the recipe form the gate accepts, so the report holds exactly the selected production file. Excluding the virtual environment instead would replace c8's default exclusions of the test files.

## Risks / Trade-offs

- [A new production JavaScript file would be left out of coverage] → The gate selects production files itself and refuses a report that lacks one, so the recipe must then name it too.

## Migration Plan

Commit the Change with its implementation, archive it, prove the archived head once, run the film gates as a host observation and land the three Changes together.
