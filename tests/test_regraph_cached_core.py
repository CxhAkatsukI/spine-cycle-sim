"""Checked-core reuse and an explicit CPU-only resource policy are not timing knobs."""

import json
from pathlib import Path
import tempfile
import unittest

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.evaluation_impact.r_bank_stream import cached_core, runtime
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware import admission


class CachedCoreTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.gates = self.root / "gates"
        self.gates.mkdir()
        self.rows = []
        for name in ("cpp/src/model.cpp", "cpp/include/model.hpp", "CMakeLists.txt", "cpp/CMakeLists.txt"):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("frozen\n")
            self.rows.append({"path": name, "sha256": sha256_file(path)})
        self.snapshot = {"files": self.rows}
        self.summary = {"status": "PASS", "source_unchanged": True, "attempts": [
            {"name": name, "resources": {"exit_code": 0, "timed_out": False}}
            for name in ("core_build", "core_ctest")]}
        for name in ("core/CMakeCache.txt", "core/cpp/liboriginal_regraph_cycle.a",
                     "core/cpp/libspine_cycle_core.a", "source_archive.json"):
            path = self.gates / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("frozen\n")
        self.save()

    def save(self):
        (self.gates / "source_before.json").write_text(json.dumps(self.snapshot))
        (self.gates / "summary.json").write_text(json.dumps(self.summary))

    def test_validated_core_and_only_approved_entry_points(self):
        core, pins = cached_core.validate(self.root, self.gates)
        self.assertEqual(len(pins), 6)
        command = cached_core.command(self.root, core, Path("/output"), Path("/usr/bin/g++"), "convergence")
        self.assertIn("-O3", command)
        self.assertIn("-std=gnu++20", command)
        self.assertEqual(command[-2:], [str(core / "liboriginal_regraph_cycle.a"), str(core / "libspine_cycle_core.a")])
        floor = cached_core.command(self.root, core, Path("/output"), Path("/usr/bin/g++"), "adapter_floor")
        self.assertIn(str(self.root / "cpp/tests/evaluation_impact/adapter_floor.cpp"), floor)
        with self.assertRaises(ValueError):
            cached_core.command(self.root, core, Path("/output"), Path("/usr/bin/g++"), "unapproved")

    def test_new_or_changed_numerical_source_cannot_reuse_core(self):
        path = self.root / "cpp/src/new.cpp"
        path.write_text("new\n")
        with self.assertRaisesRegex(ValueError, "omits"):
            cached_core.validate(self.root, self.gates)
        path.unlink()
        (self.root / "cpp/include/model.hpp").write_text("changed\n")
        with self.assertRaisesRegex(ValueError, "differs"):
            cached_core.validate(self.root, self.gates)

    def test_failed_or_absent_complete_regression_cannot_reuse_core(self):
        self.summary["attempts"].pop()
        self.save()
        with self.assertRaisesRegex(ValueError, "build/test"):
            cached_core.validate(self.root, self.gates)

    def test_both_build_lists_must_be_present_in_snapshot(self):
        for name in ("CMakeLists.txt", "cpp/CMakeLists.txt"):
            self.snapshot["files"] = [row for row in self.rows if row["path"] != name]
            self.save()
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "omits"):
                cached_core.validate(self.root, self.gates)

    def test_cpu_budget_reserves_full_peers_and_keeps_own_zero_swap(self):
        selected = runtime.settings(runtime.CPU_ONLY, 4)
        self.assertEqual(selected["high_gib"], 3)
        peers = [{"bounded": True, "memory_max_bytes": 32 * 1024**3}] * 2
        self.assertEqual(admission.required_bytes(selected["policy"], peers), 80 * 1024**3)
        self.assertFalse(admission.eligible(79 * 1024**3, peers, selected["policy"]))
        with self.assertRaises(ValueError):
            runtime.settings(runtime.CPU_ONLY, 5)

    def test_foreign_swap_allowance_only_ignored_when_host_has_no_swap(self):
        proc, groups = self.root / "proc", self.root / "groups"
        (proc / "9").mkdir(parents=True)
        (proc / "9/cgroup").write_text("0::/foreign\n")
        (groups / "foreign").mkdir(parents=True)
        (groups / "foreign/memory.max").write_text(str(32 * 1024**3))
        (groups / "foreign/memory.swap.max").write_text("max")
        (proc / "meminfo").write_text("SwapTotal: 0 kB\n")
        with self.assertRaisesRegex(ValueError, "zero swap"):
            admission.budget(9, proc=proc, root=groups)
        _, amount = admission.budget(9, proc=proc, root=groups, host_swap_disabled=True)
        self.assertEqual(amount, 32 * 1024**3)
        (proc / "meminfo").write_text("SwapTotal: 1 kB\n")
        with self.assertRaisesRegex(ValueError, "SwapTotal"):
            admission.budget(9, proc=proc, root=groups, host_swap_disabled=True)
        (proc / "meminfo").write_text("SwapTotal: 0 kB\n")
        (groups / "foreign/memory.max").write_text("max")
        with self.assertRaisesRegex(ValueError, "no finite"):
            admission.budget(9, proc=proc, root=groups, host_swap_disabled=True)


if __name__ == "__main__":
    unittest.main()
