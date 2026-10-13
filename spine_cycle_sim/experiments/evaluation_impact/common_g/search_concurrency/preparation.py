"""Keep the full cached-G declaration and add two controls, without row selection."""

from ..cached_hot.preparation import ARMS as PREVIOUS_ARMS, CASES, prepare

ARMS = PREVIOUS_ARMS + ("original_forwarded", "cached_hot64")


def matrix():
    return [(latency, name, count, arm) for latency in (64, 128)
            for name, count, _ in CASES for arm in ARMS]
