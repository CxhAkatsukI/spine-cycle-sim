"""Admit only the complete declared source-functional matrix, never timing."""

import re

EXPECTED = {"empty": (0, 2, 0), "segment_weights": (36, 2, 120),
            "repeated_weights": (40, 3, 8), "dst19_weight12_boundary": (5, 1, 1)}
ARMS = ("original_cache", "registered_cache")
FINAL = "WEIGHTED_ABI_COMPLETE scope=source_functional timing_admitted=false"
ROW = re.compile(r"WEIGHTED_ABI_PASS case=(\w+) arm=(\w+) operations=(\d+) "
                 r"segments=(\d+) shards=(\d+) edges=(\d+)")
# Pristine process_1 ORs a 32-bit insertion into a 512-bit temporary. Vendor
# headers print both lines per insertion; full-state checks still apply.
INSERTIONS = 40
WARNING_PAIR = ("WARNING: Bitsize mismatch for ap_[u]int|=ap_[u]int.",
                "Warning! Bitsize mismach for ap_[u]int |= ap_[u]int.")


def diagnostics(stderr: str):
    if stderr.splitlines() != list(WARNING_PAIR) * INSERTIONS:
        raise ValueError("unexpected source diagnostics or width-warning count")
    return {"retained_vendor_width_warning_pairs": INSERTIONS,
            "origin": "pristine process_1: res_data |= update_edge (512-bit |= 32-bit)",
            "complete_intermediate_state_gate_required": True}


def analyze(stdout: str, stderr: str):
    lines = stdout.splitlines()
    diagnostics(stderr)
    if len(lines) != len(EXPECTED) * len(ARMS) + 1 or lines[-1] != FINAL:
        raise ValueError("incomplete matrix or unexpected stream diagnostics")
    rows = []
    for (case, expected), arm, line in zip(
            ((case, expected) for case, expected in EXPECTED.items() for _ in ARMS),
            ARMS * len(EXPECTED), lines[:-1], strict=True):
        match = ROW.fullmatch(line)
        if not match or match.group(1, 2) != (case, arm):
            raise ValueError("undeclared, duplicate or reordered source row")
        operations, segments, shards, edges = map(int, match.group(3, 4, 5, 6))
        if (operations, shards, edges) != expected or segments < shards:
            raise ValueError("source row scope mismatch")
        rows.append({"case": case, "arm": arm, "operations": operations,
                     "segments": segments, "shards": shards, "edges": edges})
    for index in range(0, len(rows), 2):
        if {k: v for k, v in rows[index].items() if k != "arm"} != \
                {k: v for k, v in rows[index + 1].items() if k != "arm"}:
            raise ValueError("cache arms have different work")
    return rows
