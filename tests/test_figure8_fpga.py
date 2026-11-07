"""The FPGA update-only sweep cannot substitute one batch or simulated time."""

from pathlib import Path
import tempfile
import unittest

from spine_cycle_sim.experiments.evaluation_impact.figure8_fpga import analysis, inputs


class Figure8FPGA(unittest.TestCase):
    case = dict(vertices=8, initial_edges=2, updates=5, batches=2)

    def text(self, arm="spine"):
        prefix = "SPINE" if arm == "spine" else "GRASU"
        setup = "bootstrap_ns=20 checked_edges=7" if arm == "spine" else "upload_ns=20 pma_mismatches=0"
        return (f"{prefix}_PERSISTENT_BATCH batch=0 updates=2 batch_ns=3 update_wall_ns=5\n"
                f"{prefix}_PERSISTENT_BATCH batch=1 updates=3 batch_ns=4 update_wall_ns=6\n"
                f"{prefix}_PERSISTENT_UPDATE status=PASS vertices=8 initial_edges=2 logical_updates=5 "
                f"batches=2 layout_ns=10 {setup} batch_ns=7 update_wall_ns=11 setup_inclusive_ns=48\n")

    def test_checks_both_arms_and_timer_sum(self):
        for arm in ("spine", "gr"):
            self.assertEqual(analysis.timing(self.text(arm), arm, self.case)["setup_inclusive_ns"], 48)
        with self.assertRaises(ValueError):
            analysis.timing(self.text().replace("setup_inclusive_ns=48", "setup_inclusive_ns=49"), "spine", self.case)

    def test_rejects_missing_reordered_or_duplicate_batches(self):
        for text in (self.text().replace("batch=0", "batch=1"),
                     self.text().split("\n", 1)[1],
                     self.text().replace("batch_ns=3", "batch_ns=3 batch_ns=3"),
                     self.text().replace("update_wall_ns=6", "update_wall_ns=7")):
            with self.subTest(text=text), self.assertRaises(ValueError):
                analysis.timing(text, "spine", self.case)

    def test_no_wrong_count_or_missing_final_check(self):
        for text in (self.text().replace("updates=2", "updates=3"),
                     self.text().replace("checked_edges=7", "checked_edges=6"),
                     self.text().replace("status=PASS", "status=FAIL")):
            with self.subTest(text=text), self.assertRaises(ValueError):
                analysis.timing(text, "spine", self.case)

    def test_stream_conversion_preserves_ids_weights_and_order(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            graph, update, output = (root / name for name in ("old", "new", "native"))
            graph.write_text("# vertices=8\n4 7 3 1\n0 2 8 1\n")
            update.write_text("# vertices=8\n3 5 2 1\n1 6 4 1\n")
            row = inputs.convert(graph, update, output, 2)
            self.assertEqual(output.read_text(), "8 2 2\n4 7 3\n0 2 8\n3 5 2 1\n1 6 4 1\n")
            self.assertEqual((row["vertices"], row["initial_edges"], row["updates"]), (8, 2, 2))

    def test_rejects_delete_and_out_of_domain(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "slice"
            for line in ("0 2 1 -1", "0 8 1 1", "0 2 4096 1"):
                path.write_text("# vertices=8\n" + line + "\n")
                with self.assertRaises(ValueError):
                    list(inputs.records(path, {}))


if __name__ == "__main__":
    unittest.main()
