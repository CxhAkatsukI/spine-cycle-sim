from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

from spine_cycle_sim.experiments.refactor_equivalence import (
    case_command, compare_result_payloads, compare_runs, verify_source_snapshot,
)
from spine_cycle_sim.experiments.campaign_runtime import sha256_file


class RefactorEquivalenceTests(unittest.TestCase):
    def test_all_result_fields_are_compared(self) -> None:
        result = {"success": True, "cycles": 100, "bytes": 64,
                  "fifo_stalls": 7, "arbitration": {"ledger_closed": True}}
        self.assertTrue(compare_result_payloads(result, dict(result))["equivalent"])
        for field in ("cycles", "bytes", "fifo_stalls", "arbitration"):
            candidate = copy.deepcopy(result)
            candidate[field] = None
            self.assertEqual(compare_result_payloads(result, candidate)["changed_fields"], [field])

    def test_new_null_field_is_not_confused_with_an_absent_field(self) -> None:
        before = {"success": True}
        after = {"success": True, "new_field": None}
        self.assertFalse(compare_result_payloads(before, after)["equivalent"])

    def test_failed_correctness_is_not_equivalence_evidence(self) -> None:
        result = {"success": False, "cycles": 100}
        with self.assertRaisesRegex(ValueError, "correctness"):
            compare_result_payloads(result, result)

    def test_command_keeps_profile_and_semantics_explicit(self) -> None:
        root = Path("/repo")
        case = {"runner": "scripts/run.py", "profile": "profile.json",
                "workload": "initial.slice", "updates": "update.slice",
                "arguments": ["--hardware-warm-sssp"]}
        command = case_command(root, case, Path("/plugin"), Path("/output"))
        self.assertIn("--no-build", command)
        self.assertIn("--hardware-warm-sssp", command)
        self.assertEqual(command[command.index("--lib-dir") + 1], "/plugin")
        self.assertEqual(command[command.index("--profile") + 1], "/repo/profile.json")
        self.assertIn("240s", command)
        self.assertIn("600s", case_command(
            root, case, Path("/plugin"), Path("/output"), timeout_seconds=600))
        with self.assertRaisesRegex(ValueError, "positive"):
            case_command(root, case, Path("/plugin"), Path("/output"), timeout_seconds=0)

    def test_source_or_input_mutation_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.cpp"
            source.write_text("original")
            snapshot = {"files": [{"path": "source.cpp", "sha256": sha256_file(source)}]}
            verify_source_snapshot(root, snapshot)
            source.write_text("changed")
            with self.assertRaisesRegex(ValueError, "changed during"):
                verify_source_snapshot(root, snapshot)
            source.unlink()
            with self.assertRaisesRegex(ValueError, "changed during"):
                verify_source_snapshot(root, snapshot)

    def fixture(self, parent: Path):
        directories = [parent / "before", parent / "after"]
        contract = {"cases": [{"id": "example", "manifest": "manifest.json"}]}
        for index, directory in enumerate(directories):
            case_dir = directory / "cases/example"
            case_dir.mkdir(parents=True)
            identity = {
                "contract_sha256": "same-contract", "plugin_sha256": f"plugin-{index}",
                "source": {"compiler": "same-compiler", "declared_build": {"flags": "-O3"},
                           "dramsim3_library_sha256": "same-dram"},
            }
            (directory / "identity.json").write_text(json.dumps(identity))
            (case_dir / "result.json").write_text(json.dumps(
                {"success": True, "cycles": 100, "backend_requests": 20}))
            (case_dir / "manifest.json").write_text(json.dumps(
                {"status": "PASS", "sst_plugin_sha256": f"plugin-{index}",
                 "profile_sha256": "same-profile", "workload_sha256": "same-workload"}))
        return contract, directories

    def test_compares_distinct_plugins_without_ignoring_result_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            contract, directories = self.fixture(Path(temporary))
            report = compare_runs(contract, *directories)
            self.assertEqual(report["status"], "PASS")
            self.assertEqual(report["ignored_result_fields"], [])

    def test_equal_cycles_with_different_inputs_is_a_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            contract, directories = self.fixture(Path(temporary))
            path = directories[1] / "cases/example/manifest.json"
            manifest = json.loads(path.read_text())
            manifest["workload_sha256"] = "different-workload"
            path.write_text(json.dumps(manifest))
            report = compare_runs(contract, *directories)
            self.assertEqual(report["status"], "FAIL")
            self.assertEqual(report["cases"][0]["changed_manifest_identities"], ["workload_sha256"])

    def test_wrong_plugin_or_changed_compiler_is_rejected(self) -> None:
        for field in ("plugin_sha256", "compiler"):
            with tempfile.TemporaryDirectory() as temporary:
                contract, directories = self.fixture(Path(temporary))
                path = directories[1] / "identity.json"
                identity = json.loads(path.read_text())
                if field == "compiler":
                    identity["source"][field] = "different"
                else:
                    identity[field] = "different"
                path.write_text(json.dumps(identity))
                with self.assertRaises(ValueError):
                    compare_runs(contract, *directories)


if __name__ == "__main__":
    unittest.main()
