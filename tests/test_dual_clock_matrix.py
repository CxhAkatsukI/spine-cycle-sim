import argparse
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention import (
    dual_clock_matrix as matrix, dual_clock_resident as resident,
)


class DualClockMatrixTests(unittest.TestCase):
    def test_complete_dataset_declaration_and_failure_retention(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "matrix"
            args = argparse.Namespace(output=output, child_prefix="test-pair",
                                      board_wait_seconds=10)
            for key in matrix.INPUTS:
                setattr(args, key, Path(temporary) / key)
            gate = {"pins": []}
            measured = matrix.resident_matrix.MEASURED
            called = []

            def child(command, log, directory, dataset, admitted, boundary):
                called.append(dataset)
                self.assertEqual(admitted, gate)
                self.assertEqual(boundary, resident.BOUNDARY)
                return {"status": "FAILED_RETAINED" if dataset == "SU" else measured}

            with patch.object(matrix, "check_memory"), \
                    patch.object(resident, "admit", return_value=gate), \
                    patch.object(resident, "declaration", side_effect=lambda previous, dataset:
                        ({"dataset": dataset}, 24, [])), \
                    patch.object(matrix, "identity", side_effect=lambda path: {"path": str(path)}), \
                    patch.object(matrix, "unchanged"), \
                    patch.object(matrix.resident_matrix, "run_child", side_effect=child):
                report = matrix.run(args)
            self.assertEqual(called, list(matrix.active_min_resident.DATASETS))
            self.assertEqual(report["status"], "RETAINED_INCOMPLETE_MATRIX")
            self.assertEqual(report["cases"]["SU"]["status"], "FAILED_RETAINED")
            self.assertEqual(report["repetitions_per_arm"], 1)
            self.assertFalse(report["nominal_timing_pass"])
            self.assertEqual(json.loads((output / "matrix.json").read_text()), report)
            command = report["cases"]["AU"]["command"]
            self.assertIn("--property=MemoryMax=24G", command)
            self.assertIn("--property=MemorySwapMax=0", command)
            self.assertNotIn("--repetitions", command)

    def test_large_cases_keep_the_frozen_graph_and_budget(self):
        frozen = dict(dataset="LJ", graph="graph", source=0, vertices=100,
                      edges=200, updates=8, memory_gib=32)
        with patch.object(resident.active_min_resident, "frozen_case",
                          return_value=(frozen, ["pin"])):
            case, budget, pins = resident.declaration(Path("previous"), "LJ")
        self.assertEqual(budget, 32)
        self.assertEqual(pins, ["pin"])
        self.assertEqual(case["graph"], "graph")
        self.assertEqual(case["updates"], 8)
        self.assertFalse(case["requires_propagation"])
        self.assertEqual(case["algorithm"], "residual_pagerank")

    def test_nominal_or_different_image_g_evidence_is_rejected(self):
        profile = [140, 500, 430, 0]
        measured = dict(bdf="card", device=0, pins={"r_current": "image"})
        report = dict(status="DERATED_G_GATE_PASS", nominal_timing_pass=False,
            r_report="rpin", profile_mhz=profile, bdf="card", device=0,
            image="image", host={"sha256": "host"})
        with tempfile.TemporaryDirectory() as temporary:
            g_path = Path(temporary) / "g.json"
            for override in (dict(nominal_timing_pass=True), dict(image="different"),
                             dict(profile_mhz=[150, 500, 450, 0]), dict(device=1)):
                g_path.write_text(json.dumps({**report, **override}))
                with self.subTest(override=override), \
                        patch.object(resident.g_control, "admit_screen",
                            return_value=({"profile_mhz": profile}, measured)), \
                        patch.object(resident, "identity", return_value="rpin"), \
                        patch.object(resident.board, "native_host_sha256", return_value="host"), \
                        self.assertRaisesRegex(ValueError, "exact same-clock"):
                    resident.admit(Path("r"), g_path, Path("route"))


if __name__ == "__main__":
    unittest.main()
