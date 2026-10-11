import unittest

from spine_cycle_sim.experiments.sharded_k4_stages.sst_delivery import tail_diagnostic


class TailDiagnosticTests(unittest.TestCase):
    def fixture(self):
        model = {"rounds": [{}], "invocations": [
            {"stage": "adapter", "round": 1, "partition": 0, "end": 300},
            {"stage": "gather", "round": 1, "partition": 0, "end": 150}]}
        board = {"events": [
            {"stage": "adapter", "round": 0, "shard": 0, "end_ns": 4000},
            {"stage": "gather", "round": 0, "shard": 0, "end_ns": 2000}]}
        inventory = [{"partition": 0, "trailing_empty_rows": 10}]
        return model, board, inventory

    def test_units_and_round_rebase(self):
        report = tail_diagnostic(*self.fixture())
        self.assertEqual(report["model_median_nominal_ns_per_row"], 100)
        self.assertEqual(report["board_median_nominal_ns_per_row"], 200)
        self.assertIn("not_exclusive_AXI_latency", report["claim"])

    def test_no_negative_tail(self):
        model, board, inventory = self.fixture()
        model["invocations"][0]["end"] = 100
        report = tail_diagnostic(model, board, inventory)
        self.assertEqual(report["model_median_nominal_ns_per_row"], 0)

    def test_missing_stage_is_not_zero_cost(self):
        model, board, inventory = self.fixture()
        board["events"].pop()
        with self.assertRaises(KeyError):
            tail_diagnostic(model, board, inventory)


if __name__ == "__main__":
    unittest.main()
