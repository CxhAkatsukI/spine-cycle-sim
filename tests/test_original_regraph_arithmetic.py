"""Arithmetic controls do not establish FPGA timing or default PR equivalence."""

import copy
from pathlib import Path
import random
import tempfile
import unittest

from spine_cycle_sim.experiments.original_regraph_execution.hardware import study as reference
from spine_cycle_sim.experiments.original_regraph_execution.hardware.semantics import arithmetic, sources, study


class ArithmeticTests(unittest.TestCase):
    def test_exact_and_quantized_outputs_are_numeric_not_bitwise_equality(self):
        exact = arithmetic.compare([128, 0], [1, 0], 1)
        self.assertTrue(exact["numeric_outputs_equal"])
        self.assertTrue(exact["output_encoding_different"])
        self.assertEqual(exact["max_absolute_difference"], 0)
        rounded = arithmetic.compare([1, 128, 0], [1, 3, 0], 2)
        self.assertEqual(rounded["different_output_vertices"], 2)
        self.assertEqual(rounded["fixed_zero_float_nonzero_vertices"], 1)
        self.assertFalse(rounded["numeric_outputs_equal"])
        self.assertTrue(rounded["original_quantization_bound_passed"])
        self.assertAlmostEqual(rounded["max_absolute_difference"], 1.0)

    def test_random_nonnegative_inputs_obey_independent_truncation_bound(self):
        rng = random.Random(571)
        sums = [rng.randrange(100_000) for _ in range(200)]
        divisors = [rng.randrange(256, 4000) for _ in sums]
        result = arithmetic.compare(sums, divisors, len(sums))
        self.assertTrue(result["original_quantization_bound_passed"])
        self.assertTrue(result["binary32_integer_gather_exact_any_order"])
        self.assertGreater(result["different_output_vertices"], 0)

    def test_overflow_inexact_domain_and_nonzero_padding_rejected(self):
        cases = (([0], [0], 0), ([1], [], 1), ([128, 1], [1, 0], 1),
                 ([128, 0], [1, 1], 1), ([100_000], [1], 1),
                 ([2**24 + 1], [1000], 1), ([128], [2**24 + 1], 1),
                 ([-1], [1], 1), ([1], [-1], 1))
        for totals, divisors, vertices in cases:
            with self.subTest(totals=totals, divisors=divisors), self.assertRaises(ValueError):
                arithmetic.compare(totals, divisors, vertices)

    def test_csr_accumulates_same_numeric_contributions_with_zero_padding(self):
        result = arithmetic.csr_sums([0, 2, 3, 3], [1, 2, 2], [128, 64, 0, 0], 3)
        self.assertEqual(list(result), [0, 128, 192, 0])
        cases = (([0], [], [], 0), ([1, 1], [0], [1], 1),
                 ([0, 1], [1], [1], 1), ([0, 0], [], [1, 2], 1),
                 ([0, 2, 1], [0], [1, 1], 2), ([0, 0], [], [-1], 1))
        for offsets, destinations, initial, vertices in cases:
            with self.subTest(offsets=offsets), self.assertRaises(ValueError):
                arithmetic.csr_sums(offsets, destinations, initial, vertices)


class AdmissionTests(unittest.TestCase):
    def test_complete_independently_passing_reference_required(self):
        document = {"status": reference.INPUT_PASS,
                    "cases": [{"id": key} for key in reference.EXPECTED]}
        accepted = {"status": reference.STATUS, "errors": [], "cases": document["cases"]}
        study.validate_reference(accepted, document)
        for update in ({"status": "RUNNING"}, {"errors": ["failed"]},
                       {"cases": accepted["cases"][:-1]},
                       {"cases": accepted["cases"][:-1] + accepted["cases"][:1]}):
            with self.subTest(update=update), self.assertRaises(ValueError):
                study.validate_reference({**accepted, **update}, document)

    def test_missing_or_nonzero_limit_events_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            values = dict.fromkeys(("max", "oom", "oom_kill", "oom_group_kill"), "0")
            def write(fields):
                (root / "memory.events").write_text("\n".join(f"{key} {value}" for key, value in fields.items()))
            write(values)
            study.clean_memory_events(root)
            for key in values:
                for value in ("1", None):
                    changed = copy.deepcopy(values)
                    if value is None:
                        changed.pop(key)
                    else:
                        changed[key] = value
                    write(changed)
                    with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                        study.clean_memory_events(root)

    def test_source_review_rejects_duplicate_or_changed_arithmetic(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "apply.cpp"
            source.write_text("base=0; damping=108/128;\n")
            pin = sources.unique_literals(source, ("base=0", "damping=108/128"))
            self.assertEqual(pin["path"], str(source))
            for text in ("base=1; damping=108/128;", "base=0; base=0; damping=108/128;"):
                source.write_text(text)
                with self.assertRaisesRegex(ValueError, "source anchors"):
                    sources.unique_literals(source, ("base=0", "damping=108/128"))

    def test_audit_does_not_claim_board_performance_or_default_equivalence(self):
        self.assertIn("NOT_HARDWARE_OR_PERFORMANCE_MATCH", study.STATUS)
        self.assertIn("production_default_semantics_equal", study.CLAIMS)
        self.assertEqual(study.PROFILE["candidate_damping"], 108 / 128)
        self.assertEqual(study.PROFILE["candidate_mode"], "FullPR")
        self.assertEqual(study.PROFILE["candidate_base"], 0)
        self.assertEqual(study.PROFILE["candidate_dangling_share"], 0)


if __name__ == "__main__":
    unittest.main()
