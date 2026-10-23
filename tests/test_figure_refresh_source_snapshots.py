"""Large historical docs may be external only with a verified source replacement."""

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from spine_cycle_sim.experiments.evaluation_impact.figure_refresh.multialgorithm import source_snapshots


class SourceSnapshotTests(unittest.TestCase):
    def fixture(self, root):
        directory = root / "before"
        directory.mkdir()
        report = dict(status="PRECHANGE_GIT_SOURCE_SNAPSHOT", commit="a" * 40)
        for key, suffix, blob in (("full_repository_snapshot", ".tar.gz", b"historical docs"),
                                  ("code_only_snapshot", "-code-only.tar.gz", b"frozen code")):
            path = directory / ("source-aaaaaaa" + suffix)
            path.write_bytes(blob)
            report[key] = dict(path=str(path), bytes=len(blob), sha256=hashlib.sha256(blob).hexdigest())
        report["full_repository_snapshot"].update(external=True, reason="Repeated historical documentation")
        (root / source_snapshots.INDEX).write_text(json.dumps(report))
        return report

    def test_only_indexed_full_snapshot_is_external_and_stays_on_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = self.fixture(root)
            excluded, records = source_snapshots.collect(root)
            full = Path(report["full_repository_snapshot"]["path"])
            self.assertEqual(excluded, {full})
            self.assertTrue(full.exists())
            files = {source_snapshots.INDEX: (root / source_snapshots.INDEX).read_bytes(),
                     "before/source-aaaaaaa-code-only.tar.gz": b"frozen code"}
            source_snapshots.verify(files.__getitem__, files, records)
            for mode in ("changed_compact", "recursive_full", "missing_record", "changed_record"):
                changed, rows = copy.deepcopy(files), copy.deepcopy(records)
                if mode == "changed_compact":
                    changed["before/source-aaaaaaa-code-only.tar.gz"] = b"other code"
                elif mode == "recursive_full":
                    changed[rows[0]["omitted_member"]] = full.read_bytes()
                elif mode == "missing_record":
                    rows = []
                else:
                    rows[0]["sha256"] = "f" * 64
                with self.subTest(mode=mode), self.assertRaises(ValueError):
                    source_snapshots.verify(changed.__getitem__, changed, rows)

    def test_missing_changed_symlink_or_outside_replacement_is_rejected(self):
        for mode in ("missing", "changed", "symlink", "outside"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                report = self.fixture(root)
                compact = Path(report["code_only_snapshot"]["path"])
                if mode == "missing":
                    compact.unlink()
                elif mode == "changed":
                    compact.write_bytes(b"changed")
                elif mode == "symlink":
                    compact.unlink()
                    compact.symlink_to(report["full_repository_snapshot"]["path"])
                else:
                    report["code_only_snapshot"]["path"] = str(root / compact.name)
                    (root / source_snapshots.INDEX).write_text(json.dumps(report))
                with self.assertRaises(ValueError):
                    source_snapshots.collect(root)

    def test_no_policy_does_not_silently_skip_any_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(source_snapshots.collect(Path(tmp)), (set(), []))
            source_snapshots.verify(lambda _: b"", [], [])


if __name__ == "__main__":
    unittest.main()
