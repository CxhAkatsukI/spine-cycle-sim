from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.original_regraph_validation.frontend_analysis import (
    admit_protocol, analyze_frontend, protocol_rows,
)
from spine_cycle_sim.experiments.original_regraph_validation.study import source_identities

ROOT = Path(__file__).resolve().parents[1]


class OriginalFrontendTests(unittest.TestCase):
    def setUp(self):
        self.contract = json.loads((ROOT / (
            "configs/experiments/original_regraph_frontend_validation_v1.json")).read_text())
        self.source_contract = json.loads((ROOT / (
            "configs/experiments/regraph_upstream_scatter_protocol_v2.json")).read_text())
        self.cases = []
        for case in self.contract["cases"]:
            name, little = case["id"], case["little"]
            pressure = name == "depth1_slow_sink"
            gather = name == "a4_memory_to_merged"
            requests = len(case["requests"]) * little
            edge_bytes = len(case["rounds"]) * 256 * little
            source_bytes = requests * 16384
            self.cases.append({
                "id": name, "completed": True, "cycles": 2000 if name in (
                    "depth1_slow_sink", "one_outstanding", "memory_latency128") else 1000,
                "edge_bytes": edge_bytes, "source_bytes": source_bytes,
                "normal_requests": requests, "source_loaded": requests * 256 - 1,
                "source_discarded": 1, "scatter_stalls": int(pressure), "edge_stalls": 0,
                "source_response_stalls": int(pressure), "axi_stalls": 0,
                "axi_beats": (edge_bytes + source_bytes) // 64,
                "checked_words": 65536 if gather else len(case["rounds"]) * 32,
                "first_merged": 500 if gather else 0, "last_scatter_done": 900,
                "little": little, "fifo_depth": 1 if pressure else 8,
                "memory_latency": 128 if name == "memory_latency128" else 64,
                "outstanding": 1 if name == "one_outstanding" else 16,
                "gather": gather, "request_rounds": [case["requests"]] * little,
            })
        by_id = {case["id"]: case for case in self.contract["cases"]}
        self.source_rows = [{
            "id": name, "checked_words": len(by_id[name]["rounds"]) * 32,
            "source_response_lines": len(by_id[name]["requests"]) * 256,
            "request_rounds": by_id[name]["requests"],
        } for name in self.contract["source_protocol_cases"]]
        self.protocol = {"cases": self.source_rows}

    def stdout(self, cases=None):
        return "\n".join([
            "FRONTEND_CONFIG " + json.dumps(self.contract["configuration"]),
            *["FRONTEND_CASE " + json.dumps(row) for row in (
                self.cases if cases is None else cases)],
            *["FRONTEND_REJECTION " + json.dumps(row)
              for row in self.contract["expected_rejections"]],
        ])

    def source_stdout(self, records=None):
        return "\n".join("ORIGINAL_SCATTER_CASE " + json.dumps(row)
                         for row in (self.source_rows if records is None else records))

    def test_complete_matrix_is_not_published_or_FPGA_timing(self):
        result = analyze_frontend(self.stdout(), self.stdout(), self.protocol, self.contract)
        self.assertEqual(result["original_protocol_checked_words"], 320)
        self.assertIsNone(result["publication_rate_error_pct"])
        self.assertIsNone(result["FPGA_cycle_error_pct"])

    def test_repetition_requires_all_counters_identical(self):
        cases = copy.deepcopy(self.cases)
        cases[0]["cycles"] += 1
        with self.assertRaises(ValueError):
            analyze_frontend(self.stdout(), self.stdout(cases), self.protocol, self.contract)

    def test_missing_reordered_duplicate_rows_are_rejected(self):
        for cases in (self.cases[:-1], list(reversed(self.cases)), self.cases + self.cases[:1]):
            text = self.stdout(cases)
            with self.assertRaises(ValueError):
                analyze_frontend(text, text, self.protocol, self.contract)

    def test_work_types_conservation_and_resource_changes_are_rejected(self):
        for key, value in (("completed", 1), ("cycles", True), ("edge_bytes", 512.0),
                           ("source_loaded", 0), ("axi_beats", 0), ("outstanding", 32),
                           ("request_rounds", [[0, 0]]), ("gather", 0)):
            cases = copy.deepcopy(self.cases)
            cases[0][key] = value
            text = self.stdout(cases)
            with self.assertRaises(ValueError):
                analyze_frontend(text, text, self.protocol, self.contract)

    def test_configuration_rejection_and_pressure_checks_cannot_be_dropped(self):
        texts = [self.stdout().replace('"clock_mhz": 210', '"clock_mhz": 150'),
                 "\n".join(line for line in self.stdout().splitlines()
                           if not line.startswith("FRONTEND_REJECTION "))]
        cases = copy.deepcopy(self.cases)
        cases[4]["source_response_stalls"] = 0
        texts.append(self.stdout(cases))
        for text in texts:
            with self.assertRaises(ValueError):
                analyze_frontend(text, text, self.protocol, self.contract)

    def test_source_guard_is_signed_and_sparse_requests_are_not_consecutive(self):
        observed = protocol_rows(self.source_stdout(), self.contract)
        self.assertEqual(observed[-2]["request_rounds"], [0, 2, 3])
        self.assertEqual(observed[-1]["request_rounds"], [0, 1, 3, 4])
        changed = copy.deepcopy(self.source_rows)
        changed[-1]["request_rounds"] = [0, 1, 2, 3, 4]
        with self.assertRaises(ValueError):
            protocol_rows(self.source_stdout(changed), self.contract)

    def test_source_protocol_must_match_model_not_only_summary(self):
        protocol = copy.deepcopy(self.protocol)
        protocol["cases"][0]["source_response_lines"] -= 1
        with self.assertRaises(ValueError):
            analyze_frontend(self.stdout(), self.stdout(), protocol, self.contract)

    def test_identities_include_memory_and_new_validation_owners(self):
        identities = {row["path"] for row in source_identities(ROOT)}
        for name in ("cpp/src/axi.cpp", "cpp/src/memory_backend.cpp",
                     "cpp/src/original_regraph/little_scatter.cpp",
                     "cpp/tests/original_regraph/frontend_wiring.hpp",
                     "spine_cycle_sim/experiments/original_regraph_validation/frontend_analysis.py",
                     "scripts/run_original_regraph_frontend_validation.py"):
            self.assertIn(name, identities)

    def test_protocol_admission_requires_code_dependencies_boundary_and_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            canonical = root / "configs/experiments/regraph_upstream_scatter_protocol_v2.json"
            canonical.parent.mkdir(parents=True)
            canonical.write_text(json.dumps(self.source_contract))
            (root / "contract.json").write_text(json.dumps(self.source_contract, indent=2, sort_keys=True))
            code = root / "control.py"
            code.write_text("fixture")
            stdout = root / "run.stdout.txt"
            expected = self.source_contract["probes"][0]
            stdout.write_text(self.source_stdout() + "\nPUBLICATION_PROBE " +
                              json.dumps(expected["expected"]))
            report = {
                "evidence_class": "upstream_source_functional_only", "device_cycles": None,
                "all_functional_probes_passed": True, "contract_sha256": sha256_file(canonical),
                "analysis_code": [{"path": "control.py", "sha256": sha256_file(code)}],
                "probes": [{"id": expected["id"], "status": "FUNCTIONAL_PASS_NOT_TIMING",
                    "observed": expected["expected"], "expected": expected["expected"],
                    "compile": {"exit_code": 0, "timed_out": False},
                    "run": {"exit_code": 0, "timed_out": False, "stdout": str(stdout)},
                    "dependencies": [{"path": str(code), "sha256": sha256_file(code)}]}],
            }
            path = root / "report.json"
            path.write_text(json.dumps(report))
            self.assertEqual(len(admit_protocol(root, root, self.contract)["cases"]), 5)
            mutations = (
                lambda value: value.update(device_cycles=1),
                lambda value: value.update(analysis_code=[]),
                lambda value: value["probes"][0].update(dependencies=[]),
                lambda value: value["probes"][0]["run"].update(timed_out=True),
                lambda value: value["probes"][0]["dependencies"][0].update(sha256="0" * 64),
                lambda value: value["probes"][0].update(status="FAILED"),
                lambda value: value.update(contract_sha256="0" * 64),
            )
            for mutate in mutations:
                changed = copy.deepcopy(report)
                mutate(changed)
                path.write_text(json.dumps(changed))
                with self.assertRaises(ValueError):
                    admit_protocol(root, root, self.contract)


if __name__ == "__main__":
    unittest.main()
