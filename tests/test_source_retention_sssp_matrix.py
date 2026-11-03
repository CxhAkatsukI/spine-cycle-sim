import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention import sssp_matrix as matrix


class SsspMatrixTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.args = SimpleNamespace(
            **{key: self.root / key for key in matrix.INPUTS},
            output=self.root / "output", algorithm=matrix.ALGORITHM, dataset="AU",
            cc_wall_packet=None, au_unit="au.service", au_invocation="a" * 32,
            odd_unit="odd.service", odd_invocation="b" * 32, child_prefix="sssp-test",
            wait_seconds=0, au_wait_seconds=1,
        )
        self.pins = []
        for name in ("host", "image", "r", "g", "reference", "au_queue", "au_result"):
            path = self.root / name
            path.write_text(name)
            self.pins.append(matrix.identity(path))
        host, image, r, g, ref, *_ = self.pins
        self.gate = dict(host=host, image=image, r={"report": r}, g={"report": g, "reference": ref},
                         resident_mhz=150)
        self.mocks = patch.multiple(matrix, service_state=lambda _: {"LoadState": "not-found", "InvocationID": ""},
                                    route_finished=lambda *_: False, runner_pins=lambda: [],
                                    admitted_au=lambda *_: self.pins[-2:])
        self.mocks.start()
        self.addCleanup(self.mocks.stop)
        for owner, name, value in (
            (matrix.resident, "frozen_case", lambda *_: ({"memory_gib": 24}, [])),
            (matrix.active_min_admission, "admit", lambda *_: self.gate),
        ):
            mock = patch.object(owner, name, value)
            mock.start()
            self.addCleanup(mock.stop)

    def test_odd_r_failure_never_requests_a_board_job(self):
        with patch.object(matrix, "admitted_odd", side_effect=ValueError("R over 15 percent")), \
                patch.object(matrix.subprocess, "run") as launch:
            with self.assertRaisesRegex(ValueError, "R over 15 percent"):
                matrix.run(self.args)
            launch.assert_not_called()
        journal = json.loads((self.args.output / "matrix.json").read_text())
        self.assertEqual(journal["status"], "FAILED_RETAINED")
        self.assertEqual({row["status"] for row in journal["cases"].values()}, {"NOT_REQUESTED"})

    def test_one_job_per_dataset_and_no_retry_on_failure(self):
        launched = []

        def launch(command, **kwargs):
            ds = command[command.index("--dataset") + 1]
            launched.append(ds)
            self.assertIn("--property=MemoryMax=24G", command)
            self.assertIn("--property=MemoryHigh=22G", command)
            self.assertIn("--property=MemorySwapMax=0", command)
            output = Path(command[command.index("--output") + 1])
            output.mkdir()
            failed = ds == "WK"
            matrix.save(output / "results.json", dict(
                status="FAILED_RETAINED" if failed else matrix.MEASURED, dataset=ds,
                attempts=["spine"] if failed else ["spine", "gr"], stage_gates=self.gate,
                boundary=matrix.resident.BOUNDARY, warmups=0, repetitions_per_arm=1,
            ))
            return subprocess.CompletedProcess(command, int(failed))

        with patch.object(matrix, "admitted_odd", return_value=({}, [])), \
                patch.object(matrix.subprocess, "run", side_effect=launch):
            report = matrix.run(self.args)
        self.assertEqual(launched, ["SU", "WK", "SO", "PK", "LJ", "LJ08", "R19"])
        self.assertEqual(report["status"], "SSSP_MATRIX_WITH_FAILURES")
        self.assertEqual(report["cases"]["WK"]["attempts"], ["spine"])
        self.assertEqual(report["cases"]["R19"]["status"], matrix.MEASURED)


if __name__ == "__main__":
    unittest.main()
