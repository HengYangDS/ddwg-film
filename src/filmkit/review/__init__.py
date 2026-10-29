"""Measure the editions and run an independent review round.

A review tool that refuses its inputs raises `ReviewError`, which each command reports as
its refusal.
"""


class ReviewError(ValueError):
    """A review input or record differs from what the review tools require."""
