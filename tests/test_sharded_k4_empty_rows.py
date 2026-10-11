"""Finite-input and statistics gates for the row-scan diagnostic."""

import copy
import json
from pathlib import Path
import struct
import tempfile
import unittest

from spine_cycle_sim.experiments.sharded_k4_stages.row_sweep import load_contract
from spine_cycle_sim.experiments.sharded_k4_stages.row_sweep_analysis import (
    adapter_samples, incremental_slopes, inspect_fixture,
)

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "configs/experiments/sharded_k4_empty_rows_v1.json"


def fixture_bytes(vertices):
    words = [0x4b345331, 1, vertices, 1, 131072, 2, 1]
    words += list(range(vertices))
    words += [0, 8, 16, 24, 32] + [0xffffffff] * (vertices - 5)
    words += [0]
    words += [0, 8, 16, 24, 1] + [0xffffffff] * (vertices - 5)
    words += [1, 64]
    words += [value for v in range(vertices) for value in (min(v, 4)*16, min(v+1, 4)*16)]
    words += list(range(64))
    return struct.pack(f"<{len(words)}I", *words)


class EmptyRowTests(unittest.TestCase):
    def test_contract_cannot_silently_reduce_scope_or_fit(self):
        original = load_contract(CONTRACT)
        for field, changed in (("vertices", [4096, 8192]), ("repeats", 1),
                               ("timing_fit_allowed", True), ("expected_rounds", 1),
                               ("updates", [[0, 4, 2, 1]])):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "contract.json"
                path.write_text(json.dumps({**original, field: changed}))
                with self.assertRaises(ValueError):
                    load_contract(path)

    def test_only_added_empty_rows_leave_payload_invariant(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            results = []
            for count in (8, 16):
                graph, fixture = directory / "graph", directory / "fixture"
                graph.write_text(f"{count} 4 1\n0 1 8\n1 2 8\n2 3 8\n3 4 8\n0 4 1 1\n")
                fixture.write_bytes(fixture_bytes(count))
                results.append(inspect_fixture(graph, fixture))
            self.assertEqual(results[0]["fixed_payload_sha256"], results[1]["fixed_payload_sha256"])
            self.assertEqual([r["trailing_empty_rows"] for r in results], [4, 12])
            data = bytearray(fixture.read_bytes())
            struct.pack_into("<I", data, 20, 1)
            fixture.write_bytes(data)
            with self.assertRaises(ValueError):
                inspect_fixture(graph, fixture)

    def test_samples_are_durations_not_sum_of_overlapping_stages(self):
        board = {"result": {"destination_partitions": "1", "executed_supersteps": "2"}, "events": []}
        for index in range(2):
            board["events"] += [dict(stage="adapter", round=index, start_ns=10, end_ns=110),
                                dict(stage="gather", round=index, start_ns=20, end_ns=90)]
        self.assertEqual(adapter_samples(board), {"duration_ns": [100, 100], "tail_ns": [20, 20]})
        board["result"]["destination_partitions"] = "2"
        with self.assertRaises(ValueError):
            adapter_samples(board)

    def test_descriptive_slopes_do_not_fit_or_clamp(self):
        first = {"vertices": 8, "arms": {}}
        for arm in ("original", "candidate"):
            first["arms"][arm] = {f"{source}_median_{metric}_ns": 100
                                  for source in ("board", "model") for metric in ("duration", "tail")}
        second = copy.deepcopy(first)
        second["vertices"] = 16
        second["arms"]["original"]["board_median_duration_ns"] = 180
        second["arms"]["candidate"]["board_median_duration_ns"] = 92
        result = incremental_slopes([first, second])[0]["arms"]
        self.assertEqual(result["original"]["board_duration_ns_per_added_row"], 10)
        self.assertEqual(result["candidate"]["board_duration_ns_per_added_row"], -1)
        with self.assertRaises(ValueError):
            incremental_slopes([second, first])


if __name__ == "__main__":
    unittest.main()
