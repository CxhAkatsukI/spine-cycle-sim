import csv
import io
import json
from pathlib import Path
import tarfile
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
        receipt = b'{"status":"fixture"}'
        bundle = io.BytesIO()
        with tarfile.open(fileobj=bundle, mode="w:gz") as archive:
            member = tarfile.TarInfo("receipt.json")
            member.size = len(receipt)
            archive.addfile(member, io.BytesIO(receipt))
        files[str(self.resident / review.RECEIPTS)] = bundle.getvalue()
        rows = [dict(algorithm=algorithm, dataset=dataset, status="MEASURED", boundary=review.BOUNDARIES[algorithm],
                     spine_wall_ms="2", gr_wall_ms="4", speedup_gr_over_spine="2",
                     receipt_sha256=review.frozen.digest(receipt))
                for algorithm in review.ALGORITHMS for dataset in review.DATASETS]
        next(row for row in rows if row["algorithm"] == "cc").update(
            gr_wall_ms="1", speedup_gr_over_spine=".5")
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

    def direct_fixture(self):
        self.name = "resident_checkpoint_v3"
        self.resident = review.resident_path(self.name)
        files, rows = self.fixture(pending=False)
        for path in review.selection(self.name, cc_direct=True):
            files.setdefault(str(path), b"fixture")
        cc = []
        pairs = {}
        for row in rows:
            if row["algorithm"] != "cc":
                continue
            copy = dict(row, status=review.CC_MEASURED, routing_report_complete="False")
            cc.append(copy)
            pairs[row["dataset"]] = dict(boundary=row["boundary"], spine_ms=float(row["spine_wall_ms"]),
                                         gr_ms=float(row["gr_wall_ms"]),
                                         gr_over_spine=float(row["speedup_gr_over_spine"]))
            row.update(status="PENDING", spine_wall_ms="", gr_wall_ms="", speedup_gr_over_spine="")
        self.write_rows(files, rows)
        scope = json.loads(files[str(self.resident / "scope.json")])
        scope.update(measured_pairs=16, status="INCOMPLETE_CURRENT_FPGA_CHECKPOINT")
        files[str(self.resident / "scope.json")] = json.dumps(scope).encode()
        out = io.StringIO()
        writer = csv.DictWriter(out, fieldnames=list(cc[0]))
        writer.writeheader()
        writer.writerows(cc)
        files[str(review.CC_TABLE)] = out.getvalue().encode()
        image = dict(path="cc.xclbin", sha256="a" * 64, bytes=123)
        files[str(review.RESIDENT / "gr_scope.json")] = json.dumps(dict(artifact_index=[image])).encode()
        files[str(review.CC_DIRECT / "data/scope.json")] = json.dumps(dict(
            status="MEASURED", measured_pairs=8, expected_pairs=8, routing_report_complete=False,
            artifacts=dict(gr_image=image), pairs=pairs,
            raw_source_records=[dict(sha256=review.frozen.digest(b'{"status":"fixture"}'))])).encode()
        files[str(review.CC_DIRECT / "data/receipts.tar.gz")] = files[str(self.resident / review.RECEIPTS)]
        return files

    def test_explicit_selection_preserves_same_host_fig8(self):
        paths = [str(path) for path in review.selection(self.name)]
        self.assertTrue(any(f"{self.name}/fig7_" in name for name in paths))
        self.assertFalse(any("resident_checkpoint_v2/" in name for name in paths))
        self.assertTrue(any("portable_fig8_headroom_v1/batch_sweep/" in name for name in paths))
        with self.assertRaises(ValueError):
            review.selection("../resident_checkpoint_v3")
        with self.assertRaisesRegex(ValueError, "pinned to resident_checkpoint_v3"):
            review.selection(self.name, cc_direct=True)

    def test_completion_is_not_an_all_win_claim(self):
        for pending in (True, False):
            files, _ = self.fixture(pending)
            summary = review.checkpoint(self.name, files.__getitem__)
            self.assertEqual(summary["complete"], not pending)
            self.assertFalse(summary["all_pairs_spine_wins"])
            self.assertEqual(len(summary["spine_wins"]), 21 if pending else 22)
            self.assertEqual(summary["gr_wins"][0]["algorithm"], "cc")
            self.assertEqual(summary["gr_wins"][0]["speedup_gr_over_spine"], .5)
            self.assertEqual(len(summary["ties"]), 1)
            self.assertEqual([row["status"] for row in summary["unmeasured"]],
                             ["LAYOUT_FAILURE"] if pending else [])

    def test_rejects_wrong_control_pin_and_disagreed_ratio(self):
        files, rows = self.fixture()
        files[str(review.CONTROLS)] = b"other"
        with self.assertRaisesRegex(ValueError, "not exported against"):
            review.checkpoint(self.name, files.__getitem__)
        next(row for row in rows if row["algorithm"] == "cc")["speedup_gr_over_spine"] = "2"
        self.write_rows(files, rows)
        with self.assertRaisesRegex(ValueError, "timing, boundary or receipt"):
            review.checkpoint(self.name, files.__getitem__)

    def test_rejects_substituted_cc_timing_boundary(self):
        files, rows = self.fixture()
        cc = next(row for row in rows if row["algorithm"] == "cc")
        cc["boundary"] = review.BOUNDARIES["weighted_sssp"]
        self.write_rows(files, rows)
        with self.assertRaisesRegex(ValueError, "timing, boundary or receipt"):
            review.checkpoint(self.name, files.__getitem__)

    def test_rejects_valid_pin_without_its_receipt(self):
        files, rows = self.fixture()
        rows[0]["receipt_sha256"] = "a" * 64
        self.write_rows(files, rows)
        with self.assertRaisesRegex(ValueError, "receipt not found in archive: weighted_sssp/AU"):
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

    def test_direct_overlay_keeps_qualifications_and_source_tables(self):
        files = self.direct_fixture()
        before = files[str(self.resident / review.CSV)]
        summary = review.selected_checkpoint(self.name, files.__getitem__, cc_direct=True)
        self.assertEqual(summary["fpga_pairs"], 24)
        self.assertTrue(summary["complete"])
        self.assertFalse(summary["cc_routing_report_complete"])
        self.assertFalse(summary["all_pairs_spine_wins"])
        rows = list(csv.DictReader(io.StringIO(review.complete_csv(self.name, files.__getitem__).decode())))
        self.assertEqual(len(rows), 24)
        self.assertEqual(sum(row["status"] == review.CC_MEASURED for row in rows), 8)
        self.assertTrue(all(row["source_csv"] for row in rows))
        self.assertEqual(files[str(self.resident / review.CSV)], before)

    def test_direct_overlay_rejects_timing_relabel_and_missing_receipt(self):
        for mutation, message in (("time", "timing or qualification"), ("receipt", "receipt missing")):
            files = self.direct_fixture()
            key = str(review.CC_DIRECT / "data/scope.json")
            scope = json.loads(files[key])
            if mutation == "time":
                scope["pairs"]["AU"]["spine_ms"] = 3
            else:
                scope["raw_source_records"][0]["sha256"] = "f" * 64
            files[key] = json.dumps(scope).encode()
            with self.assertRaisesRegex(ValueError, message):
                review.selected_checkpoint(self.name, files.__getitem__, cc_direct=True)

    def test_direct_overlay_archive_contains_complete_table(self):
        files = self.direct_fixture()
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name, blob in files.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(blob)
            destination = root / "review.tar.gz"
            manifest = review.build(root, self.name, destination, cc_direct=True)
            self.assertTrue(manifest["cc_direct"])
            self.assertEqual(review.verify_archive(destination), manifest)
            with tarfile.open(destination) as archive:
                combined = archive.extractfile(str(review.COMPLETE_CSV)).read()
            self.assertEqual(combined, review.complete_csv(self.name, files.__getitem__))
