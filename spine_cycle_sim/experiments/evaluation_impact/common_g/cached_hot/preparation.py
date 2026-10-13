"""Reuse the complete previous workload declaration without selecting rows."""

from ..hot_lanes.preparation import ARMS as PREVIOUS_ARMS, CASES, prepare

ARMS = PREVIOUS_ARMS + ("cached_hot",)
HOT_TRANSFER_BYTES = 2 * 131072 * 64


def matrix():
    return [(latency, name, count, arm) for latency in (64, 128)
            for name, count, _ in CASES for arm in ARMS]
