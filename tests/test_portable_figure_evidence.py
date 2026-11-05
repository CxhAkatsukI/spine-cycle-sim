"""Portable predictions must retain failures and cannot mix CPU cohorts."""

import copy
import csv
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.evaluation_impact.figure_refresh import analysis
from spine_cycle_sim.experiments.evaluation_impact.figure_refresh import portable_evidence as evidence
from spine_cycle_sim.experiments.evaluation_impact.r_credits.freeze import pin


class PortableEvidenceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

        def put(name, content):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content if isinstance(content, str) else json.dumps(content))
            return pin(path)

        self.put = put
        inputs = {key: put(key, key) for key in ("graph", "updates")}
        self.original = dict(dataset="sx_askubuntu", batch_count=10,
                             **{k: v["path"] for k, v in inputs.items()})
        source = put("original.json", self.original)
        self.manifest = dict(self.original, input_relocation=dict(
            source_manifest=source, inputs=inputs, semantics="only graph/updates paths changed"))
        self.manifest_pin = put("au/manifest.json", self.manifest)
        numerical = [put(name, "fixture") for name in ("cpp/model.cpp",
            "configs/memory/HBM2_1ch_x128_summary_only.ini",
            "dram/libdramsim3.so", "dram/src/dramsim3.h", "compiler", "sst")]
        self.report = dict(status=evidence.STATUS, cpu=7, git_head="frozen-source",
            compiler_version="fixed compiler", pins=[*inputs.values(), self.manifest_pin, *numerical],
            environment=dict(host="host-a", cpu_model="CPU-a", platform="Linux",
                paths={key: str(self.root / key) for key in ("compiler", "sst")}),
            rows={}, steps={}, comparisons={})
        self.report["environment"]["paths"].update(sst_include="/sst/include", dram="/dram")
        self.report["steps"]["plugin"] = dict(cwd=str(self.root),
            command=["/usr/bin/c++", "-O3", str(self.root / "cpp/model.cpp")],
            stdout=self.put("plugin.stdout", "")["path"],
            stderr=self.put("plugin.stderr", "")["path"])
        self.report["build_pins"] = [put("build/compile_commands.json", [dict(
            file=str(self.root / "cpp/model.cpp"),
            output=str(self.root / "build/cpp/CMakeFiles/spine_cycle_core.dir/model.o"),
            command="/usr/bin/c++ -O3 " + str(self.root / "cpp/model.cpp"))])]
        for label, updates, batches in (("smoke", 3, 3), ("trace", 4096, 10)):
            for arm in ("spine", "gr"):
                name = label + "_" + arm
                widths = [(i + 1) * updates // batches - i * updates // batches for i in range(batches)]
                records = [dict(batch=i, updates=n, cycles=1, read_bytes=64, write_bytes=0)
                           for i, n in enumerate(widths)]
                device = dict(arm=arm, cycles=batches, read_bytes=64 * batches, write_bytes=0,
                              correctness=True, ledger_closed=True, physical_image_checked=True)
                stdout = put(name + "/stdout", "".join("WARM_BATCH " + json.dumps(r) + "\n" for r in records)
                    + "WARM_RESULT " + json.dumps(device) + "\nREFRESH_COMPLETE\n")
                stderr = put(name + "/stderr", "")
                width = 16 if arm == "spine" else 8
                host = dict(arm=arm, repeat=0, updates=updates, batches=batches, nanoseconds=100,
                    initial_nanoseconds=90, batch_nanoseconds=10, initial_h2d_bytes=64,
                    update_h2d_bytes=updates * width, batch_h2d_bytes=[n * width for n in widths],
                    bootstrap_complete=True, batch_preparation_complete=True)
                host_stdout = put(name + "/host_stdout", "HOST_RESULT " + json.dumps(host) + "\nREFRESH_COMPLETE\n")
                config = dict(graph=inputs["graph"]["path"], updates=inputs["updates"]["path"], batches=batches)
                self.report["rows"][name] = dict(device=device, batches=records, host=host,
                    stdout=stdout, config=put(name + "/config.json", config),
                    backend=put(name + "/backend.json", {}),
                    host_evidence=dict(stdout=host_stdout, config=put(name + "/host.json", config)))
                self.report["steps"][name] = dict(exit_code=0, timed_out=False,
                    stdout=stdout["path"], stderr=stderr["path"])
                self.report["steps"][name + "_host"] = dict(exit_code=0, timed_out=False,
                    stdout=host_stdout["path"], stderr=stderr["path"])
            self.report["comparisons"][label] = analysis.persistent_comparison(
                {arm: self.report["rows"][label + "_" + arm] for arm in ("spine", "gr")},
                updates=updates, batch_count=batches)
        self.path = self.root / "results.json"
        self.save()
        self.reference = evidence.freeze_reference(self.path)

    def save(self):
        self.path.write_text(json.dumps(self.report))

    def collect(self):
        self.save()
        return evidence.collect("AU", self.path, self.reference)

    def test_complete_case_checks_smoke_and_keeps_raw_receipts(self):
        row, members, cohort = self.collect()
        self.assertEqual(row["status"], evidence.STATUS)
        self.assertGreater(row["speedup_gr_over_spine"], 0)
        self.assertFalse(row["baseline_admitted"])
        self.assertIn("AU/raw/trace_gr.stdout.txt", members)
        self.assertEqual(cohort["host"], "host-a")

    def test_failed_case_is_not_given_a_speedup(self):
        self.report.update(status="FAILED_RETAINED", error="capacity-safe free target unavailable")
        del self.report["comparisons"]["trace"]
        row, members, _ = self.collect()
        self.assertIsNone(row["speedup_gr_over_spine"])
        self.assertIn("capacity", row["error"])
        self.assertIn("AU/raw/trace_spine.stderr.txt", members)

    def test_failure_cannot_retain_a_successful_trace_comparison(self):
        self.report.update(status="FAILED_RETAINED", error="failed")
        with self.assertRaisesRegex(ValueError, "not a trace comparison"):
            self.collect()

    def test_changed_smoke_is_rejected(self):
        self.reference["smoke"]["spine"]["device"]["cycles"] += 1
        with self.assertRaisesRegex(ValueError, "smoke device"):
            self.collect()

    def test_changed_numerical_source_identity_is_rejected(self):
        self.reference["numerical_pins"]["cpp/model.cpp"]["sha256"] = "changed"
        with self.assertRaisesRegex(ValueError, "numerical source"):
            self.collect()

    def test_explicit_preload_policy_is_part_of_the_cohort(self):
        self.report["spine_preload_minimum_level"] = 4
        for row in self.report["rows"].values():
            for identity in (row["config"], row["host_evidence"]["config"]):
                config = json.loads(Path(identity["path"]).read_text())
                config["preload_minimum_level"] = 4
                identity.update(self.put(Path(identity["path"]).relative_to(self.root), config))
        self.save()
        reference = evidence.freeze_reference(self.path)
        row, _, cohort = evidence.collect("AU", self.path, reference)
        self.assertEqual(row["spine_preload_minimum_level"], 4)
        self.assertEqual(cohort["spine_preload_minimum_level"], 4)
        self.assertNotEqual(cohort, evidence.cohort_key(dict(self.report,
            spine_preload_minimum_level=2, rows={})))
        with self.assertRaisesRegex(ValueError, "preload policy differs"):
            evidence.collect("AU", self.path, self.reference)

    def test_host_config_cannot_silently_use_a_different_preload_policy(self):
        row = self.report["rows"]["trace_spine"]
        config = json.loads(Path(row["host_evidence"]["config"]["path"]).read_text())
        config["preload_minimum_level"] = 4
        row["host_evidence"]["config"] = self.put("trace_spine/host.json", config)
        with self.assertRaisesRegex(ValueError, "configuration differs"):
            self.collect()

    def test_invalid_preload_policy_is_rejected(self):
        for level in (True, 1, 11, 4.0, "4"):
            with self.subTest(level=level), self.assertRaisesRegex(ValueError, "integer preload"):
                evidence.preload_policy(dict(self.report, spine_preload_minimum_level=level))

    def test_expanded_uncompiled_test_inventory_is_explicitly_retained(self):
        self.report["pins"].append(self.put("cpp/tests/other.cpp", "test only"))
        row, _, _ = self.collect()
        self.assertEqual(row["expanded_test_files"], 1)

    def test_changed_source_file_is_rejected_even_with_unchanged_report(self):
        (self.root / "cpp/model.cpp").write_text("modified after measurement")
        with self.assertRaisesRegex(ValueError, "changed portable receipt"):
            self.collect()

    def test_changed_build_flags_are_rejected_even_if_sources_match(self):
        self.report["steps"]["plugin"]["command"].append("-DCHANGED_MODEL")
        with self.assertRaisesRegex(ValueError, "compiled numerical"):
            self.collect()

    def test_new_non_test_source_is_rejected(self):
        self.report["pins"].append(self.put("cpp/src/new.cpp", "new source"))
        with self.assertRaisesRegex(ValueError, "inventory expansion"):
            self.collect()

    def test_changed_host_raw_log_is_rejected(self):
        Path(self.report["rows"]["trace_gr"]["host_evidence"]["stdout"]["path"]).write_text("changed")
        with self.assertRaisesRegex(ValueError, "changed portable receipt"):
            self.collect()

    def test_changed_comparison_is_rejected(self):
        self.report["comparisons"]["trace"]["speedup_gr_over_spine"] *= 2
        with self.assertRaisesRegex(ValueError, "setup formula"):
            self.collect()

    def test_relocation_may_not_change_batch_semantics(self):
        self.manifest["batch_count"] = 9
        changed = self.put("au/manifest.json", self.manifest)
        self.report["pins"] = [changed if p == self.manifest_pin else p for p in self.report["pins"]]
        with self.assertRaisesRegex(ValueError, "relocation changed"):
            self.collect()

    def test_export_requires_all_five_statuses(self):
        reference = self.put("reference.json", self.reference)
        with self.assertRaisesRegex(ValueError, "all five"):
            evidence.export({"AU": self.path}, Path(reference["path"]), self.root / "export")

    def test_export_rejects_mixed_hosts(self):
        reference = self.put("reference.json", self.reference)
        key = evidence.cohort_key(self.report)
        other = dict(key, host="host-b")
        values = [(dict(dataset=ds, status=evidence.STATUS), {}, copy.deepcopy(key)) for ds in evidence.DATASETS]
        values[1] = (values[1][0], {}, other)
        with patch.object(evidence, "collect", side_effect=values):
            with self.assertRaisesRegex(ValueError, "mixed host"):
                evidence.export({ds: self.path for ds in evidence.DATASETS},
                                Path(reference["path"]), self.root / "export")

    def test_generalized_collection_still_checks_actual_batch_scope(self):
        with self.assertRaisesRegex(ValueError, "mutation count mismatch"):
            evidence.collect("AU", self.path, self.reference, updates=131072, batches=10)

    def sweep(self, *, other_cpu=False, changed_inputs=False, failure=False):
        reference = self.put("reference.json", self.reference)
        key = evidence.cohort_key(self.report)
        cohort = self.put("dataset-scope.json", dict(status="COMPLETE", cohort=key,
                                                    evidence="prediction only"))
        values = []
        for count in (10, 100, 1000):
            manifest = copy.deepcopy(self.manifest)
            if changed_inputs and count == 1000:
                manifest["input_relocation"]["inputs"]["updates"]["sha256"] = "different"
            row = dict(dataset="AU", updates=131072, batches=count,
                       status="FAILED_RETAINED" if failure and count == 1000 else evidence.STATUS)
            values.append((row, {f"AU_b{count}/input_manifest.json": json.dumps(manifest).encode()},
                           dict(key, cpu=99) if other_cpu and count == 1000 else key))
        with patch.object(evidence, "collect", side_effect=values) as collector:
            result = evidence.export_sweep({n: self.path for n in (10, 100, 1000)},
                Path(reference["path"]), Path(cohort["path"]), self.root / "sweep")
            self.assertEqual([call.kwargs["batches"] for call in collector.call_args_list], [10, 100, 1000])
            self.assertTrue(all(call.kwargs["updates"] == 131072 for call in collector.call_args_list))
        return result

    def test_sweep_keeps_declared_counts_and_failed_status(self):
        scope = self.sweep(failure=True)
        self.assertEqual(scope["status"], "PARTIAL_RETAINED")
        self.assertEqual(scope["cases"][-1]["status"], "FAILED_RETAINED")
        self.assertTrue((self.root / "sweep/receipts.tar.gz").is_file())

    def test_sweep_cannot_mix_cpu_or_input_cohorts(self):
        with self.assertRaisesRegex(ValueError, "cohorts differ"):
            self.sweep(other_cpu=True)
        with self.assertRaisesRegex(ValueError, "identical graph and update"):
            self.sweep(changed_inputs=True)

    def test_sweep_requires_all_three_statuses(self):
        with self.assertRaisesRegex(ValueError, "all three"):
            evidence.export_sweep({10: self.path}, self.path, self.path, self.root / "sweep")


class PackagedPortableEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1] / (
            "docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/"
            "figure7_11_preview_20261105/fresh_simulator/portable_fig8")
        cls.rows = list(csv.DictReader(io.StringIO((root / "fig8_ten_batch.csv").read_text())))
        cls.scope = json.loads((root / "scope.json").read_text())
        with tarfile.open(root / "receipts.tar.gz") as archive:
            cls.members = {member.name: archive.extractfile(member).read() for member in archive}

    def test_checked_in_cohort_keeps_all_statuses_and_original_receipt_hashes(self):
        self.assertEqual([row["dataset"] for row in self.rows], list(evidence.DATASETS))
        self.assertEqual(self.scope["measured"], ["AU", "SU", "WK", "SO"])
        self.assertEqual(self.scope["failed"], ["PK"])
        for row in self.rows:
            raw = self.members[row["dataset"] + "/results.json"]
            self.assertEqual(hashlib.sha256(raw).hexdigest(), row["receipt_sha256"])
            report = json.loads(raw)
            self.assertEqual(report["status"], row["status"])
            if row["status"] == evidence.STATUS:
                self.assertAlmostEqual(float(row["speedup_gr_over_spine"]),
                    report["comparisons"]["trace"]["speedup_gr_over_spine"])
            else:
                self.assertEqual(row["speedup_gr_over_spine"], "")
                self.assertNotIn("trace", report["comparisons"])
        self.assertIn(b"no capacity-safe free target", self.members["PK/raw/trace_spine.stderr.txt"])

    def test_packaged_raw_device_receipts_replay_against_frozen_smoke(self):
        reference = json.loads(self.members["reference.json"])
        self.assertEqual(hashlib.sha256(self.members["reference.json"]).hexdigest(),
                         self.scope["reference_sha256"])
        with tempfile.TemporaryDirectory() as directory:
            for row in self.rows:
                dataset = row["dataset"]
                report = json.loads(self.members[dataset + "/results.json"])
                names = ["smoke_spine", "smoke_gr"]
                if row["status"] == evidence.STATUS:
                    names += ["trace_spine", "trace_gr"]
                for name in names:
                    path = Path(directory) / (dataset + "_" + name + ".txt")
                    path.write_bytes(self.members[f"{dataset}/raw/{name}.stdout.txt"])
                    step = dict(report["steps"][name], stdout=str(path))
                    smoke = name.startswith("smoke_")
                    arm = name.rsplit("_", 1)[1]
                    parsed = analysis.persistent_device(step, arm=arm,
                        updates=3 if smoke else 4096, batch_count=3 if smoke else 10)
                    self.assertEqual(parsed, {key: report["rows"][name][key]
                                              for key in ("device", "batches")})
                    if smoke:
                        self.assertEqual(parsed, reference["smoke"][arm])


if __name__ == "__main__":
    unittest.main()
