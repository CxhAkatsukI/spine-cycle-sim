"""Recheck delivered independent-stage evidence without rerunning models."""

import hashlib
import json
from pathlib import Path
import tarfile
import unittest

from spine_cycle_sim.experiments.campaign_runtime import sha256_file


ROOT = Path(__file__).resolve().parents[1]
STUDY = ROOT / "docs/experiments/comparisons/grasu_regraph_stage_validation"


def load(path):
    return json.loads(path.read_text())


class StageValidationDeliveryTests(unittest.TestCase):
    def test_refactor_raw_results_match_every_field_and_preserve_rejections(self):
        for owner, phases, reports, count in (
            ("grasu_component_refactor", ("before", "after"), ("equivalence.json",), 5),
            ("sst_spine_refactor", ("before", "after_sst", "after_spine"),
             ("sst_equivalence.json", "spine_equivalence.json"), 14),
        ):
            directory = ROOT / "docs/repository" / owner
            contract_name = "sst_spine_component_refactor_v2" if count == 14 else "grasu_component_refactor_v1"
            contract = load(ROOT / f"configs/experiments/{contract_name}.json")
            expected = {case["id"]: case.get("expected_rejection") for case in contract["cases"]}
            with tarfile.open(directory / "raw_runs.tar.gz") as archive:
                for report_name in reports:
                    report = load(directory / report_name)
                    self.assertEqual(report["status"], "PASS")
                    self.assertEqual(report["ignored_result_fields"], [])
                    self.assertEqual(len(report["cases"]), count)
                    for case in report["cases"]:
                        with self.subTest(owner=owner, case=case["case"]):
                            prefix = "results/sst_spine_component_refactor_v2/" if count == 14 else ""
                            payloads = [archive.extractfile(
                                f'{prefix}{phase}/cases/{case["case"]}/result.json').read()
                                for phase in phases]
                            self.assertTrue(all(value == payloads[0] for value in payloads))
                            self.assertEqual(case["result_hashes"],
                                             [hashlib.sha256(payloads[0]).hexdigest()] * 2)
                            self.assertEqual(case["changed_fields"], [])
                            self.assertEqual(case["changed_manifest_identities"], [])
                            rejection = expected[case["case"]]
                            if rejection is None:
                                self.assertTrue(json.loads(payloads[0])["success"])
                            else:
                                for field, value in rejection["result_fields"].items():
                                    self.assertEqual(json.loads(payloads[0])[field], value)
                            for phase in phases:
                                campaign = json.load(archive.extractfile(
                                    f"{prefix}{phase}/campaign/campaign_state.json"))
                                job = next(job for job in campaign["jobs"] if job["job_id"] == case["case"])
                                self.assertEqual(job["status"], "fail" if rejection else "pass")
                                self.assertEqual(job["exit_code"], 1 if rejection else 0)
                    if count == 14:
                        self.assertEqual(report["correctness_admitted_cases"], 10)
                        self.assertEqual(report["known_rejections"], 4)

    def test_complete_stage_archives_and_result_identities_match(self):
        for stem, archive_name in (
            ("a4", "raw_a4_graph_execution.tar.gz"),
            ("mixed", "raw_mixed_execution.tar.gz"),
            ("finite_pma", "raw_finite_pma.tar.gz"),
            ("finite_grasu", "raw_finite_grasu.tar.gz"),
        ):
            with self.subTest(stage=stem):
                spec = load(STUDY / f"{stem}_verification.json")
                path = STUDY / archive_name
                self.assertEqual(sha256_file(path), spec["archive_sha256"])
                self.assertEqual(path.stat().st_size, spec["archive_bytes"])
                self.assertEqual(sha256_file(STUDY / f"{stem}_results.json"), spec["results_sha256"])
                with tarfile.open(path) as archive:
                    files = [member for member in archive if member.isfile()]
                    indexed = {row["path"]: row for row in spec["files"]}
                    self.assertEqual(len(indexed), len(spec["files"]))
                    self.assertEqual(len(files), len(indexed))
                    self.assertEqual({member.name for member in files}, set(indexed))
                    for member in files:
                        self.assertEqual(member.size, indexed[member.name]["bytes"])
                        with archive.extractfile(member) as stream:
                            self.assertEqual(hashlib.file_digest(stream, "sha256").hexdigest(),
                                             indexed[member.name]["sha256"])

    def test_G_complete_repetitions_are_exact_without_claiming_timing(self):
        report = load(STUDY / "finite_grasu_results.json")
        self.assertEqual(report["status"], "G_FINITE_SOURCE16_STATE_LEDGER_PASS_NOT_TIMING")
        self.assertEqual(len(report["rows"]), 24)
        groups = {}
        for row in report["rows"]:
            groups.setdefault(row["id"], []).append(row)
            result = row["result"]
            self.assertEqual(result["status"], "SOURCE16_STATE_AND_FINITE_LEDGER_PASS")
            self.assertIsNone(result["fpga_timing_match"])
            self.assertIsNone(result["publication_timing_match"])
        self.assertEqual(len(groups), 12)
        for rows in groups.values():
            self.assertEqual({row["repetition"] for row in rows}, {0, 1})
            self.assertEqual(rows[0]["result"], rows[1]["result"])

    def test_original_R_controls_repeat_complete_state_and_ledgers(self):
        for stem in ("a4", "mixed"):
            report = load(STUDY / f"{stem}_results.json")
            self.assertEqual(len(report["cases"]), 8)
            for case in report["cases"]:
                first, repeat = [run["analysis"] for run in case["runs"]]
                self.assertEqual(first, repeat)
                self.assertTrue(first["result"]["passed"])
                self.assertTrue(first["result"]["queues_and_requests_conserved"])
                self.assertEqual(first["result"]["iterations"], 1)
                self.assertIsNone(first.get("publication_rate_error_pct", first.get("publication_error_pct")))

    def test_B_uses_the_same_A4_state_and_downstream_budget(self):
        report = load(STUDY / "finite_pma_results.json")
        self.assertEqual(len(report["cases"]), 8)
        self.assertEqual(report["matrix_checks"]["unadmitted_cases"], [])
        self.assertIsNone(report["FPGA_measured_cycles"])
        self.assertIsNone(report["publication_rate_error_pct"])
        for case in report["cases"]:
            actual, matched = case["analysis"], case["matched"]["analysis"]
            self.assertEqual(actual["files"], matched["files"])
            a, b = matched["result"], actual["result"]
            for field in ("clock_mhz", "little", "big", "iterations", "argument",
                          "memory_latency", "outstanding_bursts", "state_parent_credits",
                          "logical_edges", "source_read_bytes", "degree_read_bytes",
                          "property_write_bytes", "checked_sum_words", "checked_replica_words"):
                self.assertEqual(a[field], b[field], f'{case["id"]}: {field}')
            self.assertTrue(b["passed"])
            self.assertTrue(b["queues_and_requests_conserved"])
            self.assertFalse(b["timing_calibrated_to_FPGA"])
            self.assertAlmostEqual(actual["modeled_overhead_pct"], (b["cycles"] / a["cycles"] - 1) * 100)

    def test_current_numerical_sources_retain_the_accepted_identities(self):
        report = load(ROOT / "docs/repository/sst_spine_refactor/spine_equivalence.json")
        identities = [row for row in report["candidate_identity"]["source"]["files"]
                      if row["path"].startswith(("cpp/src/", "cpp/include/", "cpp/sst/"))
                      and row["path"].endswith((".cpp", ".hpp"))]
        identities += load(STUDY / "finite_grasu_results.json")["model"]["files"]
        for row in identities:
            with self.subTest(path=row["path"]):
                self.assertEqual(sha256_file(ROOT / row["path"]), row["sha256"])


if __name__ == "__main__":
    unittest.main()
