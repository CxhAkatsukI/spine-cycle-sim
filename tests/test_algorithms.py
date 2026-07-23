from __future__ import annotations

import math
from pathlib import Path
import unittest

from spine_cycle_sim.algorithms import (
    AlgorithmConfig,
    DynamicGraph,
    EdgeUpdate,
    FullPageRankPolicy,
    MapReduceEngine,
    NumericMode,
    ResidualPageRankPolicy,
    UpdateOperation,
    WeightedSsspPolicy,
    load_spine_edge_list,
    run_dual_oracle,
)
from spine_cycle_sim.workloads import Edge


DATA = Path(__file__).resolve().parent / "data"


class DynamicGraphTests(unittest.TestCase):
    def test_batch_is_last_write_wins(self) -> None:
        graph = DynamicGraph(4)
        effect = graph.apply_batch(
            [
                EdgeUpdate(0, 1, 9),
                EdgeUpdate(0, 1, 4),
                EdgeUpdate(1, 2, 7),
            ]
        )
        self.assertEqual(effect.inserted, 2)
        self.assertEqual(graph.edge_count, 2)
        self.assertEqual(graph.weight(0, 1), 4)

    def test_update_effect_classifies_weight_changes_and_delete(self) -> None:
        graph = DynamicGraph.from_edges(4, [Edge(0, 1, 5), Edge(1, 2, 3)])
        effect = graph.apply_batch(
            [
                EdgeUpdate(0, 1, 2),
                EdgeUpdate(1, 2, 8),
                EdgeUpdate(2, 3, 1, UpdateOperation.DELETE),
                EdgeUpdate(1, 2, 8, UpdateOperation.DELETE),
            ]
        )
        self.assertEqual(effect.decreased, 1)
        self.assertEqual(effect.deleted, 1)
        self.assertEqual(effect.missing_deletes, 1)
        self.assertEqual(graph.edge_count, 1)


class WeightedSsspTests(unittest.TestCase):
    def test_weighted_relaxation_and_dual_oracle_are_exact(self) -> None:
        graph = DynamicGraph.from_edges(
            5,
            [
                Edge(0, 1, 5),
                Edge(0, 2, 2),
                Edge(2, 1, 1),
                Edge(1, 3, 4),
                Edge(2, 3, 10),
            ],
        )
        result = run_dual_oracle(
            graph, WeightedSsspPolicy(), AlgorithmConfig(source=0)
        )
        inf = WeightedSsspPolicy.infinity
        self.assertEqual(result.mathematical.values, (0, 3, 2, 7, inf))
        self.assertTrue(result.exact_match)
        self.assertTrue(result.mathematical.stats.converged)
        self.assertEqual(result.mathematical.stats.applied_vertices, 5)

    def test_real_amazon_slice_is_a_file_backed_workload(self) -> None:
        loaded = load_spine_edge_list(DATA / "amazon_top1_exact.slice")
        self.assertEqual(loaded.metadata["case"], "amazon_top1_exact")
        self.assertEqual(loaded.graph.vertices, 735_323)
        self.assertEqual(loaded.graph.edge_count, 10)
        result = MapReduceEngine().run(
            loaded.graph,
            WeightedSsspPolicy(),
            AlgorithmConfig(source=2),
            NumericMode.FLOAT64,
        )
        reached = sum(value != WeightedSsspPolicy.infinity for value in result.values)
        self.assertEqual(reached, 11)
        self.assertEqual(result.stats.mapped_edges, 10)
        self.assertEqual(result.stats.applied_vertices, 10)

    def test_multiround_hardware_fixture_matches_dual_oracle(self) -> None:
        loaded = load_spine_edge_list(DATA / "weighted_chain_shortcut.slice")
        result = run_dual_oracle(
            loaded.graph, WeightedSsspPolicy(), AlgorithmConfig(source=0)
        )
        inf = WeightedSsspPolicy.infinity
        self.assertEqual(result.mathematical.values, (0, 3, 2, 7, 8, 10))
        self.assertNotIn(inf, result.mathematical.values)
        self.assertEqual(
            result.mathematical.stats.frontier_sizes, (1, 3, 2, 2, 2, 1)
        )
        self.assertEqual(result.mathematical.stats.iterations, 6)
        self.assertTrue(result.mathematical.stats.converged)
        self.assertTrue(result.exact_match)

    def test_architecture_oracle_saturates_uint32_sssp(self) -> None:
        graph = DynamicGraph.from_edges(
            3,
            [Edge(0, 1, (1 << 32) - 2), Edge(1, 2, 10)],
        )
        result = run_dual_oracle(
            graph, WeightedSsspPolicy(), AlgorithmConfig(source=0)
        )
        self.assertEqual(result.mathematical.values[2], (1 << 32) + 8)
        self.assertEqual(
            result.architecture.values[2], WeightedSsspPolicy.architecture_infinity
        )
        self.assertFalse(result.exact_match)


