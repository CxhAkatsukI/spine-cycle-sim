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
            cc_wall_packet=None, au_unit="au.service", au_invocation="a" * 32, au_output=self.root / "au",
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
                patch.object(matrix.resident_matrix.subprocess, "run") as launch:
            with self.assertRaisesRegex(ValueError, "R over 15 percent"):
                matrix.run(self.args)
            launch.assert_not_called()
        journal = json.loads((self.args.output / "matrix.json").read_text())
        self.assertEqual(journal["status"], "FAILED_RETAINED")
        self.assertEqual({row["status"] for row in journal["cases"].values()}, {"NOT_REQUESTED"})

    def test_complete_matrix_requires_exact_three_producer_receipts(self):
        self.args.include_au = True
        self.args.au_unit = self.args.au_invocation = self.args.au_output = None
        odd = {"report": self.pins[-1]}
        jobs = {key: dict(unit=f"{key}.service", receipt=row["report"]) for key, row in
                (("g", self.gate["g"]), ("r", self.gate["r"]), ("odd", odd))}
        with patch.object(matrix.resident_matrix, "stage_jobs", return_value=jobs), \
                patch.object(matrix.follow, "ready", return_value=True) as ready, \
                patch.object(matrix, "admitted_au") as legacy, \
                patch.object(matrix, "admitted_odd", return_value=(odd, [])), \
                patch.object(matrix, "run_child", return_value={"status": matrix.MEASURED}) as launch:
            report = matrix.run(self.args)
        legacy.assert_not_called()
        self.assertEqual(ready.call_count, 3)
        self.assertEqual(list(report["cases"]), list(matrix.resident.DATASETS))
        self.assertEqual([call.args[3] for call in launch.call_args_list], list(matrix.resident.DATASETS))
        self.assertEqual(report["status"], "MEASURED_SSSP_MATRIX")

        self.args.output = self.root / "mismatch"
        jobs["g"]["receipt"] = odd["report"]
        with patch.object(matrix.resident_matrix, "stage_jobs", return_value=jobs), \
                patch.object(matrix, "admitted_odd", return_value=(odd, [])), \
                patch.object(matrix, "run_child") as launch:
            with self.assertRaisesRegex(ValueError, "exact producer receipts"):
                matrix.run(self.args)
        launch.assert_not_called()

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
                patch.object(matrix.resident_matrix.subprocess, "run", side_effect=launch):
            report = matrix.run(self.args)
        self.assertEqual(launched, ["SU", "WK", "SO", "PK", "LJ", "LJ08", "R19"])
        self.assertEqual(report["status"], "SSSP_MATRIX_WITH_FAILURES")
        self.assertEqual(report["cases"]["WK"]["attempts"], ["spine"])
        self.assertEqual(report["cases"]["R19"]["status"], matrix.MEASURED)

    def test_continue_stopped_journal_preserves_attempts_and_prioritizes_memory(self):
        original = self.root / "previous-matrix"
        (original / "so").mkdir(parents=True)
        odd = {"report": self.pins[-1]}
        jobs = {key: dict(unit=f"{key}.service", ready=True, receipt=row["report"]) for key, row in
                (("g", self.gate["g"]), ("r", self.gate["r"]), ("odd", odd))}
        memory = dict(AU=16, SU=16, WK=16, SO=32, PK=24, LJ=32, LJ08=32, R19=16)
        rows = {ds: dict(case={"memory_gib": budget}, pins=[], status="NOT_REQUESTED")
                for ds, budget in memory.items()}
        rows["AU"].update(status=matrix.MEASURED, result=self.pins[-2], attempts=["spine", "gr"])
        rows["WK"].update(status="FAILED_RETAINED", attempts=["spine"])
        rows["SO"].update(status="REQUESTED", command=["--unit=old-so"])
        child = original / "so/results.json"
        receipt = dict(status="WAITING_FOR_MEMORY", attempts=[], arms={}, dataset="SO",
                       algorithm=matrix.ALGORITHM)
        matrix.save(child, receipt)
        journal = original / "matrix.json"
        matrix.save(journal, dict(status="RUNNING_SINGLE_PASS", cases=rows, repetitions_per_arm=1,
                                  warmups=0, prerequisites=jobs, baseline=self.gate, odd_r=odd))
        self.args.include_au = True
        self.args.au_unit = self.args.au_invocation = self.args.au_output = None
        self.args.continue_from = (journal, matrix.identity(journal)["sha256"], "original.service")
        with patch.object(matrix.sssp_continuation, "require_stopped") as stopped, \
                patch.object(matrix.resident, "frozen_case", side_effect=lambda _, __, ds: (rows[ds]["case"], [])), \
                patch.object(matrix, "admitted_odd", return_value=(odd, [])), \
                patch.object(matrix, "run_child", return_value={"status": matrix.MEASURED}) as launch:
            stopped.return_value = {"ActiveState": "inactive"}
            self.args.output = self.root / "attempted"
            matrix.save(child, dict(receipt, attempts=["spine"]))
            with self.assertRaisesRegex(ValueError, "ambiguous or attempted"):
                matrix.run(self.args)
            launch.assert_not_called()

            matrix.save(child, receipt)
            self.args.output = self.root / "continued"
            report = matrix.run(self.args)
            self.assertEqual([call.args[3] for call in launch.call_args_list], ["SU", "R19", "PK", "SO", "LJ", "LJ08"])
            self.assertEqual(report["cases"]["AU"], rows["AU"])
            self.assertEqual(report["cases"]["WK"], rows["WK"])
            self.assertEqual(report["cases"]["SO"]["previous_preboard_result"], matrix.identity(child))
            self.assertEqual(report["status"], "SSSP_MATRIX_WITH_FAILURES")
            self.assertEqual(set(report["continuation"]["stopped_services"]), {"original.service", "old-so.service"})

            self.args.output = self.root / "duplicate"
            launch.reset_mock()
            with self.assertRaises(FileExistsError):
                matrix.run(self.args)
            launch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
