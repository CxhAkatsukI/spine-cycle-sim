import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention import cc_matrix, spine_cc_layout


class CcMatrixTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        template = root / "template.json"
        template.write_text("{}")
        self.args = SimpleNamespace(
            **{key: root / key for key in cc_matrix.resident_matrix.INPUTS},
            algorithm="cc", dataset="R19", output=root / "matrix", cc_wall_packet=template,
            small=[(ds, str(root / ds), str(root / (ds + ".log"))) for ds in cc_matrix.SMALL],
            child_prefix="cc-test", stage_wait_seconds=10, wait_seconds=0, r19_output=root / "r19",
        )
        pin = cc_matrix.identity(template)
        self.gate = dict(host=pin, image=pin, r={"report": pin}, g={"report": pin, "reference": pin})
        self.jobs = {key: dict(unit=key, ready=True, receipt=pin) for key in ("g", "r", "odd")}

    def prepare(self, args, ds, small, campaign, template, row):
        if ds in cc_matrix.LARGE and ds.lower() not in campaign["rows"]:
            raise ValueError("large host layout did not complete")
        row.update(case={"memory_gib": 32}, pins=[])
        return args.output / (ds + ".json")

    def test_r19_intermediate_memory_cap_is_layout_only(self):
        common = ["--matrix", "matrix", "--output", "output", "--datasets", "r19", "--memory-gib", "12"]
        args = spine_cc_layout.arguments([*common, "--host", "host", "--inputs", "inputs"])
        self.assertEqual(args.memory_gib, 12)
        with self.assertRaises(SystemExit):
            spine_cc_layout.arguments(common)

    def test_failed_odd_gate_prevents_board_launch(self):
        with patch.object(cc_matrix, "stage_jobs", return_value=self.jobs), \
                patch.object(cc_matrix, "layout_packet", side_effect=self.prepare), \
                patch.object(cc_matrix.active_min_admission, "admit", return_value=self.gate), \
                patch.object(cc_matrix.resident_matrix, "admitted_odd", side_effect=ValueError("R over 15%")), \
                patch.object(cc_matrix.resident_matrix, "run_child") as child:
            with self.assertRaisesRegex(ValueError, "R over 15%"):
                cc_matrix.run(self.args)
            child.assert_not_called()

    def test_failed_topology_gate_prevents_board_launch(self):
        self.args.au_slice_r = ["cc-topology.service", "a" * 32, "pair.json", "inputs"]
        topology = dict(unit="cc-topology.service", ready=False)
        with patch.object(cc_matrix, "stage_jobs", return_value=self.jobs), \
                patch.object(cc_matrix, "topology_job", return_value=topology), \
                patch.object(cc_matrix, "service_state"), \
                patch.object(cc_matrix.follow, "ready", side_effect=ValueError("AU R over 15%")), \
                patch.object(cc_matrix, "layout_packet", side_effect=self.prepare), \
                patch.object(cc_matrix.resident_matrix, "run_child") as child:
            with self.assertRaisesRegex(ValueError, "AU R over 15%"):
                cc_matrix.run(self.args)
            child.assert_not_called()
        report = json.loads((self.args.output / "matrix.json").read_text())
        self.assertEqual(report["status"], "FAILED_RETAINED")
        self.assertTrue(all(row["status"] == "NOT_REQUESTED" for row in report["cases"].values()))

    def test_topology_replay_pins_geometry_image_clock_and_receipt(self):
        pin = self.gate["host"]
        gate = dict(self.gate, resident_mhz=[150, 500, 450, 0])
        job = dict(report_path=pin["path"], inputs=pin["path"], receipt=pin)
        good = dict(report=pin, candidate_clock={"driver_reported_mhz": gate["resident_mhz"]})
        with patch.object(cc_matrix.active_min_admission, "replay_r", return_value=good) as replay:
            self.assertEqual(cc_matrix.admit_topology(self.args, job, gate), good)
            replay.assert_called_once_with(Path(pin["path"]), "cc", Path(pin["path"]),
                                           pin, pin, geometry=(156289, 903774, 12))
            good["candidate_clock"] = {"driver_reported_mhz": [150, 500, 423, 0]}
            with self.assertRaisesRegex(ValueError, "image, clock and producer receipt"):
                cc_matrix.admit_topology(self.args, job, gate)

    def test_keeps_partial_layout_failures_and_never_repeats_r19(self):
        pin = self.gate["host"]
        with patch.object(cc_matrix, "stage_jobs", return_value=self.jobs), \
                patch.object(cc_matrix, "layout_packet", side_effect=self.prepare), \
                patch.object(cc_matrix, "wait_for_layout", return_value=({"rows": {"so": {}}}, pin)), \
                patch.object(cc_matrix.active_min_admission, "admit", return_value=self.gate), \
                patch.object(cc_matrix.resident_matrix, "admitted_odd", return_value=({"report": pin}, [])), \
                patch.object(cc_matrix.resident_matrix, "run_child",
                             return_value={"status": cc_matrix.resident_matrix.MEASURED}) as child:
            result = cc_matrix.run(self.args)
        self.assertEqual([call.args[3] for call in child.call_args_list], ["AU", "SU", "WK", "SO"])
        command = child.call_args.args[0]
        self.assertIn("--property=MemoryMax=32G", command)
        self.assertIn("--property=MemorySwapMax=0", command)
        self.assertIn("--cc-wall-packet", command)
        self.assertEqual(result["status"], "CC_MATRIX_WITH_FAILURES")
        self.assertEqual(result["cases"]["PK"]["status"], "LAYOUT_NOT_ADMITTED")
        self.assertEqual(json.loads((self.args.output / "matrix.json").read_text()), result)

    def test_includes_r19_once_using_original_packet(self):
        self.args.include_r19 = True
        pin = self.gate["host"]
        with patch.object(cc_matrix, "stage_jobs", return_value=self.jobs), \
                patch.object(cc_matrix, "layout_packet", side_effect=self.prepare), \
                patch.object(cc_matrix, "wait_for_layout",
                             return_value=({"rows": {ds.lower(): {} for ds in cc_matrix.LARGE}}, pin)), \
                patch.object(cc_matrix.resident, "frozen_case", return_value=({}, [])), \
                patch.object(cc_matrix.cc_resident_wall, "configure", return_value=({"memory_gib": 32}, [])), \
                patch.object(cc_matrix.active_min_admission, "admit", return_value=self.gate), \
                patch.object(cc_matrix.resident_matrix, "admitted_odd", return_value=({"report": pin}, [])), \
                patch.object(cc_matrix.resident_matrix, "run_child",
                             return_value={"status": cc_matrix.resident_matrix.MEASURED}) as child:
            result = cc_matrix.run(self.args)
        self.assertEqual([call.args[3] for call in child.call_args_list], [*cc_matrix.SMALL, *cc_matrix.LARGE, "R19"])
        self.assertIn(str(self.args.cc_wall_packet), child.call_args.args[0])
        self.assertNotIn("r19_not_repeated", result)


if __name__ == "__main__":
    unittest.main()
