import copy
from pathlib import Path
import tempfile
import unittest

from spine_cycle_sim.experiments.sharded_k4_stages.bank_stream.model_contract import PROFILE_ID
from spine_cycle_sim.experiments.sharded_k4_stages.bank_stream.model_validation import require_result, require_values


class BankStreamValidationTests(unittest.TestCase):
    def setUp(self):
        self.geometry = {"vertices": 1025, "partitions": 1, "rounds": 1, "pma_slots": 16,
                         "live_edges_per_round": 1, "tails": [{"visited_rows": 1, "slots": 16}]}
        self.counters = {"extent_reads": 1, "row_reads": 128, "segment_reads": 1, "packets": 2,
                         "live_edges": 1, "dummy_edges": 15, "source_blocks": 1, "source_lines": 256,
                         "source_terminators": 1, "gather_rows": 32768, "mux_rows": 32768,
                         "apply_reads": 4096, "apply_writes": 4096, "source_writes": 8192,
                         "status_writes": 1, "axi_requests": 16389, "axi_completions": 16389,
                         "axi_beats": 16771, "axi_completed_beats": 16771, "start_cycle": 0, "end_cycle": 100}
        self.result = {"profile_id": PROFILE_ID, "boundary": "resident_compute_no_host_launch_gaps",
                       "evidence": "simulator_prediction_not_hardware_timing_admission", "success": True,
                       "done": True, "failed": False, "replicas_equal": True, "ledger_closed": True,
                       "mismatches": 0, "expected_rounds": 1, "rounds": [{"active_vertices": 0}],
                       **{key: self.geometry[key] for key in ("vertices", "partitions", "pma_slots", "live_edges_per_round")},
                       "counters": self.counters, "backend_reads": 4482, "backend_writes": 12289,
                       "observed_cycles": 100,
                       "arbitration": {"ledger_closed": True, "pending_intents": 0, "pending_grants": 0,
                                       "unique_intents": 16771, "grants": 16771, "consumed_grants": 16771}}
        self.diagnostic = "source-services=2 physical-masters=7\n" + "\n".join(
            [f"worker={w} source-service=source{w % 2}" for w in range(4)]
            + [f"master=physical{x} pending=0" for x in range(7)])

    def test_admits_bursts_without_counting_parents_as_beats(self):
        self.assertFalse(require_result(self.result, self.geometry, self.diagnostic)["hardware_timing_admitted"])

    def test_rejects_incorrect_outputs_or_open_conservation(self):
        for key, value in (("success", False), ("replicas_equal", False), ("mismatches", 1),
                           ("ledger_closed", False), ("expected_rounds", 2), ("observed_cycles", 99),
                           ("evidence", "hardware_measurement")):
            with self.subTest(key=key), self.assertRaises(ValueError):
                require_result({**self.result, key: value}, self.geometry, self.diagnostic)
        for key in self.counters:
            if key == "start_cycle": continue
            invalid = copy.deepcopy(self.result)
            invalid["counters"][key] += 1
            with self.subTest(counter=key), self.assertRaises(ValueError):
                require_result(invalid, self.geometry, self.diagnostic)

    def test_rejects_wrong_source_sharing_or_extra_physical_master(self):
        for diagnostic in (self.diagnostic.replace("source-services=2", "source-services=4"),
                           self.diagnostic.replace("worker=2 source-service=source0", "worker=2 source-service=source2"),
                           self.diagnostic + "\nmaster=extra pending=0"):
            with self.assertRaisesRegex(ValueError, "topology"):
                require_result(self.result, self.geometry, diagnostic)

    def test_full_output_check_is_not_a_checksum_of_sampled_vertices(self):
        with tempfile.TemporaryDirectory() as directory:
            actual, expected = Path(directory) / "actual", Path(directory) / "expected"
            actual.write_text("0 0\n1 4\n2 8\n")
            expected.write_text(actual.read_text())
            require_values(actual, expected)
            expected.write_text("0 0\n1 5\n2 8\n")
            with self.assertRaisesRegex(ValueError, "full external output"):
                require_values(actual, expected)


if __name__ == "__main__":
    unittest.main()
