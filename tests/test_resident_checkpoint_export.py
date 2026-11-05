"""Incomplete exports retain pending slots and do not invent propagation or repetitions."""

import argparse
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch


class ResidentCheckpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        folder = Path(__file__).resolve().parents[1] / (
            "docs/experiments/comparisons/grasu_regraph_stage_validation/"
            "evaluation_impact/figure7_11_preview_20261105")
        cls.package = folder
        sys.path.insert(0, str(folder))
        try:
            spec = importlib.util.spec_from_file_location("resident_checkpoint", folder / "export_resident_checkpoint.py")
            cls.export = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(cls.export)
        finally:
            sys.path.remove(str(folder))

    def row(self, **changes):
        pair = dict(algorithm="residual_pagerank", logical_updates=8, physical_updates=8,
                    spine_wall_ms=5, gr_wall_ms=10, speedup_gr_over_spine=2,
                    boundary="resident", spine_rounds=0, gr_rounds=0)
        pair.update(changes)
        return self.export.measured_row("residual_pagerank", "AU", pair,
            dict(sha256="receipt"), [140, 500, 430, 0], reused=True)

    def test_reused_zero_round_sample_is_not_fresh_pair_or_timing_closure(self):
        row = self.row()
        self.assertEqual((row["fresh_spine_samples"], row["fresh_gr_samples"]), (1, 0))
        self.assertTrue(row["gr_sample_reused"])
        self.assertFalse(row["nominal_timing_pass"])
        self.assertEqual((row["spine_rounds"], row["gr_rounds"]), (0, 0))

    def test_invalid_values_and_changed_batch_rejected(self):
        for changes in (dict(spine_wall_ms=0), dict(gr_wall_ms=float("nan")),
                        dict(speedup_gr_over_spine=3), dict(logical_updates=9), dict(physical_updates=16)):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.row(**changes)

    def test_different_round_counts_do_not_alone_disprove_same_final_state(self):
        self.assertEqual(self.row(spine_rounds=1, gr_rounds=2)["gr_rounds"], 2)

    def test_cc_requires_reciprocal_records_and_exports_a_measured_loss(self):
        pair = dict(algorithm="cc", logical_updates=8, physical_updates=16,
                    spine_wall_ms=20, gr_wall_ms=10, speedup_gr_over_spine=0.5,
                    boundary="resident", spine_rounds=0, gr_rounds=1)
        export = self.export.measured_row
        args = (dict(sha256="receipt"), [150, 500, 450, 0])
        row = export("cc", "AU", pair, *args, reused=True)
        self.assertEqual((row["status"], row["speedup_gr_over_spine"]), ("MEASURED", 0.5))
        with self.assertRaisesRegex(ValueError, "invalid paired times"):
            export("cc", "AU", dict(pair, physical_updates=8), *args)

    def test_losing_row_is_retained(self):
        row = self.row(spine_wall_ms=20, speedup_gr_over_spine=0.5)
        self.assertEqual(row["speedup_gr_over_spine"], 0.5)

    def test_fresh_qualified_pair_cannot_replace_measured_retime_or_change_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.json"
            path.write_text(json.dumps(dict(dataset="LJ08")))
            args = argparse.Namespace(qualified_pair=[path])
            checked = dict(report=dict(stage_gates=dict(image=dict(sha256="baseline"))))
            retimes = dict(LJ08=dict(status="UPSTREAM_UNAVAILABLE_RETAINED"))
            with patch.object(self.export.qualified_resident, "validate_result", return_value=checked):
                self.assertEqual(self.export.fresh_qualified_pairs(args, retimes, "baseline"),
                                 dict(LJ08=checked))
                with self.assertRaisesRegex(ValueError, "baseline image"):
                    self.export.fresh_qualified_pairs(args, retimes, "different")
                args.qualified_pair = [path, path]
                with self.assertRaisesRegex(ValueError, "unique declared"):
                    self.export.fresh_qualified_pairs(args, retimes, "baseline")
                args.qualified_pair = [path]
                retimes["LJ08"]["status"] = self.export.correction_matrix.MEASURED
                with self.assertRaisesRegex(ValueError, "already measured"):
                    self.export.fresh_qualified_pairs(args, retimes, "baseline")

    def test_two_fresh_arms_are_not_labelled_as_a_reused_gr_sample(self):
        pair = dict(algorithm="residual_pagerank", logical_updates=8, physical_updates=8,
                    spine_wall_ms=20, gr_wall_ms=10, speedup_gr_over_spine=0.5,
                    boundary="resident", spine_rounds=0, gr_rounds=0)
        row = self.export.measured_row("residual_pagerank", "LJ08", pair,
            dict(sha256="receipt"), [140, 500, 430, 0])
        self.assertEqual((row["fresh_spine_samples"], row["fresh_gr_samples"]), (1, 1))
        self.assertFalse(row["gr_sample_reused"])
        self.assertEqual(row["speedup_gr_over_spine"], 0.5)

    def test_retime_fragments_keep_all_statuses_and_unmodified_raw_matrices(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first, next_ = root / "first.json", root / "next.json"
            cases = {dataset: dict(status="WAITING") for dataset in self.export.sssp.DATASETS}
            cases["AU"] = dict(status=self.export.correction_matrix.MEASURED, result="first")
            first.write_text(json.dumps(dict(pins=[], cases=cases)))
            pending = dict(status="FAILED_RETAINED", error="pressure guard")
            next_.write_text(json.dumps(dict(pins=[], cases={"LJ": pending})))
            combined, members, sources = self.export.retime_fragments([first, next_])
            self.assertEqual(combined["AU"], cases["AU"])
            self.assertEqual(combined["LJ"], pending)
            self.assertEqual(members["retime-matrix.json"], first.read_bytes())
            self.assertEqual(members["retime-fragments/01.json"], next_.read_bytes())
            self.assertEqual(sources["LJ"], "retime-fragments/01.json")
            self.assertEqual(set(combined), set(cases))

    def test_retime_fragments_never_choose_between_two_measured_samples(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first, next_ = root / "first.json", root / "next.json"
            cases = {dataset: dict(status="WAITING") for dataset in self.export.sssp.DATASETS}
            cases["AU"] = dict(status=self.export.correction_matrix.MEASURED, result="first")
            first.write_text(json.dumps(dict(pins=[], cases=cases)))
            next_.write_text(json.dumps(dict(pins=[], cases={"AU": dict(
                status=self.export.correction_matrix.MEASURED, result="different")})))
            with self.assertRaisesRegex(ValueError, "conflicting measured"):
                self.export.retime_fragments([first, next_])
            next_.write_text(json.dumps(dict(pins=[], cases={"AU": dict(status="WAITING")})))
            combined, _, sources = self.export.retime_fragments([first, next_])
            self.assertEqual(combined["AU"], cases["AU"])
            self.assertEqual(sources["AU"], "retime-matrix.json")

    def test_partial_first_matrix_cannot_remove_declared_slots(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "partial.json"
            path.write_text(json.dumps(dict(pins=[], cases={"AU": dict(status="WAITING")})))
            with self.assertRaisesRegex(ValueError, "all eight"):
                self.export.retime_fragments([path])

    def test_sixteen_pair_increment_preserves_prior_samples_and_raw_qualified_receipt(self):
        current = self.package / "current_fpga/resident_checkpoint_v3"
        previous = current.with_name("resident_checkpoint_v2")

        def read_rows(folder):
            with (folder / "fig7_resident_checkpoint.csv").open(newline="") as stream:
                return {(row["algorithm"], row["dataset"]): row for row in csv.DictReader(stream)}

        old, new = read_rows(previous), read_rows(current)
        scope = json.loads((current / "scope.json").read_text())
        self.assertEqual(set(new), set(old))
        self.assertEqual(len(new), scope["expected_pairs"])
        measured = [row for row in new.values() if row["status"] == "MEASURED"]
        self.assertEqual((len(measured), scope["measured_pairs"]), (16, 16))
        added = ("residual_pagerank", "LJ08")
        for key in old.keys() - {added}:
            self.assertEqual(new[key], old[key])
        for row in new.values():
            if row["status"] != "MEASURED":
                self.assertEqual(row["algorithm"], "cc")
                self.assertTrue(all(not row[name] for name in (
                    "spine_wall_ms", "gr_wall_ms", "speedup_gr_over_spine")))
        row = new[added]
        self.assertEqual((row["fresh_spine_samples"], row["fresh_gr_samples"],
                          row["gr_sample_reused"]), ("1", "1", "False"))
        self.assertAlmostEqual(float(row["speedup_gr_over_spine"]),
                               float(row["gr_wall_ms"]) / float(row["spine_wall_ms"]))
        pin = scope["fresh_qualified_sources"]["LJ08"]
        with tarfile.open(current / "receipts.tar.gz", "r:gz") as archive:
            raw = archive.extractfile(f"objects/{pin['sha256']}/results.json").read()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), pin["sha256"])
        self.assertEqual(row["receipt_sha256"], pin["sha256"])
        self.assertEqual(json.loads(raw)["status"], "MEASURED_RESIDENT_PAIR")


if __name__ == "__main__":
    unittest.main()
