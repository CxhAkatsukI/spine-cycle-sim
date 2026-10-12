"""The real-graph scope must not relax smoke bounds or permit matrix selection."""

import copy
import json
from pathlib import Path
import tempfile
import unittest

from spine_cycle_sim.experiments.sharded_k4_stages.row_line.model_scope import RESIDENT, SMOKE, study_scope
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.model_delivery import verify
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.model_recheck import recheck_smoke, recheck_study
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.model_study import run
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.model_validation import inventory
from test_sharded_k4_row_line_model_validation import fixture

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / ("docs/experiments/comparisons/grasu_regraph_stage_validation/actual_sharded_k4/"
                   "adapter_optimization/row_line/model/real_graph/evidence")


def declarations() -> list[dict]:
    return [{"id": case.name,
             "geometry": {key: getattr(case, key) for key in ("vertices", "partitions", "rounds")},
             "fixture": {"sha256": case.fixture_sha256}, "expected_values": {"sha256": case.values_sha256}}
            for case in RESIDENT.cases]


class RowLineStudyScopeTests(unittest.TestCase):
    def test_separate_explicit_bounds(self):
        self.assertEqual(study_scope("smoke_v1"), SMOKE)
        self.assertEqual(study_scope("resident_matrix_v1"), RESIDENT)
        self.assertEqual(SMOKE.inventory_limits, {"max_fixture_bytes": 64 * 1024**2, "max_vertices": 300000})
        self.assertEqual(SMOKE.limits["max_cycles"], 1000000)
        self.assertEqual(RESIDENT.limits["max_cycles"], 100000000)
        for key in ("timeout_seconds", "tree_memory_gib", "reserve_gib", "affinity", "parallel_workers"):
            self.assertEqual(SMOKE.limits[key], RESIDENT.limits[key])
        with self.assertRaisesRegex(ValueError, "unknown"):
            study_scope("resident_matrix_v2")

    def test_complete_matrix_identity_required(self):
        rows = declarations()
        RESIDENT.require_cases(rows)
        for changed in (rows[:2], rows[::-1], rows + rows[:1]):
            with self.subTest(ids=[r["id"] for r in changed]), self.assertRaises(ValueError):
                RESIDENT.require_cases(changed)
        for key, field, value in (("geometry", "vertices", 4096), ("geometry", "rounds", 1),
                                  ("fixture", "sha256", "changed"), ("expected_values", "sha256", "changed")):
            changed = copy.deepcopy(rows)
            changed[0][key][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "identity"):
                RESIDENT.require_cases(changed)

    def test_inventory_bound_is_explicit_not_global(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "resident.bin"
            fixture(path)
            inventory(path)
            with self.assertRaisesRegex(ValueError, "byte bound"):
                inventory(path, max_fixture_bytes=28)
            with self.assertRaisesRegex(ValueError, "geometry"):
                inventory(path, max_vertices=8)
            self.assertEqual(inventory(path, **RESIDENT.inventory_limits), inventory(path))

    def test_partial_resident_matrix_rejected_before_output_or_source_read(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, "complete predeclared"):
                run(root, root / "missing_plugin", [root / "au"], root / "output", scope_name=RESIDENT.name)
            self.assertFalse((root / "output").exists())

    def test_offline_recheck_cannot_downgrade_matrix_to_smoke_or_change_boundary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = {"study_scope": RESIDENT.name, "cases": declarations(),
                        "limits": RESIDENT.limits, "claim": RESIDENT.claim}
            (root / "results.json").write_text("{}")
            (root / "manifest.json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "smoke scope"):
                recheck_smoke(root, root / "missing_plugin")
            for field, value, message in (("cases", declarations()[:2], "matrix"),
                                           ("limits", SMOKE.limits, "boundary"),
                                           ("claim", SMOKE.claim, "boundary")):
                changed = dict(manifest, **{field: value})
                (root / "manifest.json").write_text(json.dumps(changed))
                with self.subTest(field=field), self.assertRaisesRegex(ValueError, message):
                    recheck_study(root, root / "missing_plugin")

    def test_portable_resident_archive_rechecks_full_matrix(self):
        report = verify(EVIDENCE)
        self.assertEqual([row["id"] for row in report["rows"]], [case.name for case in RESIDENT.cases])
        self.assertFalse(report["hardware_timing_admitted"])
        self.assertFalse(report["original_A4_comparison_complete"])
        for row in report["rows"]:
            self.assertTrue(row["complete_external_state_equal"])
            self.assertTrue(row["work_and_round_activity_equal"])
            reference, candidate = (row["arms"][arm] for arm in ("original", "candidate"))
            self.assertGreater(reference["directory_requests"], candidate["directory_requests"])


if __name__ == "__main__":
    unittest.main()
