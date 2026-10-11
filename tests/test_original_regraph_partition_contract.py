"""Mutation checks for command/report contracts and static PMA work."""

import copy
from pathlib import Path
import tempfile
import unittest

from spine_cycle_sim.experiments.original_regraph_execution.sssp_partition_round.analysis import MATRIX
from spine_cycle_sim.experiments.original_regraph_execution.sssp_partition_round.contract import (
    SCOPE, execution_contract, watchdog_contract, worker_command)
from spine_cycle_sim.experiments.original_regraph_execution.sssp_partition_round.layout_audit import audit, bind_traffic
from spine_cycle_sim.experiments.original_regraph_execution.sssp_real_round.preparation import write_words


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.root, self.run = Path("/repository"), Path("/experiment")
        self.basis = {key: {"identity": key} for key in ("memory", "model", "boundary", "compiler_version", "cmake_cache")}
        self.basis["probe"] = {"binary": "/probe"}
        self.report = {**copy.deepcopy(self.basis), "schema_version": 2, "scope": SCOPE,
                       "declared_matrix": [list(row) for row in MATRIX], "maximum_cycles_per_path": 100000000,
                       "subprocess_timeout_seconds": 180, "executor": {"path": "/executor"},
                       "inputs": [{"path": str(self.run / "inputs" / mode)} for mode in ("cold", "warm_update")],
                       "cases": [{"mode": mode, "latency": lat, "reverse": rev,
                                  "paths": [{"cycles": 42}, {"cycles": 50}]} for mode, lat, rev in MATRIX]}
        commands = [("author_layout", ["/probe", "/experiment/topology.txt", "/experiment/author_capture", "17", "1"])]
        for mode, lat, rev in MATRIX:
            label = f"{mode}_lat{lat}_reverse{rev}"
            commands.append((label, ["/executor", f"/experiment/inputs/{mode}", f"/experiment/states/{label}",
                                     str(lat), str(rev), "100000000"]))
        self.report["runs"] = [{"label": label, "command": command, "cwd": "/repository",
                                "stdout": f"/experiment/raw/{label}.stdout.txt",
                                "stderr": f"/experiment/raw/{label}.stderr.txt"} for label, command in commands]

    def check(self, report):
        execution_contract(self.root, self.run, report, self.basis, {"seed": 17})

    def test_exact_commands_and_declarations(self):
        self.check(self.report)

    def test_mutated_contracts_rejected(self):
        for field in ("memory", "model", "boundary", "compiler_version", "cmake_cache"):
            changed = copy.deepcopy(self.report)
            changed[field] = {}
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.check(changed)
        for field, value in (("subprocess_timeout_seconds", 181), ("maximum_cycles_per_path", 99999999),
                             ("declared_matrix", []), ("scope", "convergence")):
            changed = copy.deepcopy(self.report)
            changed[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.check(changed)

    def test_commands_labels_and_paths_not_just_log_self_consistency(self):
        for field in ("command", "cwd", "stdout", "stderr", "label"):
            changed = copy.deepcopy(self.report)
            changed["runs"][1][field] = [] if field == "command" else "changed"
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.check(changed)
        self.report["cases"][0]["latency"] = 128
        with self.assertRaises(ValueError):
            self.check(self.report)

    def test_watchdog_command_and_timeout(self):
        self.report.update({"python_executable": "/python", "selection": {"source": {"path": "/source"}},
                            "basis": {"path": "/basis"}})
        record = {"command": worker_command("/python", self.run, "/source", "/basis", 100000000),
                  "cwd": str(self.root), "timeout_seconds": 1500,
                  "cleanup_scope": "pidfd_bound_observed_workers_not_cgroup_containment"}
        watchdog_contract(self.root, self.run, self.report, record)
        record["command"][-1] = "10000000"
        with self.assertRaises(ValueError):
            watchdog_contract(self.root, self.run, self.report, record)

    def test_joint_budget_and_command_mutation_still_rejects_observed_overrun(self):
        self.report["maximum_cycles_per_path"] = 49
        for record in self.report["runs"][1:]:
            record["command"][-1] = "49"
        with self.assertRaisesRegex(ValueError, "observed path cycles"):
            self.check(self.report)

    def test_static_work_accounts_for_forced_dummy_and_prefetch_tail(self):
        with tempfile.TemporaryDirectory() as directory:
            capture = Path(directory)
            write_words(capture / "csr_offsets.u32le", [0, 1, 2, 2, 2])
            write_words(capture / "csr_destinations.u32le", [0, 3])
            result = audit(capture, 4, partitions=2, partition_vertices=2)
            a, b = result["partitions"]
            self.assertEqual((a["segments"], b["segments"]), (1, 2))
            self.assertEqual(b["forced_dummy_source_zero_segments"], 1)
            self.assertEqual(b["empty_rows_visited"], 0)
            counters = {"row_reads": 8, "segment_reads": 3, "live_edges": 2,
                        "dummy_edges": 46, "cycles": 100}
            bind_traffic(result, [{"paths": [{}, counters]}])
            counters["segment_reads"] += 1
            with self.assertRaises(ValueError):
                bind_traffic(result, [{"paths": [{}, counters]}])


if __name__ == "__main__":
    unittest.main()
