## Context

The release paradigm accepts release notes only inside Keep a Changelog categories. The `1.1.0` entry opened with a sentence that said the films are those of `1.0.0`, outside any category.

## Goals / Non-Goals

**Goals:**

- The `1.1.0` entry holds only categorized items, so the full proof of the release head reports no changelog gap.

**Non-Goals:**

- Any change to the build, the films, the specifications or the other entries.

## Decisions

- Remove the sentence rather than add a category for it. The entry's Changed items already state that a rebuild reproduces the `1.0.0` editions, and the README says that a build-only release publishes no films, so nothing is lost.

## Risks / Trade-offs

- None: the change touches release notes only.

## Migration Plan

Commit the correction with this Change, archive it, prove the archived head once and land both Changes together.
