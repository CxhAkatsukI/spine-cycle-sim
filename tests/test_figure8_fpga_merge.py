"""Disjoint pilots retain every paired attempt and its original evidence."""

import copy
import csv
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from spine_cycle_sim.experiments.evaluation_impact.figure8_fpga import analysis, delivery, merge


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def identity(path):
    return dict(path=str(path), sha256=delivery.checksum(path), bytes=path.stat().st_size)


class Figure8Merge(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="figure8-merge-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.inputs, self.hardware = self.root / "inputs.json", self.root / "hardware.json"
        binding = {}
        for arm in ("spine", "gr"):
            for kind in ("host", "image"):
                path = self.root / (arm + "_" + kind)
                path.write_bytes((arm + kind).encode())
                binding[arm + "_" + kind] = str(path)
        save(self.hardware, binding)
        self.artifacts = {key: identity(Path(value)) for key, value in binding.items()}
        self.plan = []
        for dataset, updates, batches, panel in (
                *((dataset, 4096, 10, "a") for dataset in ("AU", "SU", "WK", "SO", "PK")),
                *(("AU", 131072, batches, "b") for batches in (10, 100, 1000))):
            graph = self.root / f"{dataset}-{updates}.graph"
            graph.write_text("synthetic input identity, not executed\n")
            self.plan.append(dict(name=f"{dataset}_{updates}_b{batches}", dataset=dataset,
                                  updates=updates, batches=batches, panel=panel,
                                  vertices=8, initial_edges=2, graph=identity(graph)))
        save(self.inputs, dict(status="READY", cases=self.plan))
        self.pilot = self.campaign("pilot", self.plan[:3])
        self.remaining = self.campaign("remaining", self.plan[3:])
        self.output = self.root / "combined"

    def campaign(self, name, cases):
        run = self.root / name
        run.mkdir()
        report = dict(status="COMPLETED", boundary="persistent update-only, no propagation",
                      samples_per_arm=1, warmups=0, timing_source="FPGA_MEASURED",
                      metadata_replicas=1, bdf="0000:82:00.1", device=0,
                      inputs=identity(self.inputs), hardware=identity(self.hardware),
                      artifacts=copy.deepcopy(self.artifacts), memory_gib=32, memory_high_gib=30,
                      memory_profile="zfs-arc-clean-half-background5-v1",
                      memory_peak_bytes=(10 + len(cases)) * 2**30, memory_events="oom 0\n", cases=[])
        for index, declared in enumerate(cases):
            case = copy.deepcopy(declared)
            directory = run / case["name"]
            directory.mkdir()
            case.update(status="MEASURED", order=["spine", "gr"], arms={}, speedup=1.0)
            for arm in ("spine", "gr"):
                text = self.log(case, arm)
                paths = {stream: directory / f"{arm}.{stream}.txt" for stream in ("stdout", "stderr")}
                paths["stdout"].write_bytes(text.replace("\n", "\r\n").encode())
                paths["stderr"].write_bytes(b"raw stderr\r\n")
                case["arms"][arm] = dict(status="PASS", started_unix=1234.125 + index,
                                         command=["retained-command", case["name"]],
                                         clock=dict(driver_reported_mhz=[200, 200]),
                                         timing=analysis.timing(text, arm, case),
                                         **{stream: identity(path) for stream, path in paths.items()})
            (directory / "clock-evidence.json").write_bytes(b'{"unchanged": true}\r\n')
            report["cases"].append(case)
        save(run / "results.json", report)
        analysis.write_table(report, run / "fig8_fpga.csv")
        return run

    def log(self, case, arm):
        spine = arm == "spine"
        prefix = "SPINE" if spine else "GRASU"
        total, batches = case["updates"], case["batches"]
        rows = ["SPINE_PERSISTENT_LAYOUT fixed=1 relocation_ns=2 bank_words=100"] if spine else []
        launches = 0
        for batch in range(batches):
            begin, end = batch * total // batches, (batch + 1) * total // batches
            physical = (end - begin + 8191) // 8192
            launches += physical
            rows.append(f"{prefix}_PERSISTENT_BATCH batch={batch} updates={end - begin} "
                        f"begin={begin} end={end} batch_ns=3 update_wall_ns=5" +
                        (f" physical_launches={physical}" if spine else ""))
        setup = (f"bootstrap_ns=20 checked_edges={2 + total} physical_launches={launches}" if spine else
                 "upload_ns=20 pma_mismatches=0 metadata_replicas=1")
        rows.append(f"{prefix}_PERSISTENT_UPDATE status=PASS vertices=8 initial_edges=2 "
                    f"logical_updates={total} batches={batches} {setup} layout_ns=10 "
                    f"batch_ns={3 * batches} update_wall_ns={5 * batches} "
                    f"setup_inclusive_ns={30 + 8 * batches}")
        return "\n".join(rows) + "\n"

    def change(self, run, change):
        report = json.loads((run / "results.json").read_text())
        change(report)
        save(run / "results.json", report)

    def fail(self, report):
        case = report["cases"][0]
        case.update(status="FAILED_RETAINED")
        case.pop("speedup")
        arm = case["arms"]["spine"]
        arm.update(status="FAILED_RETAINED", error="a generic retained execution failure")
        arm.pop("timing")
        report["status"] = "COMPLETED_WITH_FAILURES"

    def edit_spine_log(self, run, transform, *, case_index=0):
        def change(report):
            case = report["cases"][case_index]
            path = run / case["name"] / "spine.stdout.txt"
            text = transform(path.read_text())
            path.write_text(text)
            arm = case["arms"]["spine"]
            arm["stdout"] = identity(path)
            arm["timing"] = analysis.timing(text, "spine", case)
        self.change(run, change)

    def v5_receipts(self):
        for run in (self.pilot, self.remaining):
            def change(report):
                for case in report["cases"]:
                    path = run / case["name"] / "spine.stdout.txt"
                    text = path.read_text().replace(
                        "relocation_ns=2", "graph_uploads=1 arena_allocate_ns=2 live_upload_ns=0")
                    path.write_text(text)
                    case["arms"]["spine"]["stdout"] = identity(path)
            self.change(run, change)

    def v6_receipts(self):
        self.v5_receipts()
        def add_receipt(text):
            vertices = int(analysis.records(text, "SPINE_PERSISTENT_UPDATE")[0]["vertices"])
            return (f"SPINE_MAINT_SPARSE_INIT vertices={vertices} "
                    f"bitmap_words={(vertices + 127) // 128} family_words={(vertices + 3) // 4} "
                    "owner_host_upload=0\n" + text)
        for run in (self.pilot, self.remaining):
            for index in range(len(json.loads((run / "results.json").read_text())["cases"])):
                self.edit_spine_log(run, add_receipt, case_index=index)

    def v7_receipts(self):
        self.v6_receipts()
        for run in (self.pilot, self.remaining):
            for index in range(len(json.loads((run / "results.json").read_text())["cases"])):
                self.edit_spine_log(run, lambda text: text.replace(
                    "owner_host_upload=0", "owner_host_upload=0 host_bound_scratch=0 metadata_uploads=1"),
                    case_index=index)

    def v8_receipts(self):
        self.v7_receipts()
        for run in (self.pilot, self.remaining):
            for index in range(len(json.loads((run / "results.json").read_text())["cases"])):
                self.edit_spine_log(run, lambda text: text.replace(
                    "metadata_uploads=1", "metadata_uploads=1 compact_host_staging=1"), case_index=index)

    def v9_receipts(self):
        self.v8_receipts()
        for run in (self.pilot, self.remaining):
            for index in range(len(json.loads((run / "results.json").read_text())["cases"])):
                self.edit_spine_log(run, lambda text: text.replace(
                    "host_bound_scratch=0", "host_bound_scratch=1 uninitialized_host_backing=1"),
                    case_index=index)

    def combine(self, **kwargs):
        return merge.combine([self.pilot, self.remaining], self.output, **kwargs)

    def test_pilot_three_remaining_five_retains_bytes_timestamps_and_order(self):
        before = {path: (path.read_bytes(), path.stat().st_mtime_ns)
                  for run in (self.pilot, self.remaining) for path in run.rglob("*") if path.is_file()}
        report = self.combine(repair="fixed-carry-v3")
        self.assertEqual(report["persistent_layout"], "fixed-v3")
        self.assertEqual(report["repair"], "fixed-carry-v3")
        self.assertEqual(report["status"], "COMPLETED")
        self.assertEqual([case["name"] for case in report["cases"]], [case["name"] for case in self.plan])
        self.assertEqual(report["memory_peak_bytes"], 15 * 2**30)
        for index, run in enumerate((self.pilot, self.remaining)):
            original = json.loads((run / "results.json").read_text())
            for case in original["cases"]:
                self.assertEqual(case, next(c for c in report["cases"] if c["name"] == case["name"]))
            for path in run.rglob("*"):
                if not path.is_file():
                    continue
                relative = path.relative_to(run)
                target = (self.output / "source_campaigns" / f"{index:02d}" / relative
                          if len(relative.parts) == 1 else self.output / relative)
                self.assertEqual((target.read_bytes(), target.stat().st_mtime_ns), before[path])
                self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before[path])
        with (self.output / "fig8_fpga.csv").open(newline="") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(len(rows), 8)
        self.assertEqual(rows[5]["spine_physical_launches"], "20")

    def test_case_order_comes_from_inputs_not_source_argument_order(self):
        self.plan.reverse()
        save(self.inputs, dict(status="READY", cases=self.plan))
        order = {case["name"]: index for index, case in enumerate(self.plan)}
        def change(report):
            report["inputs"] = identity(self.inputs)
            report["cases"].sort(key=lambda case: order[case["name"]])
        for run in (self.pilot, self.remaining):
            self.change(run, change)
        report = merge.combine([self.remaining, self.pilot], self.output)
        self.assertEqual([case["name"] for case in report["cases"]], list(order))

    def test_duplicate_failed_case_is_not_silently_selected(self):
        duplicate = self.campaign("duplicate", self.plan[:1])
        self.change(duplicate, self.fail)
        with self.assertRaisesRegex(ValueError, "duplicate case"):
            merge.combine([self.pilot, self.remaining, duplicate], self.output)
        self.assertFalse(self.output.exists())

    def test_missing_case_is_not_omitted(self):
        shortened = self.campaign("shortened", self.plan[3:-1])
        with self.assertRaisesRegex(ValueError, "missing declared cases"):
            merge.combine([self.pilot, shortened], self.output)

    def test_configuration_mismatch_rejected_before_output(self):
        original = (self.remaining / "results.json").read_bytes()
        changes = {"samples_per_arm": 2, "warmups": 1, "metadata_replicas": 4,
                   "memory_gib": 24, "memory_high_gib": 22, "memory_profile": "different",
                   "bdf": "0000:c1:00.1", "device": 1, "boundary": "different",
                   "timing_source": "SIMULATED"}
        for key, value in changes.items():
            with self.subTest(key=key):
                (self.remaining / "results.json").write_bytes(original)
                self.change(self.remaining, lambda report: report.update({key: value}))
                with self.assertRaises(ValueError):
                    self.combine()
                self.assertFalse(self.output.exists())

    def test_artifacts_and_input_identity_must_match(self):
        original = (self.remaining / "results.json").read_bytes()
        for field in ("artifacts", "hardware", "inputs"):
            with self.subTest(field=field):
                (self.remaining / "results.json").write_bytes(original)
                def change(report):
                    receipt = report[field]["spine_host"] if field == "artifacts" else report[field]
                    receipt["sha256"] = "0" * 64
                self.change(self.remaining, change)
                with self.assertRaises(ValueError):
                    self.combine()
        (self.remaining / "results.json").write_bytes(original)
        Path(self.artifacts["spine_host"]["path"]).write_bytes(b"changed host")
        with self.assertRaisesRegex(ValueError, "changed receipt"):
            self.combine()

    def test_raw_log_tampering_rejected_even_for_failed_arm(self):
        self.change(self.pilot, self.fail)
        path = self.pilot / self.plan[0]["name"] / "spine.stderr.txt"
        path.write_bytes(b"altered failure evidence")
        with self.assertRaisesRegex(ValueError, "changed receipt"):
            self.combine()

    def test_failed_prelaunch_without_logs_remains_failed(self):
        def change(report):
            self.fail(report)
            arm = report["cases"][0]["arms"]["spine"]
            for stream in ("stdout", "stderr"):
                Path(arm.pop(stream)["path"]).unlink()
        self.change(self.pilot, change)
        report = self.combine(repair="fixed-carry-v3")
        self.assertEqual(report["status"], "COMPLETED_WITH_FAILURES")
        self.assertNotIn("speedup", report["cases"][0])
        self.assertEqual(report["cases"][0]["arms"]["spine"]["status"], "FAILED_RETAINED")
        with (self.output / "fig8_fpga.csv").open(newline="") as stream:
            row = next(csv.DictReader(stream))
        self.assertEqual(row["speedup_gr_over_spine"], "")
        self.assertIn("generic retained", row["spine_error"])

    def test_clock_mismatch_retained_without_speedup(self):
        def change(report):
            case = report["cases"][0]
            case["arms"]["gr"]["clock"]["driver_reported_mhz"] = [199]
            case.update(status="CLOCK_MISMATCH", error="clock mismatch")
            case.pop("speedup")
            report["status"] = "COMPLETED_WITH_FAILURES"
        self.change(self.pilot, change)
        report = self.combine()
        self.assertEqual(report["cases"][0]["status"], "CLOCK_MISMATCH")
        self.assertNotIn("speedup", report["cases"][0])

    def test_repair_requires_raw_fixed_layout_and_physical_counts(self):
        original = (self.pilot / "results.json").read_bytes()
        path = self.pilot / self.plan[0]["name"] / "spine.stdout.txt"
        raw = path.read_bytes()
        transforms = (lambda text: text.replace("fixed=1", "fixed=0"),
                      lambda text: re.sub(r" physical_launches=\d+", "", text),
                      lambda text: text.replace("begin=0", "begin=1"))
        for transform in transforms:
            with self.subTest(transform=transform):
                (self.pilot / "results.json").write_bytes(original)
                path.write_bytes(raw)
                self.edit_spine_log(self.pilot, transform)
                with self.assertRaises(ValueError):
                    self.combine(repair="fixed-carry-v3")
                self.assertFalse(self.output.exists())

    def test_output_cannot_replace_or_modify_source_campaign(self):
        with self.assertRaises(ValueError):
            merge.combine([self.pilot, self.remaining], self.pilot)
        with self.assertRaises(ValueError):
            merge.combine([self.pilot, self.remaining], self.pilot / "nested")
        self.assertFalse((self.pilot / "nested").exists())

    def test_cli_and_delivery_without_optional_setup_failure(self):
        result = subprocess.run(
            [sys.executable, "-B", "-m", merge.__name__, "--run", str(self.pilot),
             "--run", str(self.remaining), "--output", str(self.output),
             "--repair", "fixed-carry-v4"], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        archive = self.root / "host-sources.tar.gz"
        archive.write_bytes(b"synthetic archived host sources")
        target = self.root / "delivery"
        args = SimpleNamespace(run=self.output, output=target, inputs=self.inputs,
                               hardware=self.hardware, host_sources=archive)
        with mock.patch.object(delivery.render, "render"):
            delivery.export(args)
        text = (target / "README.md").read_text()
        for expected in ("8/8 complete pairs", "fixed-v4", "L10", "MAINT-only", "one active record",
                         "32 GiB", "30 GiB", "Source 1", "Source 2"):
            self.assertIn(expected, text)
        for obsolete in ("setup_failure_card1/", "November 7, 2026", "overflow during PK", "24 GiB hard"):
            self.assertNotIn(obsolete, text)
        self.assertFalse((target / "setup_failure_card1").exists())
        manifest = json.loads((target / "manifest.json").read_text())
        self.assertEqual((manifest["measured_pairs"], manifest["attempted_pairs"]), (8, 8))
        self.assertEqual(len(manifest["source_campaigns"]), 2)
        report = json.loads((self.output / "results.json").read_text())
        self.assertEqual(report["bootstrap_min_level"], 10)
        self.assertEqual(report["active_buffer_records"], 1)
        self.assertEqual(report["physical_limit"], 8192)

    def test_optional_setup_failure_does_not_enter_measured_matrix(self):
        report = self.combine()
        setup = self.root / "setup-failed"
        setup.mkdir()
        (setup / "results.json").write_bytes(b'{"status": "RUNNING"}\n')
        archive = self.root / "hosts.tar.gz"
        archive.write_bytes(b"fixture")
        args = SimpleNamespace(run=self.output, output=self.root / "delivery", inputs=self.inputs,
                               hardware=self.hardware, host_sources=archive, setup_failure=setup)
        with mock.patch.object(delivery.render, "render"):
            delivery.export(args)
        self.assertEqual((args.output / "setup_failure_card1/results.json").read_bytes(),
                         (setup / "results.json").read_bytes())
        self.assertIn("setup_failure_card1/", (args.output / "README.md").read_text())
        text = delivery.readme(report)
        self.assertIn("No fixed-layout", text)
        self.assertNotIn("Native Spine bootstraps at L2", text)

    def test_all_failed_attempts_are_retained_not_relabelled_as_passes(self):
        def change(report):
            for case in report["cases"]:
                case.update(status="FAILED_RETAINED")
                case.pop("speedup")
                for arm in case["arms"].values():
                    arm.update(status="FAILED_RETAINED", error="retained generic failure")
                    arm.pop("timing")
            report["status"] = "COMPLETED_WITH_FAILURES"
        for run in (self.pilot, self.remaining):
            self.change(run, change)
        report = self.combine(repair="fixed-carry-v4")
        self.assertEqual(report["status"], "COMPLETED_WITH_FAILURES")
        self.assertEqual(len(report["cases"]), 8)
        self.assertIn("0/8 complete pairs", delivery.readme(report))
        self.assertIn("8 failed pairs", delivery.readme(report))
        self.assertNotIn("All eight pairs passed", delivery.readme(report))

    def test_v4_does_not_silently_relabel_recorded_v3_configuration(self):
        for run in (self.pilot, self.remaining):
            self.change(run, lambda report: report.update(persistent_layout="fixed-v3"))
        with self.assertRaisesRegex(ValueError, "contradicts recorded"):
            self.combine(repair="fixed-carry-v4")

    def test_v5_cli_and_delivery_use_single_fixed_upload_without_legacy_layout_fields(self):
        self.v5_receipts()
        result = subprocess.run(
            [sys.executable, "-B", "-m", merge.__name__, "--run", str(self.pilot),
             "--run", str(self.remaining), "--output", str(self.output),
             "--repair", "fixed-carry-v5"], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = delivery.checked_report(self.output)
        expected = dict(persistent_layout="fixed-v5", repair="fixed-carry-v5", graph_uploads=1,
                        bootstrap_min_level=10, active_buffer_records=1, physical_limit=8192,
                        active_buffer_policy="maint-only")
        for key, value in expected.items():
            self.assertEqual(report[key], value)
        archive = self.root / "host-sources.tar.gz"
        archive.write_bytes(b"synthetic archived host sources")
        args = SimpleNamespace(run=self.output, output=self.root / "delivery", inputs=self.inputs,
                               hardware=self.hardware, host_sources=archive)
        with mock.patch.object(delivery.render, "render"):
            delivery.export(args)
        text = (args.output / "README.md").read_text()
        for expected in ("8/8 complete pairs", "fixed-v5", "L10", "one active record",
                         "single fixed-arena graph upload", "graph_uploads=1",
                         "not a compact-device upload followed by relocation"):
            self.assertIn(expected, text)
        for case in report["cases"]:
            path = Path(case["arms"]["spine"]["stdout"]["path"])
            self.assertNotIn("relocation_ns", path.read_text())
            self.assertEqual(path.read_bytes(), (args.output / "raw" / case["name"] / path.name).read_bytes())

    def test_v5_checks_single_upload_for_every_successful_raw_case(self):
        self.v5_receipts()
        for run in (self.pilot, self.remaining):
            journal = (run / "results.json").read_bytes()
            cases = json.loads(journal)["cases"]
            for index, case in enumerate(cases):
                path = run / case["name"] / "spine.stdout.txt"
                raw = path.read_bytes()
                for marker in ("graph_uploads=0", "graph_uploads=2", ""):
                    with self.subTest(case=case["name"], marker=marker):
                        self.edit_spine_log(run, lambda text: text.replace("graph_uploads=1", marker),
                                            case_index=index)
                        with self.assertRaisesRegex(ValueError, "graph_uploads=1"):
                            self.combine(repair="fixed-carry-v5")
                        self.assertFalse(self.output.exists())
                        path.write_bytes(raw)
                        (run / "results.json").write_bytes(journal)

    def test_v5_delivery_rechecks_raw_uploads_even_when_journal_receipt_matches(self):
        self.v5_receipts()
        self.combine(repair="fixed-carry-v5")
        self.edit_spine_log(self.output, lambda text: text.replace("graph_uploads=1", "graph_uploads=2"))
        with self.assertRaisesRegex(ValueError, "graph_uploads=1"):
            delivery.checked_report(self.output)

    def test_v5_allocation_and_upload_timers_must_be_nonnegative(self):
        self.v5_receipts()
        journal = (self.pilot / "results.json").read_bytes()
        path = self.pilot / self.plan[0]["name"] / "spine.stdout.txt"
        raw = path.read_bytes()
        for field in ("arena_allocate_ns", "live_upload_ns"):
            for replacement in ("", field + "=-1", field + "=invalid"):
                with self.subTest(field=field, replacement=replacement):
                    self.edit_spine_log(self.pilot,
                                        lambda text: re.sub(field + r"=\d+", replacement, text))
                    with self.assertRaisesRegex(ValueError, field):
                        self.combine(repair="fixed-carry-v5")
                    self.assertFalse(self.output.exists())
                    path.write_bytes(raw)
                    (self.pilot / "results.json").write_bytes(journal)

    def test_v5_failed_arm_does_not_need_successful_single_upload_receipt(self):
        self.v5_receipts()
        self.edit_spine_log(self.pilot, lambda text: text.replace("graph_uploads=1", "graph_uploads=0"))
        self.change(self.pilot, self.fail)
        report = self.combine(repair="fixed-carry-v5")
        self.assertEqual(report["status"], "COMPLETED_WITH_FAILURES")
        self.assertNotIn("speedup", report["cases"][0])
        self.assertIn("1 failed pairs", delivery.readme(report))

    def test_v5_cannot_relabel_v4_or_contradict_recorded_upload_policy(self):
        self.v5_receipts()
        for key, value in (("persistent_layout", "fixed-v4"), ("graph_uploads", 2)):
            with self.subTest(key=key):
                for run in (self.pilot, self.remaining):
                    self.change(run, lambda report: report.update({key: value}))
                with self.assertRaisesRegex(ValueError, "contradicts recorded"):
                    self.combine(repair="fixed-carry-v5")
                for run in (self.pilot, self.remaining):
                    self.change(run, lambda report: report.pop(key))

    def test_mismatched_recorded_graph_upload_policy_is_not_merged(self):
        self.v5_receipts()
        self.change(self.remaining, lambda report: report.update(graph_uploads=1))
        with self.assertRaisesRegex(ValueError, "configuration differs"):
            self.combine(repair="fixed-carry-v5")

    def test_v6_cli_delivery_and_bootstrap_accounting(self):
        self.v6_receipts()
        originals = {case["name"]: copy.deepcopy(case["arms"]["spine"]["timing"])
                     for run in (self.pilot, self.remaining)
                     for case in json.loads((run / "results.json").read_text())["cases"]}
        result = subprocess.run(
            [sys.executable, "-B", "-m", merge.__name__, "--run", str(self.pilot),
             "--run", str(self.remaining), "--output", str(self.output),
             "--repair", "fixed-carry-v6"], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = delivery.checked_report(self.output)
        expected = dict(merge.REPAIRS["fixed-carry-v5"], persistent_layout="fixed-v6",
                        sparse_scratch_init=1, repair="fixed-carry-v6")
        for key, value in expected.items():
            self.assertEqual(report[key], value)
        for case in report["cases"]:
            self.assertEqual(case["arms"]["spine"]["timing"], originals[case["name"]])
        archive = self.root / "hosts.tar.gz"
        archive.write_bytes(b"synthetic sources")
        args = SimpleNamespace(run=self.output, output=self.root / "delivery", inputs=self.inputs,
                               hardware=self.hardware, host_sources=archive)
        with mock.patch.object(delivery.render, "render"):
            delivery.export(args)
        text = (args.output / "README.md").read_text()
        for expected in ("fixed-v6", "L10", "single fixed-arena graph upload", "full device allocation",
                         "reduces initialized ranges", "ceil(V/128)", "ceil(V/4)", "CONTENT_UNDEFINED",
                         "owner_host_upload=0", "lifecycle initializes owner", "per-launch input writes",
                         "charged inside bootstrap_ns"):
            self.assertIn(expected, text)

    def test_v6_requires_sparse_receipt_for_every_successful_case(self):
        self.v6_receipts()
        for run in (self.pilot, self.remaining):
            journal = (run / "results.json").read_bytes()
            for index, case in enumerate(json.loads(journal)["cases"]):
                path = run / case["name"] / "spine.stdout.txt"
                raw = path.read_bytes()
                with self.subTest(case=case["name"]):
                    self.edit_spine_log(run, lambda text: re.sub(r"SPINE_MAINT_SPARSE_INIT[^\n]*\n", "", text),
                                        case_index=index)
                    with self.assertRaisesRegex(ValueError, "SPINE_MAINT_SPARSE_INIT"):
                        self.combine(repair="fixed-carry-v6")
                    self.assertFalse(self.output.exists())
                path.write_bytes(raw)
                (run / "results.json").write_bytes(journal)

    def test_v6_rejects_duplicate_or_inconsistent_sparse_receipts(self):
        self.v6_receipts()
        journal = (self.pilot / "results.json").read_bytes()
        path = self.pilot / self.plan[0]["name"] / "spine.stdout.txt"
        raw = path.read_bytes()
        line = "SPINE_MAINT_SPARSE_INIT vertices=8 bitmap_words=1 family_words=2 owner_host_upload=0"
        replacements = [line + "\n" + line,
                        line.replace("vertices=8 bitmap_words=1 family_words=2",
                                     "vertices=129 bitmap_words=2 family_words=33")]
        for token in ("vertices=8", "bitmap_words=1", "family_words=2", "owner_host_upload=0"):
            replacements.extend((line.replace(token, ""), line.replace(token, token.split("=")[0] + "=-1")))
        replacements.extend((line.replace("bitmap_words=1", "bitmap_words=2"),
                             line.replace("family_words=2", "family_words=3"),
                             line.replace("owner_host_upload=0", "owner_host_upload=1")))
        for replacement in replacements:
            with self.subTest(receipt=replacement):
                self.edit_spine_log(self.pilot, lambda text: text.replace(line, replacement))
                with self.assertRaisesRegex(ValueError, "SPINE_MAINT_SPARSE_INIT"):
                    self.combine(repair="fixed-carry-v6")
                self.assertFalse(self.output.exists())
                path.write_bytes(raw)
                (self.pilot / "results.json").write_bytes(journal)

    def test_v6_sparse_ranges_use_ceiling_division_of_raw_update_vertices(self):
        for vertices in (1, 3, 4, 5, 127, 128, 129, 131072, 131073):
            with self.subTest(vertices=vertices):
                text = (f"SPINE_PERSISTENT_UPDATE vertices={vertices}\n"
                        f"SPINE_MAINT_SPARSE_INIT vertices={vertices} "
                        f"bitmap_words={(vertices + 127) // 128} family_words={(vertices + 3) // 4} "
                        "owner_host_upload=0\n")
                delivery.check_sparse_scratch_init(text)
                if vertices % 128:
                    with self.assertRaises(ValueError):
                        delivery.check_sparse_scratch_init(text.replace(
                            f"bitmap_words={(vertices + 127) // 128}", f"bitmap_words={vertices // 128}"))
                if vertices % 4:
                    with self.assertRaises(ValueError):
                        delivery.check_sparse_scratch_init(text.replace(
                            f"family_words={(vertices + 3) // 4}", f"family_words={vertices // 4}"))

    def test_v6_delivery_rechecks_sparse_receipts(self):
        self.v6_receipts()
        self.combine(repair="fixed-carry-v6")
        self.edit_spine_log(self.output, lambda text: text.replace("owner_host_upload=0", "owner_host_upload=1"))
        with self.assertRaisesRegex(ValueError, "SPINE_MAINT_SPARSE_INIT"):
            delivery.checked_report(self.output)

    def test_v6_retains_failed_attempt_without_sparse_receipt(self):
        self.v6_receipts()
        self.edit_spine_log(self.pilot, lambda text: re.sub(r"SPINE_MAINT_SPARSE_INIT[^\n]*\n", "", text))
        self.change(self.pilot, self.fail)
        report = self.combine(repair="fixed-carry-v6")
        self.assertEqual(report["status"], "COMPLETED_WITH_FAILURES")
        self.assertNotIn("speedup", report["cases"][0])

    def test_v6_requires_v5_single_upload_evidence(self):
        self.v6_receipts()
        self.edit_spine_log(self.pilot, lambda text: text.replace("graph_uploads=1", "graph_uploads=2"))
        with self.assertRaisesRegex(ValueError, "graph_uploads=1"):
            self.combine(repair="fixed-carry-v6")

    def test_v6_does_not_relabel_v5_or_ignore_sparse_policy_mismatch(self):
        self.v6_receipts()
        for run in (self.pilot, self.remaining):
            self.change(run, lambda report: report.update(persistent_layout="fixed-v5"))
        with self.assertRaisesRegex(ValueError, "contradicts recorded"):
            self.combine(repair="fixed-carry-v6")
        for run in (self.pilot, self.remaining):
            self.change(run, lambda report: report.pop("persistent_layout"))
        self.change(self.remaining, lambda report: report.update(sparse_scratch_init=1))
        with self.assertRaisesRegex(ValueError, "configuration differs"):
            self.combine(repair="fixed-carry-v6")
        self.change(self.pilot, lambda report: report.update(sparse_scratch_init=0))
        self.change(self.remaining, lambda report: report.update(sparse_scratch_init=0))
        with self.assertRaisesRegex(ValueError, "contradicts recorded"):
            self.combine(repair="fixed-carry-v6")

    def test_v7_cli_delivery_preserves_raw_logs_and_initialization_timing(self):
        self.v7_receipts()
        originals = {path: (path.read_bytes(), path.stat().st_mtime_ns)
                     for run in (self.pilot, self.remaining) for path in run.rglob("*") if path.is_file()}
        result = subprocess.run(
            [sys.executable, "-B", "-m", merge.__name__, "--run", str(self.pilot),
             "--run", str(self.remaining), "--output", str(self.output),
             "--repair", "fixed-carry-v7"], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = delivery.checked_report(self.output)
        expected = dict(merge.REPAIRS["fixed-carry-v6"], persistent_layout="fixed-v7",
                        host_bound_scratch=0, metadata_uploads=1, repair="fixed-carry-v7")
        for key, value in expected.items():
            self.assertEqual(report[key], value)
        for index, run in enumerate((self.pilot, self.remaining)):
            for path in run.rglob("*"):
                if not path.is_file():
                    continue
                relative = path.relative_to(run)
                target = (self.output / "source_campaigns" / f"{index:02d}" / relative
                          if len(relative.parts) == 1 else self.output / relative)
                self.assertEqual((target.read_bytes(), target.stat().st_mtime_ns), originals[path])
                self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), originals[path])
        for case in report["cases"]:
            path = self.output / case["name"] / "spine.stdout.txt"
            self.assertEqual(case["arms"]["spine"]["timing"], analysis.timing(path.read_text(), "spine", case))
            self.assertEqual(case["arms"]["spine"]["timing"]["bootstrap_ns"], 20)
        archive = self.root / "hosts.tar.gz"
        archive.write_bytes(b"synthetic sources")
        args = SimpleNamespace(run=self.output, output=self.root / "delivery", inputs=self.inputs,
                               hardware=self.hardware, host_sources=archive)
        with mock.patch.object(delivery.render, "render"):
            delivery.export(args)
        text = (args.output / "README.md").read_text()
        for expected in ("fixed-v7", "L10", "single fixed-arena graph upload", "full device allocation",
                         "reduces initialized ranges", "without bound host initialization",
                         "metadata also uses CONTENT_UNDEFINED", "final patched metadata once",
                         "lifecycle has no metadata argument", "host_bound_scratch=0", "metadata_uploads=1",
                         "per-launch input writes remain", "charged inside bootstrap_ns"):
            self.assertIn(expected, text)

    def test_v7_checks_both_new_fields_in_every_successful_case(self):
        self.v7_receipts()
        for run in (self.pilot, self.remaining):
            journal = (run / "results.json").read_bytes()
            for index, case in enumerate(json.loads(journal)["cases"]):
                path = run / case["name"] / "spine.stdout.txt"
                raw = path.read_bytes()
                for field, good, bad in (("host_bound_scratch", "0", "1"), ("metadata_uploads", "1", "0")):
                    for replacement in ("", field + "=" + bad, field + "=2", field + "=-1", field + "=invalid"):
                        with self.subTest(case=case["name"], replacement=replacement, field=field):
                            self.edit_spine_log(run, lambda text: text.replace(field + "=" + good, replacement),
                                                case_index=index)
                            with self.assertRaisesRegex(ValueError, field):
                                self.combine(repair="fixed-carry-v7")
                            self.assertFalse(self.output.exists())
                            path.write_bytes(raw)
                            (run / "results.json").write_bytes(journal)

    def test_v7_delivery_rechecks_new_raw_fields(self):
        self.v7_receipts()
        self.combine(repair="fixed-carry-v7")
        journal = (self.output / "results.json").read_bytes()
        path = self.output / self.plan[0]["name"] / "spine.stdout.txt"
        raw = path.read_bytes()
        for token in ("host_bound_scratch=0", "metadata_uploads=1"):
            with self.subTest(token=token):
                self.edit_spine_log(self.output, lambda text: text.replace(token, ""))
                with self.assertRaisesRegex(ValueError, token.split("=")[0]):
                    delivery.checked_report(self.output)
                path.write_bytes(raw)
                (self.output / "results.json").write_bytes(journal)

    def test_v7_new_fields_must_be_on_the_single_sparse_receipt(self):
        self.v7_receipts()
        journal = (self.pilot / "results.json").read_bytes()
        path = self.pilot / self.plan[0]["name"] / "spine.stdout.txt"
        raw = path.read_bytes()
        text = path.read_text()
        line = next(line for line in text.splitlines() if line.startswith("SPINE_MAINT_SPARSE_INIT "))
        for replacement in (line + "\n" + line,
                            line.replace(" host_bound_scratch=0 metadata_uploads=1", "") +
                            "\nSPINE_HOST_INIT host_bound_scratch=0 metadata_uploads=1"):
            with self.subTest(receipt=replacement):
                self.edit_spine_log(self.pilot, lambda text: text.replace(line, replacement))
                with self.assertRaisesRegex(ValueError, "SPINE_MAINT_SPARSE_INIT"):
                    self.combine(repair="fixed-carry-v7")
                self.assertFalse(self.output.exists())
                path.write_bytes(raw)
                (self.pilot / "results.json").write_bytes(journal)

    def test_v7_inherits_v6_and_v5_raw_checks(self):
        self.v7_receipts()
        journal = (self.pilot / "results.json").read_bytes()
        path = self.pilot / self.plan[0]["name"] / "spine.stdout.txt"
        raw = path.read_bytes()
        for token, replacement in (("graph_uploads=1", "graph_uploads=2"),
                                   ("bitmap_words=1", "bitmap_words=0"),
                                   ("family_words=2", "family_words=0"),
                                   ("owner_host_upload=0", "owner_host_upload=1")):
            with self.subTest(token=token):
                self.edit_spine_log(self.pilot, lambda text: text.replace(token, replacement))
                with self.assertRaises(ValueError):
                    self.combine(repair="fixed-carry-v7")
                self.assertFalse(self.output.exists())
                path.write_bytes(raw)
                (self.pilot / "results.json").write_bytes(journal)

    def test_v7_retains_failed_attempt_without_success_receipts(self):
        self.v7_receipts()
        self.edit_spine_log(self.pilot, lambda text: re.sub(r"SPINE_MAINT_SPARSE_INIT[^\n]*\n", "", text))
        self.change(self.pilot, self.fail)
        report = self.combine(repair="fixed-carry-v7")
        self.assertEqual(report["status"], "COMPLETED_WITH_FAILURES")
        self.assertNotIn("speedup", report["cases"][0])
        self.assertIn("1 failed pairs", delivery.readme(report))
        self.assertNotIn("All eight pairs passed", delivery.readme(report))

    def test_v7_rejects_relabelled_v6_and_contradictory_or_mixed_policy(self):
        self.v7_receipts()
        for key, value in (("persistent_layout", "fixed-v6"), ("host_bound_scratch", 1), ("metadata_uploads", 2)):
            with self.subTest(key=key):
                self.change(self.remaining, lambda report: report.update({key: value}))
                with self.assertRaisesRegex(ValueError, "configuration differs"):
                    self.combine(repair="fixed-carry-v7")
                self.change(self.pilot, lambda report: report.update({key: value}))
                with self.assertRaisesRegex(ValueError, "contradicts recorded"):
                    self.combine(repair="fixed-carry-v7")
                for run in (self.pilot, self.remaining):
                    self.change(run, lambda report: report.pop(key))

    def test_v8_cli_delivery_preserves_evidence_and_initialization_costs(self):
        self.v8_receipts()
        result = subprocess.run(
            [sys.executable, "-B", "-m", merge.__name__, "--run", str(self.pilot),
             "--run", str(self.remaining), "--output", str(self.output),
             "--repair", "fixed-carry-v8"], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = delivery.checked_report(self.output)
        expected = dict(merge.REPAIRS["fixed-carry-v7"], persistent_layout="fixed-v8",
                        compact_host_staging=1, repair="fixed-carry-v8")
        for key, value in expected.items():
            self.assertEqual(report[key], value)
        for index, run in enumerate((self.pilot, self.remaining)):
            original = json.loads((run / "results.json").read_text())
            retained = self.output / "source_campaigns" / f"{index:02d}" / "results.json"
            self.assertEqual(retained.read_bytes(), (run / "results.json").read_bytes())
            for case in original["cases"]:
                self.assertEqual(case, next(c for c in report["cases"] if c["name"] == case["name"]))
                for path in (run / case["name"]).iterdir():
                    target = self.output / case["name"] / path.name
                    self.assertEqual(target.read_bytes(), path.read_bytes())
                    self.assertEqual(target.stat().st_mtime_ns, path.stat().st_mtime_ns)
        archive = self.root / "hosts.tar.gz"
        archive.write_bytes(b"synthetic sources")
        args = SimpleNamespace(run=self.output, output=self.root / "delivery", inputs=self.inputs,
                               hardware=self.hardware, host_sources=archive)
        with mock.patch.object(delivery.render, "render"):
            delivery.export(args)
        text = (args.output / "README.md").read_text()
        for expected in ("fixed-v8", "L10", "single fixed-arena graph upload", "host_bound_scratch=0",
                         "metadata_uploads=1", "compact CPU staging", "without a host owner vector",
                         "full device capacities remain unchanged", "compact_host_staging=1",
                         "Required initialization and per-launch writes remain charged",
                         "bootstrap initialization still inside bootstrap_ns"):
            self.assertIn(expected, text)

    def test_v8_checks_compact_staging_for_every_successful_case(self):
        self.v8_receipts()
        for run in (self.pilot, self.remaining):
            journal = (run / "results.json").read_bytes()
            for index, case in enumerate(json.loads(journal)["cases"]):
                path = run / case["name"] / "spine.stdout.txt"
                raw = path.read_bytes()
                for replacement in ("", "compact_host_staging=0", "compact_host_staging=2",
                                    "compact_host_staging=-1", "compact_host_staging=invalid"):
                    with self.subTest(case=case["name"], marker=replacement):
                        self.edit_spine_log(run, lambda text: text.replace("compact_host_staging=1", replacement),
                                            case_index=index)
                        with self.assertRaisesRegex(ValueError, "compact_host_staging=1"):
                            self.combine(repair="fixed-carry-v8")
                        self.assertFalse(self.output.exists())
                        path.write_bytes(raw)
                        (run / "results.json").write_bytes(journal)

    def test_v8_inherits_checks_and_requires_one_combined_sparse_receipt(self):
        self.v8_receipts()
        journal = (self.pilot / "results.json").read_bytes()
        path = self.pilot / self.plan[0]["name"] / "spine.stdout.txt"
        raw = path.read_bytes()
        line = next(line for line in path.read_text().splitlines()
                    if line.startswith("SPINE_MAINT_SPARSE_INIT "))
        replacements = ((line, line + "\n" + line),
                        (line, line.replace(" compact_host_staging=1", "") +
                         "\nSPINE_HOST_INIT compact_host_staging=1"),
                        ("host_bound_scratch=0", ""), ("metadata_uploads=1", ""),
                        ("graph_uploads=1", "graph_uploads=2"),
                        ("bitmap_words=1", "bitmap_words=0"))
        for token, replacement in replacements:
            with self.subTest(token=token, replacement=replacement):
                self.edit_spine_log(self.pilot, lambda text: text.replace(token, replacement))
                with self.assertRaises(ValueError):
                    self.combine(repair="fixed-carry-v8")
                self.assertFalse(self.output.exists())
                path.write_bytes(raw)
                (self.pilot / "results.json").write_bytes(journal)

    def test_v8_delivery_rechecks_compact_receipt(self):
        self.v8_receipts()
        self.combine(repair="fixed-carry-v8")
        self.edit_spine_log(self.output, lambda text: text.replace("compact_host_staging=1", "compact_host_staging=0"))
        with self.assertRaisesRegex(ValueError, "compact_host_staging=1"):
            delivery.checked_report(self.output)

    def test_v8_retains_failed_attempt_without_success_receipts(self):
        self.v8_receipts()
        self.edit_spine_log(self.pilot, lambda text: re.sub(r"SPINE_MAINT_SPARSE_INIT[^\n]*\n", "", text))
        self.change(self.pilot, self.fail)
        report = self.combine(repair="fixed-carry-v8")
        self.assertEqual(report["status"], "COMPLETED_WITH_FAILURES")
        self.assertNotIn("speedup", report["cases"][0])
        self.assertIn("1 failed pairs", delivery.readme(report))

    def test_v8_rejects_relabelled_v7_and_contradictory_or_mixed_policy(self):
        self.v8_receipts()
        for key, value in (("persistent_layout", "fixed-v7"), ("compact_host_staging", 0)):
            with self.subTest(key=key):
                self.change(self.remaining, lambda report: report.update({key: value}))
                with self.assertRaisesRegex(ValueError, "configuration differs"):
                    self.combine(repair="fixed-carry-v8")
                self.change(self.pilot, lambda report: report.update({key: value}))
                with self.assertRaisesRegex(ValueError, "contradicts recorded"):
                    self.combine(repair="fixed-carry-v8")
                for run in (self.pilot, self.remaining):
                    self.change(run, lambda report: report.pop(key))

    def test_v9_cli_delivery_preserves_evidence_and_charged_initialization(self):
        self.v9_receipts()
        originals = {path: (path.read_bytes(), path.stat().st_mtime_ns)
                     for run in (self.pilot, self.remaining) for path in run.rglob("*") if path.is_file()}
        result = subprocess.run(
            [sys.executable, "-B", "-m", merge.__name__, "--run", str(self.pilot),
             "--run", str(self.remaining), "--output", str(self.output),
             "--repair", "fixed-carry-v9"], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = delivery.checked_report(self.output)
        expected = dict(merge.REPAIRS["fixed-carry-v8"], persistent_layout="fixed-v9",
                        host_bound_scratch=1, uninitialized_host_backing=1, repair="fixed-carry-v9")
        for key, value in expected.items():
            self.assertEqual(report[key], value)
        self.assertEqual([c["name"] for c in report["cases"]], [c["name"] for c in self.plan])
        for index, run in enumerate((self.pilot, self.remaining)):
            for path in run.rglob("*"):
                if not path.is_file():
                    continue
                relative = path.relative_to(run)
                target = (self.output / "source_campaigns" / f"{index:02d}" / relative
                          if len(relative.parts) == 1 else self.output / relative)
                self.assertEqual((target.read_bytes(), target.stat().st_mtime_ns), originals[path])
                self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), originals[path])
        for case in report["cases"]:
            self.assertEqual(case["arms"]["spine"]["timing"]["bootstrap_ns"], 20)
        archive = self.root / "hosts.tar.gz"
        archive.write_bytes(b"synthetic sources")
        args = SimpleNamespace(run=self.output, output=self.root / "delivery", inputs=self.inputs,
                               hardware=self.hardware, host_sources=archive)
        with mock.patch.object(delivery.render, "render"):
            delivery.export(args)
        text = (args.output / "README.md").read_text()
        for expected in ("fixed-v9", "L10", "single fixed-arena graph upload", "full device allocation",
                         "reduces initialized ranges", "aligned, raw nonzeroed host backing",
                         "CONTENT_UNDEFINED", "graph prefix writes remain", "Compact CPU staging",
                         "host-bound metadata is migrated once", "lifecycle has no metadata argument",
                         "host_bound_scratch=1", "metadata_uploads=1", "compact_host_staging=1",
                         "uninitialized_host_backing=1", "single metadata migration stay inside bootstrap_ns",
                         "does not remove device initialization"):
            self.assertIn(expected, text)
        self.assertNotIn("host_bound_scratch=0", text)
        self.assertNotIn("metadata also uses CONTENT_UNDEFINED", text)
        manifest = json.loads((args.output / "manifest.json").read_text())
        self.assertEqual((manifest["persistent_layout"], manifest["measured_pairs"]), ("fixed-v9", 8))

    def test_v9_checks_all_backing_fields_for_every_successful_case(self):
        self.v9_receipts()
        fields = ("host_bound_scratch", "metadata_uploads", "compact_host_staging", "uninitialized_host_backing")
        for run in (self.pilot, self.remaining):
            journal = (run / "results.json").read_bytes()
            for index, case in enumerate(json.loads(journal)["cases"]):
                path = run / case["name"] / "spine.stdout.txt"
                raw = path.read_bytes()
                for field in fields:
                    for replacement in ("", field + "=0", field + "=2", field + "=-1", field + "=invalid"):
                        with self.subTest(case=case["name"], field=field, marker=replacement):
                            self.edit_spine_log(run, lambda text: text.replace(field + "=1", replacement),
                                                case_index=index)
                            with self.assertRaisesRegex(ValueError, field + "=1"):
                                self.combine(repair="fixed-carry-v9")
                            self.assertFalse(self.output.exists())
                            path.write_bytes(raw)
                            (run / "results.json").write_bytes(journal)

    def test_v9_inherits_checks_and_requires_one_combined_sparse_receipt(self):
        self.v9_receipts()
        journal = (self.pilot / "results.json").read_bytes()
        path = self.pilot / self.plan[0]["name"] / "spine.stdout.txt"
        raw = path.read_bytes()
        line = next(line for line in path.read_text().splitlines()
                    if line.startswith("SPINE_MAINT_SPARSE_INIT "))
        replacements = [(line, line + "\n" + line),
                        ("graph_uploads=1", "graph_uploads=2"),
                        ("bitmap_words=1", "bitmap_words=0"),
                        ("family_words=2", "family_words=0"),
                        ("owner_host_upload=0", "owner_host_upload=1")]
        for field in ("host_bound_scratch", "metadata_uploads", "compact_host_staging", "uninitialized_host_backing"):
            token = field + "=1"
            replacements.extend(((line, line.replace(token, "") + "\nSPINE_HOST_INIT " + token),
                                 (line, line + " " + token)))
        for token, replacement in replacements:
            with self.subTest(token=token, replacement=replacement):
                self.edit_spine_log(self.pilot, lambda text: text.replace(token, replacement))
                with self.assertRaises(ValueError):
                    self.combine(repair="fixed-carry-v9")
                self.assertFalse(self.output.exists())
                path.write_bytes(raw)
                (self.pilot / "results.json").write_bytes(journal)

    def test_v9_delivery_rechecks_all_backing_fields(self):
        self.v9_receipts()
        self.combine(repair="fixed-carry-v9")
        journal = (self.output / "results.json").read_bytes()
        path = self.output / self.plan[0]["name"] / "spine.stdout.txt"
        raw = path.read_bytes()
        for field in ("host_bound_scratch", "metadata_uploads", "compact_host_staging", "uninitialized_host_backing"):
            with self.subTest(field=field):
                self.edit_spine_log(self.output, lambda text: text.replace(field + "=1", field + "=0"))
                with self.assertRaisesRegex(ValueError, field + "=1"):
                    delivery.checked_report(self.output)
                path.write_bytes(raw)
                (self.output / "results.json").write_bytes(journal)

    def test_v9_retains_failed_attempt_without_success_receipts(self):
        self.v9_receipts()
        self.edit_spine_log(self.pilot, lambda text: re.sub(r"SPINE_MAINT_SPARSE_INIT[^\n]*\n", "", text))
        self.change(self.pilot, self.fail)
        report = self.combine(repair="fixed-carry-v9")
        self.assertEqual(report["status"], "COMPLETED_WITH_FAILURES")
        self.assertNotIn("speedup", report["cases"][0])
        self.assertIn("1 failed pairs", delivery.readme(report))
        self.assertNotIn("All eight pairs passed", delivery.readme(report))

    def test_v9_rejects_relabelled_v8_and_contradictory_or_mixed_policy(self):
        self.v9_receipts()
        for key, value in (("persistent_layout", "fixed-v8"), ("host_bound_scratch", 0),
                           ("uninitialized_host_backing", 0)):
            with self.subTest(key=key):
                self.change(self.remaining, lambda report: report.update({key: value}))
                with self.assertRaises(ValueError):
                    self.combine(repair="fixed-carry-v9")
                self.change(self.pilot, lambda report: report.update({key: value}))
                with self.assertRaises(ValueError):
                    self.combine(repair="fixed-carry-v9")
                self.assertFalse(self.output.exists())
                for run in (self.pilot, self.remaining):
                    self.change(run, lambda report: report.pop(key))

    def test_unrecorded_high_watermark_is_not_claimed_as_observed(self):
        for run in (self.pilot, self.remaining):
            self.change(run, lambda report: report.pop("memory_high_gib"))
        text = delivery.readme(self.combine(repair="fixed-carry-v4"))
        self.assertIn("32 GiB launch profile normally uses a 30 GiB", text)
        self.assertIn("memory.high was not recorded", text)


if __name__ == "__main__":
    unittest.main()
