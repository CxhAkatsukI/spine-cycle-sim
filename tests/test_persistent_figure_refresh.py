"""Persistent figures require matched identity, exact batch widths and explicit setup assumptions."""

import json
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest

from spine_cycle_sim.experiments.evaluation_impact.figure_refresh import analysis
from spine_cycle_sim.experiments.evaluation_impact.figure_refresh import persistent_study


class PersistentFigureRefreshTests(unittest.TestCase):
    def test_preload_policy_rejects_invalid_values_before_running(self):
        for value in (True, False, 0, 1, 11, 4.0, "4", None):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "integer in L2-L10"):
                    persistent_study.run(None, None, 0, 4096,
                                         preload_minimum_level=value)

    def test_host_single_pass_identity_and_conserved_payload(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "stdout"
            step = dict(exit_code=0, timed_out=False, stdout=str(output))
            row = dict(arm="gr", repeat=0, updates=5, batches=2, nanoseconds=100,
                initial_nanoseconds=90, batch_nanoseconds=10, initial_h2d_bytes=64,
                update_h2d_bytes=40, batch_h2d_bytes=[16, 24],
                bootstrap_complete=True, batch_preparation_complete=True)

            def parse():
                output.write_text("HOST_RESULT " + json.dumps(row) + "\nREFRESH_COMPLETE\n")
                return analysis.persistent_host(step, arm="gr", updates=5, batch_count=2)

            self.assertEqual(parse(), row)
            row["arm"] = "spine"
            with self.assertRaisesRegex(ValueError, "identity"):
                parse()
            row["arm"] = "gr"
            row["batch_nanoseconds"] = 11
            with self.assertRaisesRegex(ValueError, "time ledger"):
                parse()
            row["batch_nanoseconds"] = 10
            row["batch_h2d_bytes"] = [24, 16]
            with self.assertRaisesRegex(ValueError, "transfer ledger"):
                parse()
            row["batch_h2d_bytes"] = [16, 24]
            row["bootstrap_complete"] = False
            with self.assertRaisesRegex(ValueError, "incomplete"):
                parse()

    def test_persistent_host_spine_wire_width_is_sixteen(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "stdout"
            row = dict(arm="spine", repeat=0, updates=5, batches=2, nanoseconds=100,
                initial_nanoseconds=90, batch_nanoseconds=10, initial_h2d_bytes=64,
                update_h2d_bytes=80, batch_h2d_bytes=[32, 48],
                bootstrap_complete=True, batch_preparation_complete=True)
            output.write_text("HOST_RESULT " + json.dumps(row) + "\nREFRESH_COMPLETE\n")
            step = dict(exit_code=0, timed_out=False, stdout=str(output))
            self.assertEqual(analysis.persistent_host(step, arm="spine", updates=5, batch_count=2), row)

    def test_setup_includes_initial_upload_once_and_launch_per_batch(self):
        arms = {arm: dict(host=dict(nanoseconds=1000, initial_h2d_bytes=12000,
                                   update_h2d_bytes=0), device=dict(cycles=150))
                for arm in ("spine", "gr")}
        report = analysis.persistent_comparison(arms, updates=10, batch_count=10)
        self.assertAlmostEqual(report["spine"]["setup_inclusive_seconds"], 103e-6)
        self.assertEqual(report["speedup_gr_over_spine"], 1)
        self.assertEqual(report["host_samples_per_arm"], 1)
        self.assertFalse(report["baseline_admitted"])
        arms["gr"]["host"]["nanoseconds"] *= 2
        report = analysis.persistent_comparison(arms, updates=10, batch_count=10)
        self.assertGreater(report["speedup_gr_over_spine"], 1)

    def test_wrong_arm_cannot_pass_the_persistent_device_gate(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "stdout"
            total = dict(arm="gr", cycles=3, read_bytes=128, write_bytes=0,
                correctness=True, ledger_closed=True, physical_image_checked=True)
            rows = [dict(batch=i, updates=1, cycles=i + 1, read_bytes=64, write_bytes=0)
                    for i in range(2)]
            output.write_text("".join("WARM_BATCH " + json.dumps(r) + "\n" for r in rows) +
                              "WARM_RESULT " + json.dumps(total) + "\nREFRESH_COMPLETE\n")
            step = dict(exit_code=0, timed_out=False, stdout=str(output))
            self.assertEqual(analysis.persistent_device(step, arm="gr", updates=2, batch_count=2)["device"], total)
            with self.assertRaisesRegex(ValueError, "match the arm"):
                analysis.persistent_device(step, arm="spine", updates=2, batch_count=2)


class PersistentExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        source = Path(__file__).resolve().parents[1] / (
            "docs/experiments/comparisons/grasu_regraph_stage_validation/"
            "evaluation_impact/figure7_11_preview_20261105/export_persistent.py")
        spec = importlib.util.spec_from_file_location("persistent_export", source)
        self.export = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.export)

        def pin(path, content):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
            data = path.read_bytes()
            return dict(path=str(path), bytes=len(data), sha256=hashlib.sha256(data).hexdigest())

        inputs = {key: str(self.root / key) for key in ("graph", "updates")}
        self.report = dict(status=self.export.STATUS, cpu=12, pins=[], rows={}, steps={})
        self.report["pins"] = [pin(Path(value), "fixture") for value in inputs.values()]
        self.report["pins"].append(pin(self.root / "cross_dataset/au/manifest.json", json.dumps(inputs)))
        for arm in ("spine", "gr"):
            name = "trace_" + arm
            widths = [(i + 1) * 4096 // 10 - i * 4096 // 10 for i in range(10)]
            batches = [dict(batch=i, updates=n, cycles=1, read_bytes=64, write_bytes=0)
                       for i, n in enumerate(widths)]
            device = dict(arm=arm, cycles=10, read_bytes=640, write_bytes=0,
                          correctness=True, ledger_closed=True, physical_image_checked=True)
            host = dict(arm=arm, repeat=0, updates=4096, batches=10, nanoseconds=100,
                        initial_nanoseconds=90, batch_nanoseconds=10, initial_h2d_bytes=64,
                        update_h2d_bytes=4096 * (16 if arm == "spine" else 8),
                        batch_h2d_bytes=[n * (16 if arm == "spine" else 8) for n in widths],
                        bootstrap_complete=True, batch_preparation_complete=True)
            stdout = pin(self.root / arm / "stdout", "".join(
                "WARM_BATCH " + json.dumps(row) + "\n" for row in batches) +
                "WARM_RESULT " + json.dumps(device) + "\nREFRESH_COMPLETE\n")
            host_stdout = pin(self.root / arm / "host_stdout",
                              "HOST_RESULT " + json.dumps(host) + "\nREFRESH_COMPLETE\n")
            self.report["steps"][name] = dict(exit_code=0, timed_out=False, stdout=stdout["path"])
            self.report["steps"][name + "_host"] = dict(exit_code=0, timed_out=False, stdout=host_stdout["path"])
            self.report["rows"][name] = dict(device=device, batches=batches, host=host,
                stdout=stdout, config=pin(self.root / arm / "config.json", json.dumps(inputs)),
                backend=pin(self.root / arm / "backend.json", "{}"),
                host_evidence=dict(stdout=host_stdout,
                    config=pin(self.root / arm / "host_config.json", json.dumps(inputs))))
        self.report["comparisons"] = dict(trace=analysis.persistent_comparison(
            {arm: self.report["rows"]["trace_" + arm] for arm in ("spine", "gr")},
            updates=4096, batch_count=10))
        self.path = self.root / "results.json"

    def collect(self, dataset="AU"):
        self.path.write_text(json.dumps(self.report))
        return self.export.collect(dataset, self.path)

    def test_replays_the_raw_logs_and_retains_receipts(self):
        row, members = self.collect()
        self.assertEqual(row["dataset"], "AU")
        self.assertFalse(row["baseline_admitted"])
        self.assertIn("AU/results.json", members)
        self.assertIn("AU/spine/stdout", members)

    def test_wrong_dataset_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "dataset"):
            self.collect("SU")

    def test_changed_receipt_is_rejected(self):
        Path(self.report["rows"]["trace_spine"]["backend"]["path"]).write_text("changed")
        with self.assertRaisesRegex(ValueError, "changed persistent receipt"):
            self.collect()

    def test_changed_comparison_is_rejected(self):
        self.report["comparisons"]["trace"]["speedup_gr_over_spine"] *= 2
        with self.assertRaisesRegex(ValueError, "setup formula"):
            self.collect()

    def test_wrong_batch_count_is_rejected(self):
        self.report["comparisons"]["trace"]["batches"] = 1
        with self.assertRaisesRegex(ValueError, "matched persistent-update"):
            self.collect()

    def test_fpga_admission_cannot_be_inferred_from_host_prediction(self):
        self.report["comparisons"]["trace"]["baseline_admitted"] = True
        with self.assertRaisesRegex(ValueError, "matched persistent-update"):
            self.collect()

    def test_sensitivity_cannot_relabel_ten_batch_cross_dataset_run(self):
        self.path.write_text(json.dumps(self.report))
        with self.assertRaisesRegex(ValueError, "matched persistent-update"):
            self.export.collect("AU", self.path, updates=131072, batches=100, sensitivity=True)


if __name__ == "__main__":
    unittest.main()
