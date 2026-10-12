"""Reject nominal success when fixture or traffic identities disagree."""

import copy
from pathlib import Path
import struct
import tempfile
import unittest

from spine_cycle_sim.experiments.sharded_k4_stages.row_line.model_contract import PROFILE_ID
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.model_validation import compare, inventory, require_result


def fixture(path: Path) -> None:
    rows = [0, 0] * 2 + [0, 16] + [16, 16] * 6
    words = [1, 2] + [0x80000000] * 14
    data = [0x4b345331, 1, 9, 1, 1, 2, 1, *range(9), *([0] * 9), 0, *([0] * 9), 1, 16, *rows, *words]
    path.write_bytes(struct.pack(f"<{len(data)}I", *data))


def result(geometry: dict, arm: str) -> dict:
    c = {"extent_reads": 2, "row_reads": 16 if arm == "original" else 2, "segment_reads": 2,
         "packets": 4, "live_edges": 4, "dummy_edges": 28, "source_blocks": 2, "source_lines": 512,
         "source_terminators": 2, "gather_rows": 65536, "mux_rows": 65536,
         "apply_reads": 8192, "apply_writes": 8192, "source_writes": 16384, "status_writes": 2,
         "start_cycle": 0, "end_cycle": 100}
    parents = sum(c[key] for key in ("extent_reads", "row_reads", "segment_reads", "source_blocks",
                                    "apply_reads", "apply_writes", "source_writes", "status_writes"))
    beats = parents - c["source_blocks"] + c["source_lines"]
    c.update(axi_requests=parents, axi_completions=parents, axi_beats=beats, axi_completed_beats=beats)
    return {"profile_id": PROFILE_ID, "boundary": "resident_compute_no_host_launch_gaps",
            "evidence": "simulator_prediction_not_hardware_timing_admission", "success": True,
            "done": True, "failed": False, "mismatches": 0, "replicas_equal": True, "ledger_closed": True,
            **{key: geometry[key] for key in ("vertices", "partitions", "pma_slots", "live_edges_per_round")},
            "expected_rounds": 2, "rounds": [{"active_vertices": 1}, {"active_vertices": 0}], "counters": c,
            "backend_reads": sum(c[key] for key in ("extent_reads", "row_reads", "segment_reads", "source_lines", "apply_reads")),
            "backend_writes": sum(c[key] for key in ("apply_writes", "source_writes", "status_writes")),
            "arbitration": {"ledger_closed": True, "pending_intents": 0, "pending_grants": 0,
                            "unique_intents": beats, "grants": beats, "consumed_grants": beats}}


class RowLineModelValidationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "resident.bin"
        fixture(self.path)
        self.geometry = inventory(self.path)

    def test_independent_inventory_and_complete_traffic(self):
        self.assertEqual(self.geometry["tails"][0]["visited_rows"], 3)
        self.assertEqual(self.geometry["tails"][0]["reference_reads_per_round"], 8)
        self.assertEqual(self.geometry["tails"][0]["candidate_reads_per_round"], 1)
        report = compare(result(self.geometry, "original"), result(self.geometry, "candidate"), self.geometry)
        self.assertFalse(report["hardware_timing_admitted"])
        self.assertEqual(report["arms"]["candidate"]["directory_requests"], 4)

    def test_row_directory_and_all_conservation_counters_checked(self):
        original = result(self.geometry, "candidate")
        for key in original["counters"]:
            if key in ("start_cycle", "end_cycle", "source_blocks"):
                continue
            candidate = copy.deepcopy(original)
            candidate["counters"][key] += 1
            with self.subTest(key=key), self.assertRaises(ValueError):
                require_result(candidate, self.geometry, "candidate")

    def test_failure_or_geometry_or_round_change_is_not_accepted(self):
        original = result(self.geometry, "candidate")
        for key, value in (("success", False), ("done", False), ("failed", True), ("mismatches", 1),
                           ("replicas_equal", False), ("ledger_closed", False), ("vertices", 8),
                           ("expected_rounds", 3), ("evidence", "hardware_measured")):
            with self.subTest(key=key), self.assertRaises(ValueError):
                require_result({**original, key: value}, self.geometry, "candidate")
        candidate = copy.deepcopy(original)
        candidate["rounds"][0]["active_vertices"] = 2
        with self.assertRaisesRegex(ValueError, "convergence"):
            compare(result(self.geometry, "original"), candidate, self.geometry)

    def test_unclosed_arbitration_rejected(self):
        candidate = result(self.geometry, "candidate")
        candidate["arbitration"]["pending_grants"] = 1
        with self.assertRaisesRegex(ValueError, "drain"):
            require_result(candidate, self.geometry, "candidate")

    def test_malformed_inventory_rejected(self):
        original = self.path.read_bytes()
        for payload in (original + b"tail", original[:-4], original[:28],
                        struct.pack("<I", 0) + original[4:]):
            self.path.write_bytes(payload)
            with self.subTest(size=len(payload)), self.assertRaises((ValueError, EOFError, struct.error)):
                inventory(self.path)


if __name__ == "__main__":
    unittest.main()
