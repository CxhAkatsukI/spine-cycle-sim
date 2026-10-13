"""Retain all nineteen inputs and both latencies for three cached controls."""

from ..search_concurrency.preparation import CASES, prepare

ARMS = ("original_forwarded", "cached_hot", "cached_hot64")


def matrix():
    return [(latency, name, count, arm) for latency in (64, 128)
            for name, count, _ in CASES for arm in ARMS]
