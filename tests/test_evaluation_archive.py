import csv
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from spine_cycle_sim.experiments.evaluation_impact.figure_refresh import evaluation_archive as review


class EvaluationArchiveTests(unittest.TestCase):
    name = "resident_checkpoint_v4"
    resident = review.resident_path(name)

    def fixture(self, pending=True):
        files = {str(path): b"fixture" for path in review.selection(self.name)}
        scope = dict(expected_pairs=24, measured_pairs=23 if pending else 24,
                     status="INCOMPLETE_CURRENT_FPGA_CHECKPOINT" if pending else "MEASURED_CURRENT_FPGA_MATRIX",
                     publication_throughput_reproduced=False,
                     inputs=[dict(path=str(review.CONTROLS), bytes=len(b"fixture"),
                                  sha256=review.frozen.digest(b"fixture"))])
        files[str(self.resident / "scope.json")] = json.dumps(scope).encode()
        files[str(review.FRESH)] = json.dumps(dict(
            fpga_stage_calibrated=False, no_holdout_used_for_fit=True, executions=42)).encode()
        rows = [dict(algorithm=algorithm, dataset=dataset, status="MEASURED", boundary=review.BOUNDARY,
                     spine_wall_ms="2", gr_wall_ms="4", speedup_gr_over_spine="2", receipt_sha256="a" * 64)
                for algorithm in review.ALGORITHMS for dataset in review.DATASETS]
        rows[1].update(gr_wall_ms="1", speedup_gr_over_spine=".5")
        rows[2].update(gr_wall_ms="2", speedup_gr_over_spine="1")
        if pending:
            rows[-1].update(status="LAYOUT_FAILURE", spine_wall_ms="", gr_wall_ms="", speedup_gr_over_spine="")
        self.write_rows(files, rows)
        return files, rows

    def write_rows(self, files, rows):
        out = io.StringIO()
        writer = csv.DictWriter(out, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
        files[str(self.resident / review.CSV)] = out.getvalue().encode()

    def test_explicit_selection_preserves_same_host_fig8(self):
        paths = [str(path) for path in review.selection(self.name)]
        self.assertTrue(any(f"{self.name}/fig7_" in name for name in paths))
        self.assertFalse(any("resident_checkpoint_v2/" in name for name in paths))
        self.assertTrue(any("portable_fig8_headroom_v1/batch_sweep/" in name for name in paths))
        with self.assertRaises(ValueError):
            review.selection("../resident_checkpoint_v3")

    def test_completion_is_not_an_all_win_claim(self):
        for pending in (True, False):
            files, _ = self.fixture(pending)
            summary = review.checkpoint(self.name, files.__getitem__)
            self.assertEqual(summary["complete"], not pending)
            self.assertFalse(summary["all_pairs_spine_wins"])
            self.assertEqual(len(summary["spine_wins"]), 21 if pending else 22)
            self.assertEqual(summary["gr_wins"][0]["speedup_gr_over_spine"], .5)
            self.assertEqual(len(summary["ties"]), 1)
            self.assertEqual([row["status"] for row in summary["unmeasured"]],
                             ["LAYOUT_FAILURE"] if pending else [])

    def test_rejects_wrong_control_pin_and_disagreed_ratio(self):
        files, rows = self.fixture()
        files[str(review.CONTROLS)] = b"other"
        with self.assertRaisesRegex(ValueError, "not exported against"):
            review.checkpoint(self.name, files.__getitem__)
        rows[1]["speedup_gr_over_spine"] = "2"
        self.write_rows(files, rows)
        with self.assertRaisesRegex(ValueError, "timing, boundary or receipt"):
            review.checkpoint(self.name, files.__getitem__)

    def test_archive_roundtrip_is_deterministic_and_never_overwrites(self):
        files, _ = self.fixture()
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name, blob in files.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(blob)
            a, b = root / "a.tar.gz", root / "b.tar.gz"
            manifest = review.build(root, self.name, a)
            self.assertEqual(review.verify_archive(a), manifest)
            review.build(root, self.name, b)
            self.assertEqual(a.read_bytes(), b.read_bytes())
            with self.assertRaises(FileExistsError):
                review.build(root, self.name, a)
            files[review.INDEX] = json.dumps(manifest).encode()
            files[str(review.GUIDE)] = b"tampered"
            with self.assertRaisesRegex(ValueError, "changed evaluation member"):
                review.verify(files.__getitem__, set(files))
