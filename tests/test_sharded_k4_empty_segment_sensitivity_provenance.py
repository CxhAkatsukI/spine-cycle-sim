"""Synthetic source, executable and execution-contract provenance checks."""

import copy
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from spine_cycle_sim.experiments.sharded_k4_stages.empty_segment.sensitivity import recheck, study


def digest(payload):
    return hashlib.sha256(payload).hexdigest()


class SensitivityProvenanceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.temporary = Path(temporary.name)
        self.root = self.temporary / "repo"
        self.run = self.temporary / "sensitivity-v2"
        self.binary = self.run / "build/routed_regraph_empty_segment_round"
        self.cache = self.run / "build/CMakeCache.txt"
        self.outer_path = self.run.with_name(self.run.name + "_watchdog.resources.json")
        self.make_fixture()

    def write(self, path, payload):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)

    def write_json(self, path, value):
        self.write(path, json.dumps(value).encode("ascii"))

    def resource(self, argv, budget, timeout):
        return {
            "command": argv, "cwd": str(self.root), "exit_code": 0,
            "stop_reason": "process_exit", "wall_seconds": 0.01,
            "peak_tree_rss_kib": 65536,
            "rss_scope": "sampled_simultaneous_tree_sum_shared_pages_counted_per_process",
            "minimum_available_bytes": 32 * 1024**3, "available_before_bytes": 48 * 1024**3,
            "tree_memory_gib": budget, "reserve_gib": 16,
            "per_process_address_space_gib": 64, "host_affinity": [2, 4],
            "timeout_seconds": timeout,
            "cleanup_scope": "pidfd_bound_observed_workers_not_cgroup_containment",
            "observed_pids": [12345], "cleanup_signaled_pids": [], "cleanup_snapshot_error": None,
        }

    def make_fixture(self):
        self.root.mkdir(parents=True, exist_ok=True)
        self.write(self.binary, b"synthetic-executor-v1")
        self.write(self.cache, b"CMAKE_BUILD_TYPE:STRING=Release\nBUILD_TESTING:BOOL=OFF\n")
        basis_directory = self.temporary / "partition-v6"
        production_directory = self.temporary / "production-v2"
        self.basis = {
            "cases": [{"mode": mode, "latency": latency, "reverse": reverse}
                      for mode, latency in (("cold", 64), ("warm_update", 64), ("warm_update", 128))
                      for reverse in (0, 1)],
            "inputs": [{"mode": mode, "path": str(basis_directory / "inputs" / mode)}
                       for mode in ("cold", "warm_update")],
        }
        self.report = {
            "schema_version": 2, "runs": [], "cpu_affinity": [2, 4],
            "python_executable": "/usr/bin/python3",
            "basis": {"path": str(basis_directory / "results.json")},
            "production": {"path": str(production_directory / "results.json")},
            "executor": {"path": str(self.binary), "sha256": digest(self.binary.read_bytes())},
            "cmake_cache_sha256": digest(self.cache.read_bytes()),
        }
        commands = [
            ("configure", ["cmake", "-S", str(self.root / "cpp/tests/routed_regraph/empty_segment"),
                           "-B", str(self.run / "build"), "-DCMAKE_BUILD_TYPE=Release",
                           "-DBUILD_TESTING=OFF"], 6, 300),
            ("build", ["cmake", "--build", str(self.run / "build"), "--target",
                       "routed_regraph_empty_segment_round", "-j2"], 6, 600),
            ("compiler", ["c++", "--version"], 1, 30),
        ]
        for case in self.basis["cases"]:
            mode, latency, reverse = (case[key] for key in ("mode", "latency", "reverse"))
            for arm in (73, 0):
                label = f"{mode}_lat{latency}_reverse{reverse}_empty{arm}"
                commands.append((label, [str(self.binary), str(basis_directory / "inputs" / mode),
                                        str(self.run / "states" / label), str(latency), str(reverse),
                                        "100000000", str(arm)], 3, 180))
        for label, argv, budget, timeout in commands:
            resource = self.resource(argv, budget, timeout)
            self.write_json(self.run / "raw" / (label + ".resources.json"), resource)
            self.report["runs"].append({"label": label, **copy.deepcopy(resource)})
        outer = ["/usr/bin/python3", "-m",
                 "spine_cycle_sim.experiments.sharded_k4_stages.empty_segment.sensitivity.study",
                 "--worker", "--output", str(self.run), "--basis", str(basis_directory),
                 "--production", str(production_directory)]
        self.write_json(self.outer_path, self.resource(outer, 8, 1800))

    def check(self):
        recheck.check_commands(self.root, self.run, self.report, self.basis)

    def change_resource(self, label, key, value, *, synchronize=True):
        path = self.run / "raw" / (label + ".resources.json")
        resource = json.loads(path.read_text())
        resource[key] = value
        self.write_json(path, resource)
        if synchronize:
            record = next(row for row in self.report["runs"] if row["label"] == label)
            record[key] = copy.deepcopy(value)

    def test_require_executor_accepts_unchanged_bytes(self):
        self.assertIsNone(study.require_executor(self.report["executor"]))

    def test_require_executor_rejects_changed_bytes(self):
        self.binary.write_bytes(b"synthetic-executor-v2")
        with self.assertRaisesRegex(ValueError, "executable changed"):
            study.require_executor(self.report["executor"])

    def test_require_executor_rejects_missing_file(self):
        self.binary.unlink()
        with self.assertRaises(FileNotFoundError):
            study.require_executor(self.report["executor"])

    def test_require_executor_rejects_identical_and_dangling_symlinks(self):
        target = self.temporary / "executor-target"
        target.write_bytes(self.binary.read_bytes())
        self.binary.unlink()
        self.binary.symlink_to(target)
        with self.assertRaisesRegex(ValueError, "executable changed"):
            study.require_executor(self.report["executor"])
        target.unlink()
        with self.assertRaisesRegex(ValueError, "executable changed"):
            study.require_executor(self.report["executor"])

    def test_pins_unions_previous_partition_harness_and_loaded_local_owners(self):
        previous = ("cpp/src/regraph_pma_adapter.cpp",
                    "cpp/tests/original_regraph/sssp/real_input.hpp")
        partition = ("spine_cycle_sim/experiments/original_regraph_execution/sssp_partition_round/analysis.py",
                     "spine_cycle_sim/experiments/original_regraph_execution/sssp_partition_round/delivery.py",
                     "spine_cycle_sim/experiments/sharded_k4_stages/link_runtime.py")
        loaded = ("spine_cycle_sim/experiments/sharded_k4_stages/process_cleanup.py",
                  "spine_cycle_sim/experiments/sharded_k4_stages/empty_segment/production_validation.py",
                  "spine_cycle_sim/experiments/original_regraph_validation/analysis.py")
        package = "spine_cycle_sim/experiments/sharded_k4_stages/empty_segment/sensitivity/"
        current = tuple(package + name for name in ("__init__.py", "study.py", "analysis.py", "recheck.py"))
        harness = tuple("cpp/tests/routed_regraph/empty_segment/" + name
                        for name in ("CMakeLists.txt", "round.cpp", "README.md"))
        expected = set(previous + partition + loaded + current + harness)
        for relative in expected:
            self.write(self.root / relative, relative.encode("ascii"))
        predecessor = self.temporary / "old-real-round.json"
        self.write_json(predecessor, {"sources": [{"path": relative} for relative in previous]})
        basis = {"basis": {"path": str(predecessor)},
                 "sources": [{"path": relative} for relative in (*partition, previous[0])]}
        excluded = (self.root / "spine_cycle_sim/native.so", self.root / "unrelated/owner.py",
                    self.temporary / "external.py")
        for path in excluded:
            self.write(path, b"not a local Python owner")
        modules = {str(index): SimpleNamespace(__file__=str(path))
                   for index, path in enumerate([*(self.root / name for name in loaded),
                                                 self.root / previous[0], *excluded])}
        modules["without_file"] = SimpleNamespace()
        modules["none"] = None
        with mock.patch.object(study, "__file__", str(self.root / (package + "study.py"))), \
                mock.patch.object(study, "sys", SimpleNamespace(modules=modules)):
            pins = study.pins(self.root, basis)
            self.assertEqual(pins, [{"path": relative, "sha256": digest(relative.encode("ascii"))}
                                    for relative in sorted(expected)])
            changed = self.root / loaded[0]
            changed.write_bytes(b"changed runtime owner")
            updated = study.pins(self.root, basis)
        self.assertNotEqual(updated, pins)
        self.assertEqual(next(pin["sha256"] for pin in updated if pin["path"] == loaded[0]),
                         digest(b"changed runtime owner"))

    def test_complete_command_matrix_checks_all_resource_budgets(self):
        with mock.patch.object(recheck, "require_execution", wraps=recheck.require_execution) as require:
            self.check()
        self.assertEqual(len(self.report["runs"]), 15)
        self.assertEqual([call.kwargs for call in require.call_args_list],
                         [{"budget": budget, "timeout": timeout}
                          for budget, timeout in ((6, 300), (6, 600), (1, 30),
                                                  *((3, 180),) * 12, (8, 1800))])

    def test_case_command_arguments_cannot_be_changed_even_with_matching_raw_record(self):
        label = "cold_lat64_reverse0_empty73"
        for index, value in enumerate(("/other/executor", "/other/input", "/other/output",
                                       "128", "1", "99999999", "0")):
            with self.subTest(argument=index):
                self.make_fixture()
                argv = next(row["command"] for row in self.report["runs"] if row["label"] == label).copy()
                argv[index] = value
                self.change_resource(label, "command", argv)
                with self.assertRaisesRegex(ValueError, "raw command or resource"):
                    self.check()

    def test_build_flags_and_raw_working_directory_are_bound(self):
        for label, key, value in (("configure", "command", ["cmake", "-DBUILD_TESTING=ON"]),
                                  ("build", "command", ["cmake", "--build", "other", "-j8"]),
                                  ("compiler", "command", ["other-c++", "--version"]),
                                  ("cold_lat64_reverse0_empty73", "cwd", str(self.temporary))):
            with self.subTest(label=label, key=key):
                self.make_fixture()
                self.change_resource(label, key, value)
                with self.assertRaisesRegex(ValueError, "raw command or resource"):
                    self.check()

    def test_missing_duplicate_and_reordered_execution_records_are_rejected(self):
        for change in ("missing", "duplicate", "reordered"):
            with self.subTest(change=change):
                self.make_fixture()
                if change == "missing":
                    self.report["runs"].pop()
                elif change == "duplicate":
                    self.report["runs"][-1] = copy.deepcopy(self.report["runs"][-2])
                else:
                    self.report["runs"][-2:] = self.report["runs"][-2:][::-1]
                with self.assertRaises(ValueError):
                    self.check()

    def test_raw_resource_must_exactly_match_report_record(self):
        for side in ("raw", "report"):
            with self.subTest(side=side):
                self.make_fixture()
                label = "cold_lat64_reverse0_empty73"
                if side == "raw":
                    self.change_resource(label, "wall_seconds", 2.0, synchronize=False)
                else:
                    self.report["runs"][3]["wall_seconds"] = 2.0
                with self.assertRaisesRegex(ValueError, "raw command or resource"):
                    self.check()

    def test_each_execution_kind_enforces_budget_and_timeout(self):
        for label, budget, timeout in (("configure", 6, 300), ("build", 6, 600),
                                       ("compiler", 1, 30), ("cold_lat64_reverse0_empty73", 3, 180)):
            for key, value in (("tree_memory_gib", budget + 1), ("timeout_seconds", timeout + 1)):
                with self.subTest(label=label, key=key):
                    self.make_fixture()
                    self.change_resource(label, key, value)
                    with self.assertRaisesRegex(ValueError, "resource/cleanup gate"):
                        self.check()

    def test_execution_failure_cleanup_rss_and_reserve_are_rejected(self):
        for key, value in (("exit_code", 1), ("stop_reason", "timeout"),
                           ("cleanup_snapshot_error", "ps failed"), ("reserve_gib", 15),
                           ("peak_tree_rss_kib", 3 * 1024**2 + 1),
                           ("minimum_available_bytes", 16 * 1024**3 - 1)):
            with self.subTest(key=key):
                self.make_fixture()
                self.change_resource("cold_lat64_reverse0_empty73", key, value)
                with self.assertRaisesRegex(ValueError, "resource/cleanup gate"):
                    self.check()

    def test_resource_affinity_requires_exact_values_order_and_types(self):
        for affinity in ([2], [4, 2], [2.0, 4]):
            with self.subTest(affinity=affinity):
                self.make_fixture()
                self.change_resource("cold_lat64_reverse0_empty73", "host_affinity", affinity)
                with self.assertRaisesRegex(ValueError, "raw command or resource"):
                    self.check()
        self.make_fixture()
        self.report["cpu_affinity"] = [2]
        with self.assertRaisesRegex(ValueError, "raw command or resource"):
            self.check()

    def test_executor_pin_and_actual_bytes_are_bound(self):
        for change in ("path", "hash", "bytes"):
            with self.subTest(change=change):
                self.make_fixture()
                if change == "path":
                    self.report["executor"]["path"] = str(self.temporary / "other-executor")
                elif change == "hash":
                    self.report["executor"]["sha256"] = "0" * 64
                else:
                    self.binary.write_bytes(b"synthetic-executor-v2")
                with self.assertRaisesRegex(ValueError, "standalone executable or compiler configuration"):
                    self.check()

    def test_cache_pin_and_actual_bytes_are_bound(self):
        for change in ("hash", "bytes"):
            with self.subTest(change=change):
                self.make_fixture()
                if change == "hash":
                    self.report["cmake_cache_sha256"] = "0" * 64
                else:
                    self.cache.write_bytes(b"CMAKE_BUILD_TYPE:STRING=Debug\n")
                with self.assertRaisesRegex(ValueError, "standalone executable or compiler configuration"):
                    self.check()

    def test_outer_command_cwd_and_affinity_are_bound(self):
        for index, value in ((0, "/other/python"), (2, "other.module"), (3, "--not-worker"),
                             (5, "/other/run"), (7, "/other/basis"), (9, "/other/production")):
            with self.subTest(argument=index):
                self.make_fixture()
                outer = json.loads(self.outer_path.read_text())
                outer["command"][index] = value
                self.write_json(self.outer_path, outer)
                with self.assertRaisesRegex(ValueError, "outer watchdog command or affinity"):
                    self.check()
        for key, value in (("cwd", str(self.temporary)), ("host_affinity", [4, 2]),
                           ("host_affinity", [2.0, 4])):
            with self.subTest(key=key, value=value):
                self.make_fixture()
                outer = json.loads(self.outer_path.read_text())
                outer[key] = value
                self.write_json(self.outer_path, outer)
                with self.assertRaisesRegex(ValueError, "outer watchdog command or affinity"):
                    self.check()

    def test_outer_resources_enforce_success_budget_timeout_and_reserve(self):
        for key, value in (("exit_code", 1), ("stop_reason", "tree_rss_budget"),
                           ("cleanup_snapshot_error", "snapshot failed"), ("tree_memory_gib", 9),
                           ("timeout_seconds", 1801), ("reserve_gib", 15),
                           ("peak_tree_rss_kib", 8 * 1024**2 + 1),
                           ("minimum_available_bytes", 16 * 1024**3 - 1)):
            with self.subTest(key=key):
                self.make_fixture()
                outer = json.loads(self.outer_path.read_text())
                outer[key] = value
                self.write_json(self.outer_path, outer)
                with self.assertRaisesRegex(ValueError, "resource/cleanup gate"):
                    self.check()


if __name__ == "__main__":
    unittest.main()
