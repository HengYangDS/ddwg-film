# Tasks

## 1. Repository entry

- [x] 1.1 Name the GitHub peer's new address in `.ethos/release.toml`; verify that `ethos status` reports the publication topology valid and that the address answers `git ls-remote`. ETHOS's publication topology of the lane is ready with no gap, and `https://github.com/HengYangDS/data-department-work-guidelines-film.git` answers `git ls-remote` with six refs.
- [x] 1.2 Retitle the README and point the README, NOTICE and the Changelog's link definitions to the new address; verify that no current entry document names the old address. No current entry document names `HengYangDS/ddwg-film`.
- [x] 1.3 Add `CONTRIBUTING.md`, include it in the Markdown formatter's inputs in `package.json` and point the README's checks section to it; verify that `mise run check` passes and that ETHOS reports no undeclared command in it. `mise run check` passes 9 Node and 15 Python tests and the Markdown check, which now includes the guide, and `ethos status` reports the committed lane ready with no gap.
- [x] 1.4 Record the rename and the guide under Unreleased in the Changelog; verify the Changelog structure that `ethos status` reports. `ethos status` reports no Changelog gap.

## Workflow follow-up

- Archive the Change, prove the archived head once, land it and close out.
- Publication waits for the user's approval.
