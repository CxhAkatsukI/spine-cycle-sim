"""Compare ResPR CPU reference states in external vertex order, without XRT."""

import argparse
import csv
import json
import math
from itertools import zip_longest
from pathlib import Path

STATE_FIELDS = ("warm_rank", "correction", "final_rank", "final_residual")


def _row(fields, vertex):
    if len(fields) != 7:
        raise ValueError(f"vertex {vertex}: expected seven oracle fields")
    old_degree, new_degree, active = map(int, (fields[0], fields[1], fields[6]))
    state = tuple(map(float, fields[2:6]))
    if min(old_degree, new_degree) < 0 or active not in (0, 1):
        raise ValueError(f"vertex {vertex}: invalid degree or active bit")
    if not all(map(math.isfinite, state)):
        raise ValueError(f"vertex {vertex}: non-finite oracle state")
    return (old_degree, new_degree), state, active


def compare(spine_path, gr_path, vertices):
    if vertices < 1:
        raise ValueError("expected a positive vertex count")
    errors = {key: {"l1": 0.0, "max_abs": 0.0} for key in STATE_FIELDS}
    totals = {arm: {"old_sinks": 0, "new_sinks": 0, "active_seed": 0}
              for arm in ("spine", "gr")}
    degree_mismatch = active_mismatch = 0
    count = 0
    with spine_path.open(newline="") as spine, gr_path.open(newline="") as gr:
        streams = (csv.reader(arm, delimiter="\t") for arm in (spine, gr))
        for vertex, (left, right) in enumerate(zip_longest(*streams)):
            if left is None or right is None or vertex >= vertices:
                raise ValueError(f"oracle vertex count mismatch at vertex {vertex}")
            left_degree, left_state, left_active = _row(left, vertex)
            right_degree, right_state, right_active = _row(right, vertex)
            degree_mismatch += left_degree != right_degree
            active_mismatch += left_active != right_active
            for arm, degree, active in (("spine", left_degree, left_active),
                                        ("gr", right_degree, right_active)):
                totals[arm]["old_sinks"] += degree[0] == 0
                totals[arm]["new_sinks"] += degree[1] == 0
                totals[arm]["active_seed"] += active
            for key, a, b in zip(STATE_FIELDS, left_state, right_state, strict=True):
                error = abs(a - b)
                errors[key]["l1"] += error
                errors[key]["max_abs"] = max(errors[key]["max_abs"], error)
            count += 1
    if count != vertices:
        raise ValueError(f"expected {vertices} vertices, got {count}")
    return {"claim_class": "cpu_reference_only", "vertices": count,
            "degree_mismatch_vertices": degree_mismatch,
            "active_mismatch_vertices": active_mismatch,
            "state_errors": errors, "arm_totals": totals}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spine", type=Path)
    parser.add_argument("gr", type=Path)
    parser.add_argument("vertices", type=int)
    args = parser.parse_args()
    print(json.dumps(compare(args.spine, args.gr, args.vertices), indent=2))


if __name__ == "__main__":
    main()
