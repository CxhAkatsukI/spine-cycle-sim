import copy
import json
import tempfile
import unittest
from pathlib import Path

from spine_cycle_sim.experiments.original_regraph_execution.sssp_control import (
    check_build_reference, parse_round_rows,
)


class SsspControlTests(unittest.TestCase):
    def rows(self):
        return [{"warm": warm, "inactive": inactive, "checked_words_per_replica": 65536,
                 "a4_replicas": 4, "routed_replicas": 2, "timing_ratio_admitted": False,
                 "a4_cycles_diagnostic_only": 100, "pressure_cycles": 200,
                 "a4_read_bytes": 262208, "a4_write_bytes": 1048576,
                 "active_vertices": 0 if inactive else 2}
                for warm, inactive in ((0, 0), (1, 0), (1, 1))]

    def encode(self, rows):
        return "\n".join("SSSP_ROUND " + json.dumps(row) for row in rows)

    def test_complete_scope(self):
        rows = self.rows()
        self.assertEqual(parse_round_rows("diagnostic\n" + self.encode(rows)), rows)

    def test_missing_repeated_and_reordered_rows(self):
        rows = self.rows()
        for bad in (rows[:2], rows + rows[:1], list(reversed(rows))):
            with self.assertRaises(ValueError):
                parse_round_rows(self.encode(bad))

    def test_rejects_unjustified_timing_and_broken_conservation(self):
        for key, value in (("timing_ratio_admitted", True), ("checked_words_per_replica", 16),
                           ("a4_replicas", 2), ("routed_replicas", 4), ("pressure_cycles", 99),
                           ("a4_write_bytes", 1), ("active_vertices", 0)):
            rows = copy.deepcopy(self.rows())
            rows[0][key] = value
            with self.assertRaises(ValueError):
                parse_round_rows(self.encode(rows))

    def test_reference_cache_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = root / "CMakeCache.txt"
            reference = root / "l2.h"
            cache.write_text("SPINE_SSSP_UDF_REFERENCE:FILEPATH=" + str(reference) + "\n")
            check_build_reference(root, reference)
            with self.assertRaises(ValueError):
                check_build_reference(root, root / "different.h")
