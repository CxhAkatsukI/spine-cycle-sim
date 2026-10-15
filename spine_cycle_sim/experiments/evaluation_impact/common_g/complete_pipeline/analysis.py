"""Validate all declared full-capacity source-composition executions."""

import json

COUNTS = (0, 257, 129)
MARKER = ("COMPLETE_G_SOURCE_PASS four_search_cus=4 hot_half_segments=131072 "
          "cold_segments=4 metadata_generations=2 internal_cache_ddr_fifos=unbounded "
          "timing_admitted=false")
WARNING_PAIR = ("WARNING: Bitsize mismatch for ap_[u]int|=ap_[u]int.",
                "Warning! Bitsize mismach for ap_[u]int |= ap_[u]int.")


def expected_ports(batch):
    ports = [0, 0, 0, 0]
    for operation in range(sum(COUNTS[:batch]), sum(COUNTS[:batch + 1])):
        ordinal = operation % 10
        ports[(ordinal % 2) * 2 + (ordinal >= 6)] += 1
    return ports


def expected_edges(batch):
    operations = sum(COUNTS[:batch + 1])
    return 40 + sum(((operations + 9 - ordinal) // 10) % 2 for ordinal in range(10))


def diagnostics(stderr):
    # Pristine hot-cache and production cold-DDR inserts both widen 32 to 512
    # bits with |=. The registered hot path does not; keep every vendor warning.
    pairs = 2 * sum(1 for registered in range(2) for operation in range(sum(COUNTS))
                    if operation // 10 % 2 == 0 and (not registered or operation % 10 >= 6))
    remaining = stderr
    for message in WARNING_PAIR:
        if remaining.count(message) != pairs:
            raise ValueError("unexpected diagnostics or pristine insertion width-warning count")
        remaining = remaining.replace(message, "")
    # Concurrent vendor writers can put both complete messages on one line.
    if remaining.strip():
        raise ValueError("unexpected diagnostics or pristine insertion width-warning count")
    return {"retained_vendor_width_warning_pairs": pairs,
            "origin": "pristine hot-cache / production cold-DDR: 512-bit |= 32-bit insertion",
            "complete_intermediate_state_gate_required": True}


def analyze(stdout, stderr):
    lines = stdout.splitlines()
    diagnostics(stderr)
    if len(lines) != 13 or lines[-1] != MARKER:
        raise ValueError("complete G source scope or final marker mismatch")
    rows = [json.loads(line.removeprefix("COMPLETE_G_ROW ")) for line in lines
            if line.startswith("COMPLETE_G_ROW ")]
    expected = [(arm, generation, batch) for arm in range(2) for generation in range(2)
                for batch in range(3)]
    if [(row["registered"], row["generation"], row["batch"]) for row in rows] != expected:
        raise ValueError("incomplete or reordered declared G composition scope")
    for row in rows:
        batch = row["batch"]
        if row["updates"] != COUNTS[batch] or row["edges"] != expected_edges(batch) or \
                [row[key] for key in ("hot_even", "cold_even", "hot_odd", "cold_odd")] != expected_ports(batch):
            raise ValueError("complete G update/edge/hot-cold conservation mismatch")
    return rows
