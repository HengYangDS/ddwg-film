"""This film's release manifest and the film-bound sources it records."""

import tomllib

import filmkit.delivery.reproduction as reproduction
import filmkit.repository as repository

# The format policy whose immutable carriers no formatter rewrites.
FORMAT_POLICY = ".config/checks/format-selection/policy.toml"


def test_the_film_bound_sources_hold_the_bytes_the_release_records():
    assert reproduction.changed_sources(reproduction.load()) == []


def test_the_release_records_each_source_the_format_policy_keeps_from_formatters():
    policy = tomllib.loads((repository.ROOT / FORMAT_POLICY).read_text())
    carriers = {
        path
        for increment in policy["ownership"]
        if increment["format_owner"] == "immutable-carrier"
        for path in increment["paths"]
    }
    assert carriers == set(reproduction.load().sources)
