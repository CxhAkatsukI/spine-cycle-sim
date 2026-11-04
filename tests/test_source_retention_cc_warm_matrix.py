import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention import cc_warm_matrix as warm


class CcWarmMatrixTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = root = Path(directory.name)
        self.template = {key: str(root / key) for key in ("spine_host", "spine_binary", "gr_host", "inputs")}
        packet = root / "packet.json"
        warm.save(packet, self.template)
        pin = warm.identity(packet)
        self.args = SimpleNamespace(
            **{key: root / key for key in warm.matrix.INPUTS}, algorithm="cc", dataset="AU",
            au_parent=("warm.service", "a" * 32, root / "parent.json"), output=root / "matrix",
            cc_wall_packet=packet, balanced_host=packet, cc_warm_au_receipt=None, cc_warm_layout=None,
            cc_warm_r_controls=[root / str(i) for i in range(4)], child_prefix="test-warm",
            layout=[(ds, root / (ds + ".json"), root / ds / "inputs.json") for ds in warm.DATASETS],
            stage_wait_seconds=1, layout_wait_seconds=0, wait_seconds=0,
        )
        self.state = {"LoadState": "loaded", "InvocationID": "a" * 32}
        self.gate = dict(host=pin, image=pin, r={"report": pin}, g={"report": pin, "reference": pin})
        self.controls = {key: {"report": pin} for key in ("amazon_odd", "au_slice")}
        self.au = dict(status=warm.matrix.MEASURED, algorithm="cc", dataset="AU", attempts=["gr"],
                       stage_gates=self.gate, additional_r_gates=self.controls, retained_spine=pin,
                       boundary=warm.wall.BOUNDARY, warmups=0, repetitions_per_arm=1, case=self.template)
        self.jobs = {key: {"ready": True, "receipt": pin} for key in ("g", "r", "spine", *self.controls)}

    def parent_receipt(self):
        child = self.root / "child.json"
        warm.save(child, self.au)
        path = self.args.au_parent[2]
        warm.save(path, dict(result=warm.identity(child), stages=self.jobs, requested_pair=True, dataset="AU"))
        return dict(report_path=str(path), receipt=warm.identity(path))

    def test_parent_refuses_different_gate_or_duplicate_attempt(self):
        parent = self.parent_receipt()
        _, row, _ = warm.retained_au(parent, self.gate, self.controls)
        self.assertTrue(row["reused"])
        with self.assertRaisesRegex(ValueError, "exact admitted"):
            warm.retained_au(parent, dict(self.gate, resident_mhz=[1, 2, 3]), self.controls)
        self.au["attempts"] = ["spine", "gr"]
        with self.assertRaisesRegex(ValueError, "exact admitted"):
            warm.retained_au(self.parent_receipt(), self.gate, self.controls)

    def test_gate_failure_never_requests_any_board_pairs(self):
        with patch.object(warm, "service_state", return_value=self.state), \
                patch.object(warm.follow, "ready", side_effect=ValueError("R gate did not pass")), \
                patch.object(warm.matrix, "run_child") as child:
            with self.assertRaisesRegex(ValueError, "R gate did not pass"):
                warm.run(self.args)
            child.assert_not_called()
        report = warm.load(self.args.output / "matrix.json")
        self.assertEqual(report["status"], "FAILED_RETAINED")
        self.assertTrue(all(row["status"] == "NOT_REQUESTED" for row in report["cases"].values()))

    def test_reuses_au_runs_admitted_layouts_once_and_retains_failures(self):
        parent = self.parent_receipt()
        for ds, layout, _ in self.args.layout:
            warm.save(layout, dict(status="LAYOUT_PASS_OFFLINE" if ds in ("SU", "WK", "R19") else "FAILED_RETAINED"))

        def ready(job, *_):
            job.update(parent)
            return True

        admission = warm.resident.active_min_admission
        with patch.object(warm, "service_state", return_value=self.state), \
                patch.object(warm.follow, "ready", side_effect=ready), \
                patch.object(admission, "admit", return_value=self.gate), \
                patch.object(admission, "pin_odd_queue", return_value=[]), \
                patch.object(admission, "replay_r", side_effect=self.controls.values()), \
                patch.object(warm.resident, "frozen_case", return_value=({}, [])), \
                patch.object(warm.wall, "configure", return_value=({"memory_gib": 32}, [])), \
                patch.object(warm.matrix, "run_child", side_effect=[dict(status=warm.matrix.MEASURED),
                    dict(status="FAILED_RETAINED", attempts=["spine"]), dict(status=warm.matrix.MEASURED)]) as child:
            report = warm.run(self.args)
        self.assertEqual([call.args[3] for call in child.call_args_list], ["SU", "WK", "R19"])
        self.assertTrue(report["cases"]["AU"]["reused"])
        self.assertEqual(report["cases"]["SO"]["status"], "LAYOUT_NOT_ADMITTED")
        self.assertEqual(report["cases"]["WK"]["attempts"], ["spine"])
        self.assertEqual(report["status"], "CC_MATRIX_WITH_FAILURES")
        self.assertEqual(warm.load(self.args.output / "matrix.json"), report)
        command = child.call_args.args[0]
        self.assertIn("--property=MemorySwapMax=0", command)
        self.assertIn("--cc-warm-layout", command)
        self.assertEqual(command[-4:], list(map(str, self.args.cc_warm_r_controls)))


if __name__ == "__main__":
    unittest.main()
