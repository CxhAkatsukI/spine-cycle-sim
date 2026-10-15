import json
from pathlib import Path
import tempfile
import unittest

from spine_cycle_sim.experiments.evaluation_impact.common_g.continuous_handoff import analysis, preparation


class ContinuousHandoffTests(unittest.TestCase):
    def case(self):
        return {"case": "AU-mixed-512", "shards": 1, "vertices": 32,
                "batches": [{"batch": batch, "updates": 0 if batch == 0 else 256,
                             "edges": 8192, "fallback": batch == 1,
                             "seed_sources": 0 if batch == 0 else 1} for batch in range(3)]}

    def output(self):
        setup = {"board": False, "shards": 1, "source": 0, "round_limit": 2048,
                 "initial_state": "old_graph_converged", "one_time_setup_ms": 1.0}
        rows = [{**row, "board": False, "checked_words": 2 * 131072 * 16 + 32,
                 "checked_vertices": 32, "converged": True, "state_pass": True, "restored_pma": False,
                 "active_counts": [0] if row["batch"] == 0 else [2, 1, 0],
                 "rounds": 1 if row["batch"] == 0 else 3, **dict.fromkeys(analysis.TIMES, 0.0)}
                for row in self.case()["batches"]]
        return setup, rows

    def text(self, setup, rows):
        return "\n".join(["CONTINUOUS_GR_SETUP " + json.dumps(setup),
                          *("CONTINUOUS_GR_ROW " + json.dumps(row) for row in rows), analysis.PASS])

    def test_converged_resident_preflight(self):
        setup, rows = self.output()
        self.assertEqual(analysis.analyze(self.case(), self.text(setup, rows), ""),
                         {"setup": setup, "rows": rows})

    def test_setup_rejects_cold_state_multishard_and_board(self):
        for key, value in (("board", True), ("initial_state", "cold"), ("source", False),
                           ("shards", 2), ("round_limit", 1), ("one_time_setup_ms", float("nan"))):
            setup, rows = self.output()
            setup[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                analysis.analyze(self.case(), self.text(setup, rows), "")

    def test_rejects_changed_policy_padding_state_and_timing(self):
        for key, value in (("fallback", True), ("seed_sources", 1), ("state_pass", False),
                           ("checked_words", 0), ("checked_vertices", True), ("restored_pma", True),
                           ("converged", False), ("g_busy_ms", 1), ("r_busy_ms", 1),
                           ("host_inclusive_e2e_ms", 1), ("oracle_ms", float("inf")),
                           ("g_ready_wall_ms", -1), ("updates", False)):
            setup, rows = self.output()
            rows[0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                analysis.analyze(self.case(), self.text(setup, rows), "")

    def test_rejects_invalid_convergence_trajectory(self):
        for counts in ([], [1], [0, 0], [True, 0], [33, 0], [-1, 0]):
            setup, rows = self.output()
            rows[1]["active_counts"] = counts
            rows[1]["rounds"] = len(counts)
            with self.subTest(counts=counts), self.assertRaises(ValueError):
                analysis.analyze(self.case(), self.text(setup, rows), "")
        setup, rows = self.output()
        rows[1]["rounds"] = 2
        with self.assertRaises(ValueError):
            analysis.analyze(self.case(), self.text(setup, rows), "")

    def test_rejects_incomplete_extra_or_diagnostic_output(self):
        setup, rows = self.output()
        text = self.text(setup, rows)
        for out, err in ((self.text(setup, rows[:-1]), ""), (text + "\nEXTRA", ""),
                         (text, "warning"), (text.replace(analysis.PASS, "BOARD_PASS"), "")):
            with self.subTest(out=out, err=err), self.assertRaises(ValueError):
                analysis.analyze(self.case(), out, err)

    def input(self, root, updates):
        initial = [(0, 1, 5, 1), (1, 2, 7, 1)]
        path = root / "input.txt"
        path.write_text(f"3 2 {len(updates)} 65536\n" +
                        "".join(" ".join(map(str, row)) + "\n" for row in [*initial, *updates]))
        return path

    def test_policy_uses_net_changes_and_not_physical_delete_tokens(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = self.input(root, [(0, 1, 5, -1), (0, 1, 3, 1), (1, 2, 7, -1), (1, 2, 10, 1)])
            self.assertEqual(preparation.policies(path), [{"fallback": False, "seed_sources": 0},
                             {"fallback": False, "seed_sources": 1}, {"fallback": True, "seed_sources": 1}])
            path = self.input(root, [(0, 1, 5, -1), (0, 1, 5, 1)] * 2)
            self.assertEqual(preparation.policies(path), [{"fallback": False, "seed_sources": 0}] * 3)

    def test_policy_rejects_failed_or_out_of_abi_mutations(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for changes in ([(0, 1, 6, -1)], [(0, 1, 5, 1)], [(0, 3, 1, 1)], [(0, 2, 4096, 1)]):
                with self.subTest(changes=changes), self.assertRaises(ValueError):
                    preparation.policies(self.input(root, changes))

    def test_compile_keeps_checked_native_abi(self):
        command = preparation.command(Path("source"), Path("xrt"), "g++", Path("probe"))
        for value in ("-O2", "-Werror", "-MD", "-D_GLIBCXX_ASSERTIONS",
                      "source/continuous_handoff/control.cpp", "-lxilinxopencl"):
            self.assertIn(value, command)
        self.assertNotIn("source/continuous_board/control.cpp", command)
        root = Path(__file__).resolve().parents[1]
        compute = (root / "cpp/tests/evaluation_impact/common_g/continuous_handoff/compute.hpp").read_text()
        self.assertIn("static_cast<unsigned>(model.graph.vertices)", compute)
        self.assertIn("shard.pma[port]", compute)
        self.assertNotIn("pack_weighted_pma_runtime_buffers", compute)
        self.assertIn("enqueueWriteBuffer(target, CL_FALSE", compute)

    def test_warm_control_preserves_order_and_selects_64_distinct_decreases(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            initial = [(0, dst, 5, 1) for dst in range(1, 66)]
            changes = [(0, dst, weight, diff) for dst in range(1, 66)
                       for weight, diff in ((5, -1), (3, 1))]
            source, target = root / "source.txt", root / "warm.txt"
            source.write_text("66 65 130 65536\n" + "".join(
                " ".join(map(str, row)) + "\n" for row in [*initial, *changes]))
            self.assertEqual(preparation.warm_control(source, target), (66, 65))
            self.assertEqual(preparation.policies(target), [{"fallback": False, "seed_sources": 0},
                             {"fallback": False, "seed_sources": 1}, {"fallback": False, "seed_sources": 1}])
            self.assertNotIn("0 65 3 1", target.read_text())

    def test_insufficient_warm_controls_fail_instead_of_reducing_scope(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self.input(root, [(0, 1, 5, -1), (0, 1, 3, 1)])
            with self.assertRaisesRegex(ValueError, "insufficient distinct"):
                preparation.warm_control(source, root / "warm.txt")


if __name__ == "__main__":
    unittest.main()
