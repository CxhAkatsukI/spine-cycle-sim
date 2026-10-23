"""Full-state and frontier checks for the opt-in residual Apply candidate."""

import csv
import io
import math
from pathlib import Path
import struct


def residual_comparison(dense, sparse, epsilon, vertices):
    if len(dense) != 4 * vertices or len(sparse) != len(dense):
        raise ValueError("full numerical state size differs")
    values = [[v for (v,) in struct.iter_unpack("<f", blob)] for blob in (dense, sparse)]
    if any(not math.isfinite(v) or abs(v) > epsilon for array in values for v in array):
        raise ValueError("full numerical state is not a converged finite residual")
    # A diagnostic tolerance, not a change to either arm's activation threshold.
    tolerance = 4 * 2**-23 * epsilon
    maximum = max((abs(a - b) for a, b in zip(*values)), default=0)
    if maximum > tolerance:
        raise ValueError("full numerical state residual difference exceeds FP32 comparison tolerance")
    differences = sum(a != b for a, b in zip(struct.iter_unpack("<I", dense), struct.iter_unpack("<I", sparse)))
    return dict(residual_words_identical=dense == sparse, residual_differing_words=differences,
                residual_maximum_absolute_difference=maximum, residual_comparison_tolerance=tolerance)


def frontier_comparison(dense_read, sparse_read, dense, sparse, vertices):
    changed_order = 0
    for direction in ("in", "out"):
        def rounds(read, row):
            prefix = "matrix/" + Path(row["spine"]["evidence"]).name + "/"
            records = list(csv.DictReader(io.StringIO(read(prefix + "rounds.csv").decode())))
            if len(records) != row["spine"]["rounds"]:
                raise ValueError("complete frontier round evidence required")
            result = []
            for i, record in enumerate(records):
                blob = read(prefix + f"frontier-{i}-{direction}.u32le")
                ids = tuple(v for (v,) in struct.iter_unpack("<I", blob))
                if (len(ids) != int(record["active_" + direction]) or len(set(ids)) != len(ids) or
                        any(v >= vertices for v in ids)):
                    raise ValueError("complete unique valid frontier IDs required")
                result.append(ids)
            return result
        left, right = rounds(dense_read, dense), rounds(sparse_read, sparse)
        if len(left) != len(right) or any(set(a) != set(b) for a, b in zip(left, right)):
            raise ValueError("Spine frontier vertex sets changed")
        changed_order += sum(a != b for a, b in zip(left, right))
    return dict(frontier_vertex_sets_identical=True, frontier_order_changed_lists=changed_order)
