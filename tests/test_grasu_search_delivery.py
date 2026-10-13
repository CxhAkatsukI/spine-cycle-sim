import copy
import hashlib
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from tests import test_grasu_search_concurrency
from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.evaluation_impact.common_g.search_concurrency.analysis import analyze
from spine_cycle_sim.experiments.evaluation_impact.common_g.search_concurrency.delivery import package
from spine_cycle_sim.experiments.evaluation_impact.common_g.search_concurrency import verification


class SearchDeliveryTests(unittest.TestCase):
    def test_historical_audit_requires_exact_declared_delta(self):
        added = ["cpp/include/spine_sim/original_grasu/types.hpp",
                 "cpp/src/original_grasu/hot_store.cpp", "cpp/tests/original_grasu/system.hpp"]
        for fault in (None, "extra", "removed", "previous"):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                previous = root / "previous/python-verification-v2/historical.json"
                previous.parent.mkdir(parents=True)
                old = {"status": "HISTORICAL_IDENTITY_FAILURES_RETAINED", "identity_drift": {
                    "current_mismatched_subassertions": 27,
                    "mismatched_paths_with_repetitions": ["cpp/src/prior.cpp"] * 27}}
                if fault == "previous": old["identity_drift"]["current_mismatched_subassertions"] = 26
                previous.write_text(json.dumps(old))
                files = ["cpp/src/prior.cpp"] * 27 + added
                if fault == "extra": files.append("cpp/src/undeclared.cpp")
                if fault == "removed": files.pop(0)
                rows = []
                for name in files:
                    path = root / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(b"changed")
                    rows.append({"path": name, "sha256": "0" * 64})
                manifests = {
                    "docs/repository/sst_spine_refactor/spine_equivalence.json": {
                        "candidate_identity": {"source": {"files": rows[:-1]}}},
                    "docs/experiments/comparisons/grasu_regraph_stage_validation/finite_grasu_results.json": {
                        "model": {"files": rows[-1:]}}}
                for name, value in manifests.items():
                    path = root / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(json.dumps(value))
                with patch.object(verification, "ROOT", root):
                    if fault:
                        with self.assertRaises(ValueError): verification.historical_identity(root / "previous")
                    else:
                        report = verification.historical_identity(root / "previous")
                        self.assertEqual(report["current_mismatched_subassertions"], 30)
                        self.assertEqual(report["newly_changed_paths"], added)
                        self.assertFalse(report["suite_reported_green"])

    def test_complete_delivery_and_rejection_of_unsupported_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pin = root / "pin"
            pin.write_bytes(b"complete state")
            report, previous = test_grasu_search_concurrency.SearchConcurrencyTests().fixture()
            for value in (report, previous):
                for row in value["rows"]:
                    row["state_sha256"] = sha256_file(pin)
            for row in report["rows"]:
                (root / f'lat{row["latency"]}_{row["case"]}_{row["arm"]}.u32le').write_bytes(pin.read_bytes())
            report.update(analyze(report, previous), steps=[],
                pins=[{"path": str(pin), "sha256": sha256_file(pin)}],
                status="G_SEARCH_CONCURRENCY_VALIDATED_REFERENCE_TIMING_OPEN")
            matrix, old = root / "matrix.json", root / "old.json"
            matrix.write_text(json.dumps(report))
            old.write_text(json.dumps(previous))
            result = package(root / "evidence", matrix, old)
            self.assertEqual(result["prediction_rows"], 266)
            self.assertEqual(result["old_checkpoint_exact_rows"], 190)
            self.assertFalse(result["baseline_admitted"])
            for fault in ("summary", "pin", "state", "status"):
                bad = copy.deepcopy(report)
                if fault == "summary": bad["old_checkpoint_exact_rows"] = 189
                if fault == "pin": bad["pins"][0]["sha256"] = "0" * 64
                if fault == "state":
                    row = bad["rows"][-1]
                    (root / f'lat{row["latency"]}_{row["case"]}_{row["arm"]}.u32le').write_bytes(b"changed")
                if fault == "status": bad["status"] = "RUNNING"
                matrix.write_text(json.dumps(bad))
                with self.assertRaises(ValueError): package(root / fault, matrix, old)

    def verification_fixture(self, root):
        base, previous = root / "new", root / "old"

        def write(name, value):
            path = base / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(value))

        def step(name, code=0, stderr=""):
            prefix = base / name
            prefix.parent.mkdir(parents=True, exist_ok=True)
            stdout_path, stderr_path = Path(str(prefix) + ".stdout.txt"), Path(str(prefix) + ".stderr.txt")
            stdout_path.write_text("100% tests passed, 0 tests failed out of 31")
            stderr_path.write_text(stderr)
            result = {"exit_code": code, "timed_out": False,
                      "stdout": str(stdout_path), "stderr": str(stderr_path)}
            write(name + ".resources.json", result)
            return result

        write("core-verification.json", {"status": "FRESH_CORE_REGRESSIONS_PASS",
            "steps": [step("core" + str(i)) for i in range(3)]})
        write("sst-verification/results.json", {"status": "DEFAULT_SST_SMOKES_PASS_NOT_CANDIDATE_TIMING",
            "steps": [step("sst" + str(i)) for i in range(3)]})
        write("sst-verification/build.json", step("sst-build"))
        write("python-verification/results.json", {"status": "FOCUSED_PASS", "tests_run": 2,
            "steps": [step("python", stderr="Ran 2 tests in 0.1s\nOK\n")]})
        write("python-verification/historical.json", {"status": "HISTORICAL_IDENTITY_FAILURES_RETAINED",
            "identity_drift": {"retained": True}, "step": step("historical", 1)})
        for name in ("memory/summary.json", "native/result.json"):
            write("sst-verification/" + name, {"exact": True})
            old = previous / "sst-verification" / name
            old.parent.mkdir(parents=True, exist_ok=True)
            old.write_text('{"exact":true}')
        for name in ("freeze/manifest.json", "freeze/sources.tar.gz", "core/CMakeCache.txt",
                "core/compile_commands.json", "core/cpp/libspine_cycle_core.a",
                "core/cpp/liboriginal_grasu_cycle.a", "sst/libspine_cycle.so",
                "matrix/build/common_g_execution"):
            write(name, {})
        return base, previous

    def test_verification_keeps_historical_failure_and_default_sst_boundary(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(verification, "historical_identity", return_value={"retained": True}):
            root = Path(directory)
            base, previous = self.verification_fixture(root)
            report = verification.package(base, previous, root / "evidence")
            self.assertEqual(report["core_tests"], 31)
            self.assertEqual(report["focused_python_tests"], 2)
            self.assertEqual(len(report["checks"]), 9)
            self.assertFalse(report["candidate_sst_timing_admitted"])
            self.assertEqual(report["checks"][-1]["expected_exit_code"], 1)
            with tarfile.open(root / "evidence/regressions.tar.gz") as archive:
                self.assertEqual(len(archive.getnames()), len(report["members"]))
                for item in report["members"]:
                    self.assertEqual(hashlib.sha256(archive.extractfile(item["member"]).read()).hexdigest(), item["sha256"])

    def test_incomplete_verification_cannot_be_delivered(self):
        for fault in ("scope", "core-count", "python-count", "sst", "history", "resources"):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as directory, \
                    patch.object(verification, "historical_identity", return_value={"retained": True}):
                root = Path(directory)
                base, previous = self.verification_fixture(root)
                if fault == "scope":
                    path = base / "sst-verification/results.json"
                    value = json.loads(path.read_text()); value["steps"].pop(); path.write_text(json.dumps(value))
                if fault == "core-count": (base / "core2.stdout.txt").write_text("30 tests pass")
                if fault == "python-count": (base / "python.stderr.txt").write_text("Ran 1 test in 0.1s")
                if fault == "sst": (previous / "sst-verification/memory/summary.json").write_text("{}")
                if fault == "history": (base / "python-verification/historical.json").write_text('{"status":"GREEN"}')
                if fault == "resources": (base / "core0.resources.json").write_text("{}")
                with self.assertRaises(ValueError): verification.package(base, previous, root / "rejected")


if __name__ == "__main__":
    unittest.main()
