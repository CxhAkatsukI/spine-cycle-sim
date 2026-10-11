"""The resident matrix must retain every fixed model row and repetition."""

import unittest

from spine_cycle_sim.experiments.sharded_k4_stages.residency_matrix import matrix_order, summarize_matrix


class ResidencyMatrixTests(unittest.TestCase):
    def test_rotating_complete_matrix_and_unfitted_medians(self):
        order = matrix_order()
        self.assertEqual(len(order), 18)
        for repeat in range(3):
            self.assertEqual({(g, a) for r, g, a in order if r == repeat},
                             {(g, a) for g in ("au", "su", "wk") for a in ("candidate", "original")})
        self.assertEqual(order[0], (0, "au", "candidate"))
        self.assertEqual(order[6], (1, "au", "original"))
        attempts = [dict(repeat=r, graph=g, arm=a, analysis={"compute_span_ms": 10 + r},
                         residency={"wall_ms": 2 + r}) for r, g, a in order]
        predictions = {f"{g}_{a}": 10 for _, g, a in order}
        result = summarize_matrix(attempts, predictions)
        self.assertEqual(len(result["rows"]), 6)
        for row in result["rows"]:
            self.assertEqual(row["median_board_compute_span_ms"], 11)
            self.assertEqual(row["range_ms"], [10, 12])
            self.assertEqual(row["median_initial_residency_ms"], 3)
            self.assertAlmostEqual(row["nominal_signed_error_percent"], -100 / 11)
        for key in ("timing_fit_performed", "hardware_timing_admitted", "original_A4_match_admitted"):
            self.assertFalse(result[key])
        with self.assertRaisesRegex(ValueError, "missing or reordered"):
            summarize_matrix(attempts[:-1], predictions)
        with self.assertRaisesRegex(ValueError, "missing or reordered"):
            summarize_matrix(list(reversed(attempts)), predictions)


if __name__ == "__main__":
    unittest.main()
