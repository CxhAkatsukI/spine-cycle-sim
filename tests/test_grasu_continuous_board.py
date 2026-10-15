import copy
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.evaluation_impact.common_g.continuous_board import (
    analysis, delivery, preparation,
)
from spine_cycle_sim.experiments.evaluation_impact.common_g.search_pipeline.synthesis import unchanged


class ContinuousBoardTests(unittest.TestCase):
    def case(self, name="AU-mixed-512"):
        return {"case": name, "shards": 1, "partition_vertices": 65536,
                "batches": [{"batch": 0, "updates": 0, "edges": 8192},
                            {"batch": 1, "updates": 256, "edges": 8104},
                            {"batch": 2, "updates": 256, "edges": 8192}]}

    def cases(self):
        return [self.case(f"{dataset}-{suffix}") for dataset in ("AU", "SU", "WK")
                for suffix in ("mixed-512", "weight_change-4096")]

    def setup(self):
        return {"board": False, "shards": 1, "hbm_bytes": 16777344, "one_time_setup_ms": 12.0}

    def rows(self, case=None):
        return [{**row, "board": False, "checked_words": 2 * 131072 * 16 + 32,
                 **dict.fromkeys(analysis.TIMES, 0.0), "host_preparation_ms": 0.5,
                 "g_ready_wall_ms": 0.5, "complete_state_pass": True,
                 "metadata_pass": True, "restored_pma": False}
                for row in (case or self.case())["batches"]]

    def stdout(self, rows=None, setup=None, marker=analysis.PASS):
        return "\n".join(["CONTINUOUS_G_SETUP " + json.dumps(setup or self.setup()),
                          *("CONTINUOUS_G_ROW " + json.dumps(row) for row in
                            (self.rows() if rows is None else rows)), marker])

    def test_exact_resident_state_and_zero_batch(self):
        self.assertEqual(analysis.analyze(self.case(), self.stdout(), ""),
                         {"setup": self.setup(), "rows": self.rows()})

    def test_state_padding_metadata_or_restoration_fault_rejected(self):
        for key, value in (("batch", 1), ("updates", 5), ("edges", 1), ("checked_words", 1),
                           ("complete_state_pass", False), ("metadata_pass", False),
                           ("restored_pma", True), ("board", True)):
            rows = self.rows()
            rows[0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                analysis.analyze(self.case(), self.stdout(rows), "")

    def test_boolean_counts_and_invalid_times_are_not_valid_measurements(self):
        for key, value in (("batch", False), ("updates", False), ("checked_words", True),
                           ("host_preparation_ms", True), ("oracle_ms", float("nan")),
                           ("verification_readback_ms", float("inf")), ("transfer_wall_ms", -1),
                           ("g_ready_wall_ms", 0.4), ("kernel_busy_ms", 0.1), ("kernel_span_ms", 1)):
            rows = self.rows()
            rows[0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                analysis.analyze(self.case(), self.stdout(rows), "")

    def test_board_output_extra_events_missing_rows_and_diagnostics_rejected(self):
        for stdout, stderr in ((self.stdout(marker=analysis.BOARD_PASS), ""),
                               (self.stdout(self.rows()[:-1]), ""),
                               (self.stdout() + "\nCONTINUOUS_G_EVENT {}", ""),
                               (self.stdout(), "unclassified warning")):
            with self.subTest(stdout=stdout, stderr=stderr), self.assertRaises(ValueError):
                analysis.analyze(self.case(), stdout, stderr)
        for key, value in (("board", True), ("shards", True), ("hbm_bytes", 0),
                           ("hbm_bytes", True), ("one_time_setup_ms", float("nan")),
                           ("one_time_setup_ms", True)):
            setup = self.setup()
            setup[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                analysis.analyze(self.case(), self.stdout(setup=setup), "")

    def test_xrt_compile_keeps_warnings_assertions_and_all_header_dependencies(self):
        argv = preparation.command(Path("source"), Path("xrt"), "g++", Path("probe"))
        for flag in ("-std=c++20", "-O2", "-Wall", "-Wextra", "-Werror", "-D_GLIBCXX_ASSERTIONS",
                     "-MD", "-lxilinxopencl", "source/continuous_board/control.cpp"):
            self.assertIn(flag, argv)
        self.assertNotIn("-MMD", argv)
        self.assertFalse(any("MAX_CACHE_SEGMENT=" in flag for flag in argv))

    def test_host_contract_is_separate_from_immutable_composition_contract(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            integration = root / "integration"
            header = integration / "include/weighted_pma_update_reference.hpp"
            header.parent.mkdir(parents=True)
            header.write_text("reference")
            original = {"cases": [*self.cases(), {**self.case("smoke"), "partition_vertices": 1024}]}
            def base(output, upstream, integration):
                (output / "source/host").mkdir(parents=True)
                path = output / "contract.json"
                path.write_text(json.dumps(original))
                return [{"path": str(path), "sha256": sha256_file(path)}], original
            output = root / "attempt"
            with patch.object(preparation, "prepare_real", base):
                pins, contract = preparation.prepare(output, root / "upstream", integration)
            self.assertEqual(contract["cases"], self.cases())
            self.assertEqual(json.loads((output / "contract.json").read_text()), original)
            self.assertEqual(len(pins), len({pin["path"] for pin in pins}))
            self.assertIn("no PMA restoration", contract["scope"])
            unchanged(pins)

    def attempt(self, root, status=analysis.PASS):
        attempt = root / "attempt"
        source = attempt / "source/control.cpp"
        source.parent.mkdir(parents=True)
        source.write_text("frozen source")
        (attempt / "probe").write_bytes(b"compiled host")
        contract = {"cases": self.cases()}
        (attempt / "continuous_contract.json").write_text(json.dumps(contract))
        steps, cases = [], []
        for label in ("compile", *(case["case"] for case in self.cases())):
            out, err = attempt / (label + ".stdout.txt"), attempt / (label + ".stderr.txt")
            out.write_text("" if label == "compile" else self.stdout())
            err.write_text("")
            resource = {"stdout": str(out), "stderr": str(err), "exit_code": 0, "timed_out": False}
            (attempt / (label + ".resources.json")).write_text(json.dumps(resource))
            steps.append({"label": label, **resource})
            if label != "compile":
                cases.append({"case": label, "setup": self.setup(), "rows": self.rows()})
        report = {"status": status, "errors": [] if status == analysis.PASS else ["retained failure"],
                  "source": [{"path": str(source), "sha256": sha256_file(source)}],
                  "contract": contract, "steps": steps, "cases": cases, "dependencies": [],
                  "binary_sha256": sha256_file(attempt / "probe"), **dict.fromkeys(analysis.CLAIMS, False)}
        (attempt / "results.json").write_text(json.dumps(report))
        return attempt, report

    def test_delivery_reanalyzes_raw_logs_and_requires_full_native_matrix(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            attempt, report = self.attempt(root)
            delivery.validate(attempt, report)
            with self.assertRaisesRegex(ValueError, "complete matrix"):
                delivery.validate(attempt, {**report, "steps": report["steps"][:1]})
            changed = copy.deepcopy(report)
            changed["cases"][0]["rows"][0]["edges"] = 0
            with self.assertRaisesRegex(ValueError, "raw execution"):
                delivery.validate(attempt, changed)
            with self.assertRaisesRegex(ValueError, "contract changed"):
                delivery.validate(attempt, {**report, "contract": {"cases": self.cases()[:-1]}})
            Path(report["steps"][1]["stdout"]).write_text(self.stdout(marker=analysis.BOARD_PASS))
            with self.assertRaisesRegex(ValueError, "host-only"):
                delivery.validate(attempt, report)

    def test_capsule_claims_and_corruption_are_guarded(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            attempt, report = self.attempt(root)
            output = root / "evidence"
            index = delivery.package(output, [attempt])
            self.assertEqual(index, delivery.verify(output))
            for claim in analysis.CLAIMS:
                with self.subTest(claim=claim), self.assertRaisesRegex(ValueError, "claim boundary"):
                    delivery.validate(attempt, {**report, claim: True})
            for fault in ("board claim", "index mismatch"):
                changed = copy.deepcopy(index)
                if fault == "board claim": changed["complete_GR_admitted"] = True
                else: changed["attempts"][0]["cases"][0]["rows"][0]["edges"] = 0
                (output / "index.json").write_text(json.dumps(changed))
                with self.subTest(fault=fault), self.assertRaises(ValueError):
                    delivery.verify(output)
            (output / "index.json").write_text(json.dumps(index))
            archive = output / index["attempts"][0]["archive"]
            archive.write_bytes(archive.read_bytes() + b"corrupt")
            with self.assertRaisesRegex(ValueError, "archive identity"):
                delivery.verify(output)

    def test_failed_preflight_is_retained_without_board_admission(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            attempt, report = self.attempt(root, "FAILED_RETAINED")
            index = delivery.package(root / "evidence", [attempt])
            self.assertEqual(index["attempts"][0]["errors"], report["errors"])
            self.assertTrue(all(index[claim] is False for claim in analysis.CLAIMS))

    def test_committed_capsule_contains_eighteen_host_only_rows(self):
        root = Path(__file__).resolve().parents[1]
        evidence = root / ("docs/experiments/comparisons/grasu_regraph_stage_validation/"
                           "evaluation_impact/hardware_validation/complete_pipeline/continuous_board/evidence")
        index = delivery.verify(evidence)
        self.assertEqual(len(index["attempts"]), 1)
        entry = index["attempts"][0]
        self.assertEqual(entry["status"], analysis.PASS)
        self.assertEqual(len(entry["cases"]), 6)
        self.assertEqual(sum(len(case["rows"]) for case in entry["cases"]), 18)
        self.assertTrue(all(index[claim] is False for claim in analysis.CLAIMS))
        self.assertTrue(all(case["setup"]["board"] is False and
                            all(row["board"] is False and row["kernel_busy_ms"] == 0
                                for row in case["rows"]) for case in entry["cases"]))
        with tarfile.open(evidence / entry["archive"]) as bundle:
            report = json.load(bundle.extractfile("results.json"))
            for case, result in zip(report["contract"]["cases"], report["cases"], strict=True):
                name = case["case"]
                actual = analysis.analyze(case, bundle.extractfile(name + ".stdout.txt").read().decode(),
                                          bundle.extractfile(name + ".stderr.txt").read().decode())
                self.assertEqual(actual, {key: result[key] for key in ("setup", "rows")})


if __name__ == "__main__":
    unittest.main()
