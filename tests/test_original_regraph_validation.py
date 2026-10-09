from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.original_regraph_validation.analysis import (
    admit_captures, analyze, records,
)
from spine_cycle_sim.experiments.original_regraph_validation.study import source_identities
from spine_cycle_sim.experiments.original_regraph_validation.delivery import evidence_files
from spine_cycle_sim.experiments.upstream_controls.validation import validate_contract


ROOT = Path(__file__).resolve().parents[1]


class OriginalReGraphValidationTests(unittest.TestCase):
    def setUp(self):
        self.contract = json.loads((ROOT / (
            "configs/experiments/original_regraph_gather_validation_v1.json")).read_text())
        self.capture_contract = json.loads((ROOT / (
            "configs/experiments/grasu_regraph_upstream_captures_v1.json")).read_text())
        fields = ("clock_mhz", "partition_vertices", "gather_lanes", "default_fifo_depth",
                  "uram_write_latency", "forwarding_entries_per_lane", "timing")
        self.configuration = "MODEL_CONFIG " + json.dumps(
            {field: self.contract[field] for field in fields}) + "\n"
        self.counters = {"cycles": 32781, "checked_words": 65536,
                         "output_stalls": 0, "capacity_stalls": 0}
        self.invariants = self.configuration + "\n".join(
            "GATHER_CASE " + json.dumps({"id": name, **self.counters})
            for name in self.contract["invariant_cases"])
        self.comparison_rows = [
            {"little": little, "source_base": base, "iteration": iteration, **self.counters}
            for little in (4, 11) for base in (0, 4096) for iteration in range(3)]
        self.comparison = self.comparison_stdout(self.comparison_rows)

    def comparison_stdout(self, rows):
        return self.configuration + "\n".join(
            "SOURCE_COMPARISON " + json.dumps(row) for row in rows)

    def test_complete_matrix_is_functional_admission_not_timing_match(self):
        result = analyze(self.invariants, self.comparison, self.comparison, self.contract)
        self.assertEqual(result["compared_source_words"], 786432)
        self.assertIsNone(result["publication_rate_error_pct"])
        self.assertIsNone(result["FPGA_cycle_error_pct"])
        self.assertTrue(result["repeat_stdout_and_all_counters_identical"])

    def test_missing_duplicate_reordered_comparison_is_rejected(self):
        for rows in (self.comparison_rows[:-1], self.comparison_rows + self.comparison_rows[:1],
                     list(reversed(self.comparison_rows))):
            stdout = self.comparison_stdout(rows)
            with self.assertRaises(ValueError):
                analyze(self.invariants, stdout, stdout, self.contract)

    def test_repeat_requires_exact_cycles_and_stalls_not_only_state(self):
        changed = copy.deepcopy(self.comparison_rows)
        changed[0]["capacity_stalls"] += 1
        with self.assertRaises(ValueError):
            analyze(self.invariants, self.comparison, self.comparison_stdout(changed), self.contract)

    def test_model_configuration_and_invariant_matrix_are_required(self):
        for text in (self.invariants.replace(self.configuration, ""),
                     self.invariants.replace('"clock_mhz": 210', '"clock_mhz": 150'),
                     self.invariants + '\nGATHER_CASE ' + json.dumps(
                         {"id": self.contract["invariant_cases"][0], **self.counters})):
            with self.assertRaises(ValueError):
                analyze(text, self.comparison, self.comparison, self.contract)

    def test_counter_types_and_extents_cannot_be_invented_or_missing(self):
        for field, value in (("cycles", 0), ("cycles", True), ("cycles", 1.0),
                             ("checked_words", 1), ("output_stalls", -1)):
            with self.assertRaises(ValueError):
                records("GATHER_CASE " + json.dumps({**self.counters, field: value}), "GATHER_CASE ")
        with self.assertRaises(ValueError):
            records("", "GATHER_CASE ")

    def test_matrix_labels_and_configuration_also_require_exact_types(self):
        rows = copy.deepcopy(self.comparison_rows)
        rows[0]["iteration"] = False
        stdout = self.comparison_stdout(rows)
        with self.assertRaises(ValueError):
            analyze(self.invariants, stdout, stdout, self.contract)
        invariants = self.invariants.replace('"clock_mhz": 210', '"clock_mhz": 210.0')
        with self.assertRaises(ValueError):
            analyze(invariants, self.comparison, self.comparison, self.contract)

    def test_capture_contract_is_optional_and_only_for_little(self):
        contract = json.loads((ROOT / (
            "configs/experiments/grasu_regraph_upstream_captures_v1.json")).read_text())
        validate_contract(contract)
        for value in (False, 1, "yes"):
            invalid = copy.deepcopy(contract)
            invalid["probes"][0]["capture_merged"] = value
            with self.assertRaises(ValueError):
                validate_contract(invalid)
        invalid = json.loads((ROOT / (
            "configs/experiments/grasu_regraph_upstream_controls_v2.json")).read_text())
        invalid["probes"][0]["capture_merged"] = True
        with self.assertRaises(ValueError):
            validate_contract(invalid)

    def test_model_identity_includes_shared_execution_and_numerical_sources(self):
        paths = {row["path"] for row in source_identities(ROOT)}
        for path in ("cpp/src/scheduler.cpp", "cpp/include/spine_sim/fifo.hpp",
                     "cpp/src/original_regraph/little_gather.cpp",
                     "cpp/include/spine_sim/original_regraph/detail/latency_pipe.hpp",
                     "cpp/tests/original_regraph/source_comparison.cpp",
                     "spine_cycle_sim/experiments/original_regraph_validation/analysis.py"):
            self.assertIn(path, paths)
        self.assertFalse(any("calibration_v4" in path for path in paths))

    def test_delivery_keeps_raw_captures_logs_and_flags_not_build_or_source_trees(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            captures, run = root / "captures", root / "run"
            for directory in (captures, run):
                for name in ("report.json", "contract.json", "case/run.stdout.txt",
                             "case/merged.u32le", "case/probe", "prepared/source.cpp",
                             "negative_fixtures/changed_word.u32le", "build/cpp/binary",
                             "build/compile_commands.json", "build/CMakeFiles/compiler.log"):
                    path = directory / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(b"fixture")
            files = {name for _path, name in evidence_files(captures, run)}
            self.assertIn("source_captures/case/merged.u32le", files)
            self.assertIn("finite_model/build/compile_commands.json", files)
            self.assertNotIn("source_captures/build/compile_commands.json", files)
            self.assertFalse(any("prepared" in name or "CMakeFiles" in name or
                                 "negative_fixtures" in name or name.endswith("/probe") for name in files))

    def test_capture_hash_extent_dependency_and_scope_are_enforced(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            code = root / "probe.cpp"
            code.write_text("fixture\n")
            rows = []
            for expected in self.contract["source_controls"]:
                case = root / expected["id"]
                case.mkdir()
                capture = case / "merged.u32le"
                capture.write_bytes(bytes(expected["checked_words"] * 4))
                observed = copy.deepcopy(next(probe["expected"] for probe in
                    self.capture_contract["probes"] if probe["id"] == expected["id"]))
                stdout = case / "stdout.txt"
                stdout.write_text("PUBLICATION_PROBE " + json.dumps(observed))
                rows.append({"id": expected["id"], "status": "FUNCTIONAL_PASS_NOT_TIMING",
                    "expected": observed, "observed": observed,
                    "run": {"exit_code": 0, "timed_out": False, "stdout": str(stdout)},
                    "dependencies": [{"path": str(code), "sha256": sha256_file(code)}],
                    "merged_capture": {"path": str(capture), "sha256": sha256_file(capture),
                        "bytes": capture.stat().st_size,
                        "format": "u32le_source_window_then_iteration_then_vertex",
                        "boundary": "original_global_little_merger_before_apply"}})
            report = {"evidence_class": "upstream_source_functional_only",
                      "all_functional_probes_passed": True, "device_cycles": None,
                      "analysis_code": [{"path": "probe.cpp", "sha256": sha256_file(code)}],
                      "probes": rows}
            path = root / "report.json"
            path.write_text(json.dumps(report))
            self.assertEqual(len(admit_captures(root, root, self.contract)), 2)
            mutations = (
                lambda value: value.update(device_cycles=100),
                lambda value: value.update(probes=value["probes"][:1]),
                lambda value: value["probes"][0].update(status="FAILED"),
                lambda value: value["probes"][0]["merged_capture"].update(bytes=0),
                lambda value: value["probes"][0]["merged_capture"].update(sha256="0" * 64),
                lambda value: value["probes"][0]["merged_capture"].update(boundary="after_apply"),
                lambda value: value["probes"][0]["dependencies"][0].update(sha256="0" * 64),
            )
            for mutate in mutations:
                invalid = copy.deepcopy(report)
                mutate(invalid)
                path.write_text(json.dumps(invalid))
                with self.assertRaises(ValueError):
                    admit_captures(root, root, self.contract)


if __name__ == "__main__":
    unittest.main()
