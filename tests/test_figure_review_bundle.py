import copy
import csv
import importlib.util
import io
import json
from pathlib import Path
import tarfile
from tempfile import TemporaryDirectory
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "spine_cycle_sim/experiments/evaluation_impact/figure_refresh/review_bundle.py"
SPEC = importlib.util.spec_from_file_location("review_bundle", SOURCE)
review = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(review)


class ReviewBundleTests(unittest.TestCase):
    def fixture(self):
        blobs = {str(path): str(path).encode() for path in review.selected_paths()}
        manifest = dict(schema=1, selection="nov05-review-v1",
                        checkpoint=dict(status="INCOMPLETE_REVIEW_CHECKPOINT", complete=False),
                        members=[dict(path=name, bytes=len(blob), sha256=review.digest(blob))
                                 for name, blob in blobs.items()])
        return manifest, blobs

    def test_selected_inventory_uses_current_and_same_host_fig8_only(self):
        names = [str(path) for path in review.selected_paths()]
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue(any("resident_checkpoint_v2/fig7_" in name for name in names))
        self.assertTrue(any("portable_fig8_headroom_v1/batch_sweep" in name for name in names))
        self.assertFalse(any("portable_fig8/" in name or "resident_checkpoint_v1/" in name for name in names))
        self.assertFalse(any(name.endswith("fresh_simulator/fig8_ten_batch.csv") for name in names))

    def test_hashes_inventory_and_incomplete_scope_are_enforced(self):
        manifest, blobs = self.fixture()
        self.assertEqual(review.verify_manifest(manifest, blobs.__getitem__), manifest)
        damaged = copy.deepcopy(manifest)
        damaged["checkpoint"]["complete"] = True
        with self.assertRaisesRegex(ValueError, "not a completed"):
            review.verify_manifest(damaged, blobs.__getitem__)
        damaged = copy.deepcopy(manifest)
        damaged["members"].append(damaged["members"][0])
        with self.assertRaisesRegex(ValueError, "inventory"):
            review.verify_manifest(damaged, blobs.__getitem__)
        blobs[manifest["members"][0]["path"]] += b"changed"
        with self.assertRaisesRegex(ValueError, "changed review member"):
            review.verify_manifest(manifest, blobs.__getitem__)

    def test_archive_is_portable_and_rejects_extra_links_or_traversal(self):
        manifest, blobs = self.fixture()
        blobs[str(review.MANIFEST)] = json.dumps(manifest).encode()
        with TemporaryDirectory() as temporary:
            archive = Path(temporary) / "review.tar.gz"
            for extra in (None, "extra.txt", "../escape", "symlink"):
                with tarfile.open(archive, "w:gz") as target:
                    for name, blob in blobs.items():
                        member = tarfile.TarInfo(name)
                        member.size = len(blob)
                        target.addfile(member, io.BytesIO(blob))
                    if extra:
                        member = tarfile.TarInfo(extra)
                        if extra == "symlink":
                            member.type = tarfile.SYMTYPE
                            member.linkname = "/tmp/escape"
                        target.addfile(member)
                if extra is None:
                    self.assertEqual(review.verify_archive(archive), manifest)
                else:
                    with self.assertRaises(ValueError):
                        review.verify_archive(archive)

    def test_build_refuses_to_overwrite_frozen_artifacts(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / review.ARCHIVE).parent.mkdir(parents=True)
            (root / review.ARCHIVE).touch()
            with self.assertRaises(FileExistsError):
                review.build(root)

    def test_checkpoint_reconciles_all_slots_and_actual_ratios(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / review.HANDOFF
            resident = target / "current_fpga/resident_checkpoint_v2"
            fresh = target / "fresh_simulator"
            resident.mkdir(parents=True)
            fresh.mkdir()
            scope = dict(expected_pairs=24, measured_pairs=15)
            (resident / "scope.json").write_text(json.dumps(scope))
            (fresh / "fresh_summary.json").write_text(json.dumps(dict(
                fpga_stage_calibrated=False, no_holdout_used_for_fit=True, executions=42)))
            rows = []
            for algorithm in ("weighted_sssp", "cc", "residual_pagerank"):
                for dataset in ("AU", "SU", "WK", "SO", "PK", "LJ", "LJ08", "R19"):
                    measured = len(rows) < 15
                    rows.append(dict(algorithm=algorithm, dataset=dataset,
                                     status="MEASURED" if measured else "PENDING",
                                     spine_wall_ms="2" if measured else "",
                                     gr_wall_ms="4" if measured else "",
                                     speedup_gr_over_spine="2" if measured else ""))

            def write_rows():
                with (resident / "fig7_resident_checkpoint.csv").open("w", newline="") as stream:
                    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
                    writer.writeheader()
                    writer.writerows(rows)

            write_rows()
            result = review.checkpoint(root)
            self.assertEqual((result["fpga_pairs"], result["missing_fpga_pairs"]), (15, 9))
            self.assertFalse(result["complete"])
            rows[-1]["gr_wall_ms"] = "0"
            write_rows()
            with self.assertRaisesRegex(ValueError, "missing slot has timing"):
                review.checkpoint(root)
            rows[-1]["gr_wall_ms"] = ""
            rows[0]["speedup_gr_over_spine"] = "3"
            write_rows()
            with self.assertRaisesRegex(ValueError, "ratio disagrees"):
                review.checkpoint(root)
            rows[0]["speedup_gr_over_spine"] = "2"
            write_rows()
            scope["measured_pairs"] = 16
            (resident / "scope.json").write_text(json.dumps(scope))
            with self.assertRaisesRegex(ValueError, "measured count differs"):
                review.checkpoint(root)


if __name__ == "__main__":
    unittest.main()
