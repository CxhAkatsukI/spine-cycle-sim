"""Retain all 190 legacy observations and add the explicit finite topology."""

from ..metadata_credits.preparation import ARMS as PREVIOUS_ARMS, CASES, prepare

ARM = "cached_hot64_m32_finite"
ARMS = PREVIOUS_ARMS + (ARM,)
GEOMETRY = {"workers_per_cu": 64, "groups_per_cu": 8, "workers_per_group": 8,
    "internal_channels_per_cu": 339, "internal_fifo_token_bits_per_cu": 38608,
    "ordinary_fifo_depth": 2, "memory_request_response_fifo_depth": 32,
    "metadata_parents": 32, "update_parents": 16,
    "transport_ii_cycles_assumed": 1, "transport_register_cycles_assumed": 1,
    "axi_response_order": "bounded_arrival_reorder_then_registered_issue_order_publication",
    "axi_response_word_slots_per_cu": 48, "axi_response_payload_and_valid_bits_per_cu": 3120,
    "metadata_lane_tag_bits_per_cu": 192}


def matrix():
    return [(latency, name, count, arm) for latency in (64, 128)
            for name, count, _ in CASES for arm in ARMS]
