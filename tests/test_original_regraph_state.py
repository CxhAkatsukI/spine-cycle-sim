from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.original_regraph_validation.state_analysis import analyze_state
from spine_cycle_sim.experiments.original_regraph_validation.state_sources import admit_apply
from spine_cycle_sim.experiments.original_regraph_validation.study import source_identities
from spine_cycle_sim.experiments.upstream_controls.sources import writer_invocation
from spine_cycle_sim.experiments.upstream_controls.validation import validate_contract

ROOT = Path(__file__).resolve().parents[1]


class StateAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.contract = json.loads((ROOT / "configs/experiments/original_regraph_state_validation_v1.json").read_text())
        def make(name, words=2048, replicas=4, case=0):
            return {"id": name, "case_index": case, "replicas": replicas, "cycles": 100,
                    "checked_words": words, "degree_bytes": words * 4,
                    "write_bytes": words * 4 * replicas, "degree_requests": words // 16,
                    "write_requests": words // 16 * replicas, "write_acknowledgements": words // 16 * replicas,
                    "apply_credit_stalls": 0, "writer_credit_stalls": 0, "apply_output_stalls": 0,
                    "max_apply_live": 12, "max_writer_live": 4, "waited_for_write_ack": True}
        self.cases = [make(name) for name in self.contract["invariant_cases"]]
        self.cases[3].update(cycles=200, apply_credit_stalls=100, max_apply_live=1, max_writer_live=1)
        self.cases[4].update(cycles=150, writer_credit_stalls=10, apply_output_stalls=9, max_writer_live=1)
        self.cases[5]["cycles"] = 180
        self.source = [make("source_comparison", 65536, replicas, case)
                       for replicas in (4, 14) for case in range(3)]
        self.iterations = [{"id": name, **self.contract["iteration_work"],
                            "shared_channel_contended_cycles": 10, "cycles": [1000] * 3}
                           for name in self.contract["iteration_cases"]]

    def texts(self):
        configuration = "STATE_CONFIG " + json.dumps(self.contract["configuration"]) + "\n"
        return {
            "state": configuration + "\n".join([
                *["STATE_CASE " + json.dumps(row) for row in self.cases],
                *["STATE_REJECTION " + json.dumps(row) for row in self.contract["expected_rejections"]]]),
            "comparison": configuration + "\n".join("STATE_CASE " + json.dumps(row) for row in self.source),
            "iterations": configuration + "\n".join("ITERATION_CASE " + json.dumps(row) for row in self.iterations),
        }

    def analyze(self, repeated=None):
        text = self.texts()
        return analyze_state(text["state"], text["comparison"], text["iterations"],
                             text if repeated is None else repeated, self.contract)

    def test_complete_matrix_has_no_measured_timing_claim(self):
        result = self.analyze()
        self.assertEqual(result["compared_source_words"], 393216)
        self.assertIsNone(result["publication_rate_error_pct"])
        self.assertIsNone(result["FPGA_cycle_error_pct"])

    def test_repetition_configuration_and_rejections_are_required(self):
        repeated = self.texts()
        repeated["state"] += "changed"
        with self.assertRaises(ValueError):
            self.analyze(repeated)
        self.contract["expected_rejections"].append({"id": "absent", "expected_rejection": True})
        text = self.texts()
        text["state"] = "\n".join(line for line in text["state"].splitlines()
                                    if not line.startswith("STATE_REJECTION "))
        with self.assertRaises(ValueError):
            analyze_state(text["state"], text["comparison"], text["iterations"], text, self.contract)

    def test_noninteger_unconserved_unbounded_or_premature_completion_rejected(self):
        saved = copy.deepcopy(self.cases)
        for key, value in (("cycles", True), ("degree_bytes", 0), ("write_acknowledgements", 0),
                           ("max_apply_live", 101), ("waited_for_write_ack", 1), ("checked_words", 65536)):
            self.cases = copy.deepcopy(saved)
            self.cases[0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.analyze()

    def test_pressure_reuse_or_registration_change_cannot_pass(self):
        saved = copy.deepcopy(self.cases)
        for index, key, value in ((1, "cycles", 101), (3, "apply_credit_stalls", 0),
                                  (4, "apply_output_stalls", 0), (5, "cycles", 100)):
            self.cases = copy.deepcopy(saved)
            self.cases[index][key] = value
            with self.subTest(index=index, key=key), self.assertRaises(ValueError):
                self.analyze()

    def test_source_matrix_missing_duplicate_or_wrong_replica_rejected(self):
        saved = copy.deepcopy(self.source)
        for rows in (saved[:-1], saved + saved[:1], list(reversed(saved))):
            self.source = rows
            with self.assertRaises(ValueError):
                self.analyze()

    def test_resident_iteration_work_contention_and_order_required(self):
        saved = copy.deepcopy(self.iterations)
        for key, value in (("read_bytes", 0), ("shared_channel_contended_cycles", 0), ("cycles", [1000, True, 1000])):
            self.iterations = copy.deepcopy(saved)
            self.iterations[0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.analyze()

    def test_code_identities_include_state_and_shared_test_ownership(self):
        paths = {row["path"] for row in source_identities(ROOT)}
        for name in ("cpp/src/original_regraph/pr_apply.cpp", "cpp/tests/original_regraph/memory_fixture.hpp",
                     "scripts/run_original_regraph_state_validation.py", "tests/test_original_regraph_state.py"):
            self.assertIn(name, paths)


class OriginalApplySourceTests(unittest.TestCase):
    def test_contract_and_generated_writer_cover_all_replicas(self):
        contract = json.loads((ROOT / "configs/experiments/regraph_upstream_apply_v1.json").read_text())
        validate_contract(contract)
        for replicas in (4, 14):
            invocation = writer_invocation(replicas)
            self.assertIn(f"replicas[{replicas - 1}].data()", invocation)
            self.assertNotIn(f"replicas[{replicas}].data()", invocation)
        for replicas in (0, 15, True, "4"):
            with self.assertRaises(ValueError):
                writer_invocation(replicas)

    def test_apply_admission_rechecks_matrix_code_dependency_and_capture(self):
        contract = json.loads((ROOT / "configs/experiments/original_regraph_state_validation_v1.json").read_text())
        canonical = ROOT / "configs/experiments/regraph_upstream_apply_v1.json"
        source = json.loads(canonical.read_text())
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "contract.json").write_text(json.dumps(source))
            paths = sorted((ROOT / "spine_cycle_sim/experiments/upstream_controls").glob("*.py"))
            paths.append(ROOT / "scripts/run_upstream_stage_controls.py")
            report = {
                "all_functional_probes_passed": True, "evidence_class": "upstream_source_functional_only",
                "device_cycles": None, "contract_sha256": sha256_file(canonical),
                "pins_sha256": sha256_file(ROOT / "docs/experiments/comparisons/grasu_regraph_stage_validation/source_pins.json"),
                "analysis_code": [{"path": str(path.relative_to(ROOT)), "sha256": sha256_file(path)} for path in paths],
                "probes": [],
            }
            for probe in source["probes"]:
                capture = directory / (probe["id"] + ".u32le")
                capture.write_bytes(bytes(196608 * 4))
                stdout = directory / (probe["id"] + ".txt")
                stdout.write_text("PUBLICATION_PROBE " + json.dumps(probe["expected"]))
                report["probes"].append({
                    "id": probe["id"], "status": "FUNCTIONAL_PASS_NOT_TIMING", "expected": probe["expected"],
                    "observed": probe["expected"], "run": {"exit_code": 0, "timed_out": False, "stdout": str(stdout)},
                    "dependencies": [{"path": str(canonical), "sha256": sha256_file(canonical)}],
                    "applied_capture": {"path": str(capture), "bytes": capture.stat().st_size,
                        "sha256": sha256_file(capture), "format": "u32le_case_then_vertex",
                        "boundary": "original_Apply_then_HBM_writer_all_replicas_checked"},
                })
            report_path = directory / "report.json"
            report_path.write_text(json.dumps(report))
            self.assertEqual(len(admit_apply(directory, ROOT, contract)), 2)
            for mutate in (lambda r: r.update(device_cycles=123), lambda r: r.update(analysis_code=[]),
                           lambda r: r["probes"].pop(),
                           lambda r: r["probes"][0]["dependencies"][0].update(sha256="wrong"),
                           lambda r: r["probes"][0]["applied_capture"].update(boundary="before_apply")):
                changed = copy.deepcopy(report)
                mutate(changed)
                report_path.write_text(json.dumps(changed))
                with self.assertRaises(ValueError):
                    admit_apply(directory, ROOT, contract)
            report_path.write_text(json.dumps(report))
            Path(report["probes"][0]["applied_capture"]["path"]).write_bytes(b"short")
            with self.assertRaises(ValueError):
                admit_apply(directory, ROOT, contract)


if __name__ == "__main__":
    unittest.main()
