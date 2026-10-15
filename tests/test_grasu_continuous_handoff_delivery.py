import copy
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.evaluation_impact.common_g.continuous_board import (
    analysis as g_analysis, delivery as g_delivery,
)
from spine_cycle_sim.experiments.evaluation_impact.common_g.continuous_handoff import analysis, delivery
from tests import test_grasu_continuous_handoff as fixtures


GUIDE = Path("docs/experiments/comparisons/grasu_regraph_stage_validation/"
             "evaluation_impact/hardware_validation/complete_pipeline/continuous_handoff")


class ContinuousHandoffDeliveryTests(unittest.TestCase):
    def attempt(self, root, status=analysis.PASS):
        helper = fixtures.ContinuousHandoffTests()
        attempt = root / "attempt"
        source = attempt / "source/control.cpp"
        source.parent.mkdir(parents=True)
        source.write_text("frozen control")
        for binary in ("probe", "resident-test"):
            (attempt / binary).write_bytes(binary.encode())
        cases = [{**helper.case(), "case": dataset + "-" + suffix, "partition_vertices": 65536}
                 for dataset in ("AU", "SU", "WK") for suffix in ("mixed-512", "weight_change-4096")]
        contract = {"cases": cases}
        (attempt / "handoff_contract.json").write_text(json.dumps(contract))
        steps, results = [], []
        for label in ("unit-compile", "unit", "compile", *(case["case"] for case in cases)):
            out, err = attempt / (label + ".stdout.txt"), attempt / (label + ".stderr.txt")
            out.write_text(analysis.UNIT_PASS + "\n" if label == "unit" else
                           "" if label.endswith("compile") else helper.text(*helper.output()))
            err.write_text("")
            resource = {"stdout": str(out), "stderr": str(err), "exit_code": 0, "timed_out": False}
            (attempt / (label + ".resources.json")).write_text(json.dumps(resource))
            steps.append({"label": label, **resource})
            if label not in ("unit-compile", "unit", "compile"):
                results.append({"case": label, "setup": helper.output()[0], "rows": helper.output()[1]})
        report = {"status": status, "errors": [] if status == analysis.PASS else ["retained parser rejection"],
                  "contract": contract, "source": [{"path": str(source), "sha256": sha256_file(source)}],
                  "steps": steps, "cases": results, "dependencies": [],
                  "compile_binary_sha256": sha256_file(attempt / "probe"),
                  "unit-compile_binary_sha256": sha256_file(attempt / "resident-test"),
                  **dict.fromkeys(analysis.CLAIMS, False)}
        (attempt / "results.json").write_text(json.dumps(report))
        return attempt, report

    def test_delivery_requires_complete_raw_matrix_and_unit_execution(self):
        with tempfile.TemporaryDirectory() as temporary:
            attempt, report = self.attempt(Path(temporary))
            delivery.validate(attempt, report)
            with self.assertRaisesRegex(ValueError, "complete matrix"):
                delivery.validate(attempt, {**report, "steps": report["steps"][:-1]})
            changed = copy.deepcopy(report)
            changed["cases"][0]["rows"][1]["rounds"] = 42
            with self.assertRaisesRegex(ValueError, "raw execution"):
                delivery.validate(attempt, changed)
            Path(report["steps"][1]["stdout"]).write_text("wrong unit marker\n")
            with self.assertRaisesRegex(ValueError, "unit diagnostic"):
                delivery.validate(attempt, report)

    def test_capsule_rejects_claim_promotion_and_modified_index_or_archive(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            attempt, report = self.attempt(root)
            output = root / "evidence"
            index = delivery.package(output, [attempt])
            self.assertEqual(index, delivery.verify(output))
            for claim in analysis.CLAIMS:
                with self.subTest(claim=claim), self.assertRaisesRegex(ValueError, "claim boundary"):
                    delivery.validate(attempt, {**report, claim: True})
            changed = copy.deepcopy(index)
            changed["attempts"][0]["cases"][0]["rows"][0]["rounds"] = 99
            (output / "index.json").write_text(json.dumps(changed))
            with self.assertRaises(ValueError):
                delivery.verify(output)
            (output / "index.json").write_text(json.dumps(index))
            archive = output / index["attempts"][0]["archive"]
            archive.write_bytes(archive.read_bytes() + b"corrupt")
            with self.assertRaisesRegex(ValueError, "archive identity"):
                delivery.verify(output)

    def test_failed_attempt_remains_failed_and_preserves_errors(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            attempt, report = self.attempt(root, "FAILED_RETAINED")
            index = delivery.package(root / "evidence", [attempt])
            self.assertEqual(index["attempts"][0]["status"], "FAILED_RETAINED")
            self.assertEqual(index["attempts"][0]["errors"], report["errors"])
            self.assertTrue(all(index[claim] is False for claim in analysis.CLAIMS))

    def test_committed_matrix_replays_and_keeps_parser_failure(self):
        evidence = Path(__file__).resolve().parents[1] / GUIDE / "host_evidence"
        index = delivery.verify(evidence)
        self.assertEqual([entry["status"] for entry in index["attempts"]],
                         [analysis.PASS, "FAILED_RETAINED", analysis.PASS])
        latest = index["attempts"][-1]
        self.assertEqual(len(latest["cases"]), 9)
        self.assertEqual(sum(len(case["rows"]) for case in latest["cases"]), 27)
        self.assertTrue(all(index[claim] is False for claim in analysis.CLAIMS))
        with tarfile.open(evidence / latest["archive"]) as bundle:
            report = json.load(bundle.extractfile("results.json"))
            for case, result in zip(report["contract"]["cases"], latest["cases"], strict=True):
                raw = analysis.analyze(case, bundle.extractfile(case["case"] + ".stdout.txt").read().decode(),
                                       bundle.extractfile(case["case"] + ".stderr.txt").read().decode())
                self.assertEqual(raw, {key: result[key] for key in ("setup", "rows")})
        non_timing = lambda case: {"case": case["case"], "rows": [
            {key: value for key, value in row.items() if key not in analysis.TIMES} for row in case["rows"]]}
        self.assertEqual([non_timing(case) for case in index["attempts"][0]["cases"]],
                         [non_timing(case) for case in latest["cases"][:6]])
        warm = latest["cases"][6:]
        self.assertTrue(all(not row["fallback"] and row["seed_sources"] > 0
                            for case in warm for row in case["rows"][1:]))
        self.assertTrue(all(any(count > 0 for count in row["active_counts"])
                            for case in warm[:2] for row in case["rows"][1:]))
        self.assertTrue(all(row["active_counts"] == [0] for row in warm[2]["rows"]))

    def test_original_g_default_scope_preserves_all_eighteen_state_results(self):
        root = Path(__file__).resolve().parents[1] / GUIDE
        old = g_delivery.verify(root.parent / "continuous_board/guarded_host_evidence")["attempts"][0]
        new = g_delivery.verify(root / "g_regression_evidence")["attempts"][0]
        non_timing = lambda entry: [(case["case"], [{key: value for key, value in row.items()
                        if key not in g_analysis.TIMES} for row in case["rows"]]) for case in entry["cases"]]
        self.assertEqual(non_timing(old), non_timing(new))


if __name__ == "__main__":
    unittest.main()
