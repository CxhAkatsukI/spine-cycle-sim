"""Checked-core reuse and an explicit CPU-only resource policy are not timing knobs."""

import json
from pathlib import Path
import tempfile
import unittest

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.evaluation_impact.r_bank_stream import cached_core, runtime
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware import admission
from spine_cycle_sim.experiments.evaluation_impact.r_credits.freeze import pin


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
        for source in ("prefetch_compact", "prefetch_compact_test"):
            self.assertIn(str(self.root / f"cpp/tests/evaluation_impact/{source}.cpp"),
                          cached_core.command(self.root, core, Path("/output"), Path("/usr/bin/g++"), source))
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

    def capacity_reference(self):
        build = self.gates / "build"
        paths = [self.root / row["path"] for row in self.rows]
        for name in ("simulator/cpp/libspine_cycle_core.a", "simulator/cpp/liboriginal_regraph_cycle.a",
                     "CMakeCache.txt", "compile_commands.json"):
            path = build / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("frozen\n")
            paths.append(path)
        compiler = self.root / "compiler"
        compiler.write_text("compiler\n")
        paths.append(compiler)
        inputs = self.gates / "inputs/warm_update"
        inputs.mkdir(parents=True)
        (inputs / "graph.txt").write_text("graph\n")
        paths.append(inputs / "graph.txt")
        steps = []
        for name in ("build_core", "core_ctest"):
            path = self.gates / (name + ".stdout.txt")
            path.write_text("100% tests passed, 0 tests failed out of 37\n")
            steps.append(dict(stdout=str(path), exit_code=0, timed_out=False))
        reference = self.gates / "results.json"
        report = dict(status="PREFETCH_CAPACITY_COMPLETE_SIMULATOR_PREDICTION", pins_unchanged=True,
                      r_rows=[{}] * 12, failures=[], pins=[pin(p) for p in paths], steps=steps)
        reference.write_text(json.dumps(report))
        return reference, compiler

    def test_complete_convergence_core_reuse_is_fail_closed(self):
        reference, compiler = self.capacity_reference()
        core, evidence = cached_core.validate_convergence(self.root, reference, compiler)
        self.assertEqual(core, self.gates / "build/simulator/cpp")
        self.assertTrue(any(p["path"] == str(reference) for p in evidence))
        (self.root / "cpp/src/new.cpp").write_text("new\n")
        with self.assertRaisesRegex(ValueError, "omits"):
            cached_core.validate_convergence(self.root, reference, compiler)
        (self.root / "cpp/src/new.cpp").unlink()
        compiler.write_text("changed\n")
        with self.assertRaisesRegex(ValueError, "differs"):
            cached_core.validate_convergence(self.root, reference, compiler)

    def test_complete_convergence_cannot_hide_failed_tests_or_changed_input(self):
        reference, compiler = self.capacity_reference()
        stdout = self.gates / "core_ctest.stdout.txt"
        stdout.write_text("36 tests passed\n")
        with self.assertRaisesRegex(ValueError, "all 37"):
            cached_core.validate_convergence(self.root, reference, compiler)
        stdout.write_text("100% tests passed, 0 tests failed out of 37\n")
        (self.gates / "inputs/warm_update/graph.txt").write_text("changed\n")
        with self.assertRaisesRegex(ValueError, "differs"):
            cached_core.validate_convergence(self.root, reference, compiler)

    def test_gather_reference_requires_explicit_known_status(self):
        reference, compiler = self.capacity_reference()
        report = json.loads(reference.read_text())
        report["status"] = "GATHER_REUSE_COMPLETE_SIMULATOR_PREDICTION"
        reference.write_text(json.dumps(report))
        with self.assertRaises(ValueError):
            cached_core.validate_convergence(self.root, reference, compiler)
        cached_core.validate_convergence(self.root, reference, compiler, complete_status=report["status"])
        with self.assertRaisesRegex(ValueError, "unknown"):
            cached_core.validate_convergence(self.root, reference, compiler, complete_status="RUNNING")


if __name__ == "__main__":
    unittest.main()
