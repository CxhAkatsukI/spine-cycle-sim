import tempfile
from pathlib import Path
import unittest

from spine_cycle_sim.experiments.evaluation_impact.common_g.weighted_abi.analysis import (
    ARMS, EXPECTED, FINAL, INSERTIONS, WARNING_PAIR, analyze,
)
from spine_cycle_sim.experiments.evaluation_impact.common_g.weighted_abi.preparation import command


def stdout():
    return "\n".join([
        f"WEIGHTED_ABI_PASS case={case} arm={arm} operations={values[0]} "
        f"segments={values[1] + 8} shards={values[1]} edges={values[2]}"
        for case, values in EXPECTED.items() for arm in ARMS
    ] + [FINAL]) + "\n"


def stderr():
    return "\n".join(WARNING_PAIR * INSERTIONS) + "\n"


class WeightedAbiTests(unittest.TestCase):
    def test_complete_matrix(self):
        self.assertEqual(len(analyze(stdout(), stderr())), 8)

    def test_missing_duplicate_reordered_and_diagnostics_rejected(self):
        lines = stdout().splitlines()
        for changed in (lines[1:], [lines[0], *lines[0:-1]],
                        [lines[1], lines[0], *lines[2:]], [*lines, "extra"]):
            with self.subTest(changed=changed):
                with self.assertRaises(ValueError):
                    analyze("\n".join(changed), stderr())
        with self.assertRaises(ValueError):
            analyze(stdout(), "leftover stream warning")

    def test_changed_scope_and_timing_promotion_rejected(self):
        for before, after in (("operations=36", "operations=35"),
                              ("timing_admitted=false", "timing_admitted=true"),
                              ("segments=10", "segments=1"),
                              ("arm=original_cache", "arm=registered_cache")):
            with self.subTest(before=before):
                with self.assertRaises(ValueError):
                    analyze(stdout().replace(before, after, 1), stderr())

    def test_width_warnings_are_not_silently_ignored(self):
        for changed in ("", stderr() + "warning\n", stderr().replace("WARNING", "other", 1),
                        stderr() + "\n".join(WARNING_PAIR) + "\n"):
            with self.subTest(stderr=changed):
                with self.assertRaises(ValueError):
                    analyze(stdout(), changed)

    def test_adapter_flags_are_explicit(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            resident = command(folder, folder, "resident", "g++", folder / "probe")
            candidate = command(folder, folder, "bank_stream", "g++", folder / "probe")
            self.assertNotIn("-DGRASU_REGRAPH_BANK_STREAM=1", resident)
            self.assertIn("-DGRASU_REGRAPH_BANK_STREAM=1", candidate)
            self.assertIn("-DGRASU_REGRAPH_BANK_FIFO_LINES=256", candidate)
            self.assertIn("-DGRASU_REGRAPH_DIRECTORY_TILE_ROWS=1024", candidate)
            with self.assertRaises(ValueError):
                command(folder, folder, "invented", "g++", folder / "probe")


if __name__ == "__main__":
    unittest.main()