class PageRankTests(unittest.TestCase):
    def test_full_pagerank_cycle_is_uniform(self) -> None:
        graph = DynamicGraph.from_edges(
            3, [Edge(0, 1), Edge(1, 2), Edge(2, 0)]
        )
        result = run_dual_oracle(
            graph,
            FullPageRankPolicy(),
            AlgorithmConfig(epsilon=1e-10, max_iterations=100),
        )
        self.assertTrue(result.mathematical.stats.converged)
        for value in result.mathematical.values:
            self.assertAlmostEqual(value, 1 / 3, places=10)
        self.assertLess(result.max_abs_difference, 1e-7)

    def test_full_pagerank_redistributes_dangling_mass(self) -> None:
        graph = DynamicGraph.from_edges(3, [Edge(0, 1)])
        result = MapReduceEngine().run(
            graph,
            FullPageRankPolicy(),
            AlgorithmConfig(epsilon=1e-12, max_iterations=100),
            NumericMode.FLOAT64,
        )
        self.assertTrue(result.stats.converged)
        self.assertAlmostEqual(sum(result.values), 1.0, places=10)
        self.assertGreater(result.values[1], result.values[0])

    def test_fixed_iteration_mode_does_exactly_requested_work(self) -> None:
        graph = DynamicGraph.from_edges(3, [Edge(0, 1), Edge(1, 2), Edge(2, 0)])
        result = MapReduceEngine().run(
            graph,
            FullPageRankPolicy(),
            AlgorithmConfig(fixed_iterations=10),
            NumericMode.FLOAT32,
        )
        self.assertEqual(result.stats.iterations, 10)
        self.assertEqual(result.stats.mapped_edges, 30)

    def test_residual_pagerank_matches_full_solution(self) -> None:
        graph = DynamicGraph.from_edges(
            4,
            [Edge(0, 1), Edge(0, 2), Edge(1, 2), Edge(2, 0), Edge(2, 3)],
        )
        config = AlgorithmConfig(epsilon=1e-8, max_iterations=500)
        engine = MapReduceEngine()
        full = engine.run(graph, FullPageRankPolicy(), config, NumericMode.FLOAT64)
        residual = engine.run(
            graph, ResidualPageRankPolicy(), config, NumericMode.FLOAT64
        )
        self.assertTrue(full.stats.converged)
        self.assertTrue(residual.stats.converged)
        difference = sum(
            abs(float(left) - float(right))
            for left, right in zip(full.values, residual.values, strict=True)
        )
        self.assertLess(difference, 1e-6)
        self.assertAlmostEqual(sum(residual.values), 1.0, places=6)

    def test_residual_float32_oracle_remains_close(self) -> None:
        graph = DynamicGraph.from_edges(
            4, [Edge(0, 1), Edge(1, 2), Edge(2, 0), Edge(2, 3)]
        )
        result = run_dual_oracle(
            graph,
            ResidualPageRankPolicy(),
            AlgorithmConfig(epsilon=1e-6, max_iterations=300),
        )
        self.assertTrue(result.mathematical.stats.converged)
        self.assertTrue(result.architecture.stats.converged)
        self.assertLess(result.l1_difference, 1e-4)


if __name__ == "__main__":
    unittest.main()
