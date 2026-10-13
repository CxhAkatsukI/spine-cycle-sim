"""Retain every diagnostic input and arm, then add two declared budgets."""

from ..search_diagnostics.preparation import ARMS as PREVIOUS_ARMS, CASES, prepare

NEW_ARMS = ("cached_hot64_m32", "cached_hot64_m64")
ARMS = PREVIOUS_ARMS + NEW_ARMS
CREDITS = {"cached_hot": 16, "cached_hot64": 16,
           "cached_hot64_m32": 32, "cached_hot64_m64": 64}


def matrix():
    return [(latency, name, count, arm) for latency in (64, 128)
            for name, count, _ in CASES for arm in ARMS]
