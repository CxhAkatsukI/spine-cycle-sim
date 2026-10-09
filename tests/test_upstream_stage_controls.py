from __future__ import annotations

import copy
import json
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.upstream_controls.execution import (
    dependency_identities, run_bounded,
)
from spine_cycle_sim.experiments.upstream_controls.sources import (
    merger_invocation, verify_snapshot,
)
from spine_cycle_sim.experiments.upstream_controls.validation import (
    validate_contract, validate_probe,
)


ROOT = Path(__file__).resolve().parents[1]


class UpstreamControlContractTests(unittest.TestCase):
    def setUp(self):
        self.contract = json.loads((ROOT / (
            "configs/experiments/grasu_regraph_upstream_controls_v2.json")).read_text())

    def test_predeclared_matrix_and_previous_little_matrix_are_valid(self):
        validate_contract(self.contract)
        validate_contract(json.loads((ROOT / (
            "configs/experiments/grasu_regraph_upstream_controls_v1.json")).read_text()))

    def test_empty_duplicate_or_unsafe_matrix_cannot_pass_vacuously(self):
        for field in ("probes", "topologies"):
            for mutate in (lambda rows: [], lambda rows: rows + rows[:1],
                           lambda rows: [{**rows[0], "id": "../escape"}]):
                contract = copy.deepcopy(self.contract)
                contract[field] = mutate(contract[field])
                with self.subTest(field=field, mutate=mutate), self.assertRaises(ValueError):
                    validate_contract(contract)

    def test_resource_limits_are_explicit_positive_and_reserved(self):
        for field in ("memory_limit_gib", "reserve_gib", "compile_timeout_seconds",
                      "run_timeout_seconds"):
            for value in (0, -1, True, "2"):
                contract = copy.deepcopy(self.contract)
                contract[field] = value
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    validate_contract(contract)
        self.contract["reserve_gib"] = 15
        with self.assertRaises(ValueError):
            validate_contract(self.contract)

    def test_topology_labels_do_not_replace_source_or_resource_identity(self):
        for mutation in ("counts", "source", "missing", "zero_big"):
            contract = copy.deepcopy(self.contract)
            if mutation == "counts":
                contract["probes"][1]["expected"]["little"] = 11
            elif mutation == "source":
                contract["probes"][1]["source"] = "../../anything.cpp"
            elif mutation == "missing":
                contract["probes"][1]["topology"] = "absent"
            else:
                contract["probes"][-1]["topology"] = "a4"
                contract["probes"][-1]["expected"].update(little=4, big=0)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                validate_contract(contract)

    def test_exact_typed_result_not_only_pass_boolean_is_required(self):
        expected = self.contract["probes"][1]["expected"]
        line = "PUBLICATION_PROBE " + json.dumps(expected)
        self.assertEqual(validate_probe(line, expected), expected)
        for mutate in (lambda row: row.update(physical_edges=1),
                       lambda row: row.update(physical_edges=1584.0),
                       lambda row: row.update(device_cycles=100)):
            observed = copy.deepcopy(expected)
            mutate(observed)
            with self.assertRaises(ValueError):
                validate_probe("PUBLICATION_PROBE " + json.dumps(observed), expected)

    def test_leftover_stream_warning_duplicate_or_missing_result_rejects(self):
        expected = self.contract["probes"][0]["expected"]
        line = "PUBLICATION_PROBE " + json.dumps(expected)
        for stdout in ("", line + "\n" + line,
                       line + "\nWARNING [HLS SIM]: leftover data"):
            with self.assertRaises(ValueError):
                validate_probe(stdout, expected)


class UpstreamControlSourceTests(unittest.TestCase):
    def test_merger_call_uses_exact_number_of_upstream_inputs(self):
        four = merger_invocation(4)
        self.assertIn("kernelLittleGSMerger(inputs[0], inputs[1], inputs[2], inputs[3], output)", four)
        self.assertNotIn("inputs[4]", four)
        for value in (0, 15, True, "4"):
            with self.assertRaises(ValueError):
                merger_invocation(value)

    def test_wrong_revision_dirty_snapshot_and_changed_file_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.cpp"
            source.write_text("original\n")
            pin = {"id": "example", "revision": "abc", "files": [
                {"path": "source.cpp", "sha256": sha256_file(source)}]}
            with patch("subprocess.check_output", side_effect=["abc\n", ""]):
                self.assertEqual(verify_snapshot(root, pin)["revision"], "abc")
            for answers in (["wrong\n", ""], ["abc\n", " M source.cpp"]):
                with patch("subprocess.check_output", side_effect=answers), self.assertRaises(ValueError):
                    verify_snapshot(root, pin)
            source.write_text("changed\n")
            with patch("subprocess.check_output", side_effect=["abc\n", ""]), self.assertRaises(ValueError):
                verify_snapshot(root, pin)

    def test_dependency_hashes_include_escaped_path_and_continuation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "a.cpp").write_text("a")
            (root / "b c.hpp").write_text("b")
            dependencies = root / "probe.d"
            dependencies.write_text("probe: a.cpp \\\n b\\ c.hpp\n")
            identities = dependency_identities(dependencies, root)
            self.assertEqual({row["path"] for row in identities},
                             {str(root / "a.cpp"), str(root / "b c.hpp")})
            dependencies.write_text("unexpected: a.cpp\n")
            with self.assertRaises(ValueError):
                dependency_identities(dependencies, root)


class UpstreamControlExecutionTests(unittest.TestCase):
    @patch("spine_cycle_sim.experiments.upstream_controls.execution.available_memory_bytes",
           return_value=32 * 1024**3)
    def test_success_and_nonzero_exit_preserve_output_and_rss(self, _available):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for code in (0, 3):
                prefix = root / f"case{code}"
                record = run_bounded(
                    [sys.executable, "-c", f"print('preserved'); raise SystemExit({code})"],
                    root, prefix, timeout=5, memory_gib=1, reserve_gib=16)
                self.assertEqual(record["exit_code"], code)
                self.assertFalse(record["timed_out"])
                self.assertGreater(record["peak_rss_kib"], 0)
                self.assertIn("preserved", Path(record["stdout"]).read_text())
                self.assertTrue(prefix.with_suffix(".resources.json").is_file())

    @patch("spine_cycle_sim.experiments.upstream_controls.execution.available_memory_bytes",
           return_value=32 * 1024**3)
    def test_timeout_kills_and_reaps_the_process(self, _available):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            record = run_bounded([sys.executable, "-c", "import time; time.sleep(30)"],
                                  root, root / "timeout", timeout=1, memory_gib=1,
                                  reserve_gib=16)
            self.assertTrue(record["timed_out"])
            self.assertEqual(record["exit_code"], -signal.SIGKILL)
            self.assertLess(record["wall_seconds"], 5)

    @patch("spine_cycle_sim.experiments.upstream_controls.execution.available_memory_bytes",
           return_value=16 * 1024**3)
    def test_memory_guard_refuses_before_spawning(self, _available):
        with patch.object(subprocess, "Popen") as spawn, self.assertRaises(RuntimeError):
            run_bounded(["anything"], ROOT, ROOT / "not_created", timeout=1,
                        memory_gib=1, reserve_gib=16)
        spawn.assert_not_called()


if __name__ == "__main__":
    unittest.main()
