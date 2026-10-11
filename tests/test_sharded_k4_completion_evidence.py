"""Preserve the scope and raw integrity of the model-only completion finding."""

import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile
import tempfile
import unittest

from spine_cycle_sim.experiments.sharded_k4_stages.completion_delivery import package_completion_checkpoint


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "docs/experiments/comparisons/grasu_regraph_stage_validation/actual_sharded_k4/model_sync/sst/completion_diagnostic"


class CompletionEvidenceTests(unittest.TestCase):
    def test_scope_is_capped_and_unfixed(self):
        report = json.loads((PACKAGE / "completion.json").read_text())
        self.assertEqual(report["status"], "MODEL_CROSS_OPERATION_STALL_REPRODUCED_NOT_FIXED")
        self.assertFalse(report["hardware_timing_admitted"])
        self.assertFalse(report["model_changed"])
        self.assertEqual(report["capped_probe"]["observed_cycles"], 20000000)
        self.assertFalse(report["capped_probe"]["success"])
        self.assertFalse(report["capped_probe"]["done"])
        rows = {row["case"]: row for row in report["isolated_controls"]["rows"]}
        self.assertEqual(set(rows), {"held_stream", "drained_stream", "ordinary_read"})
        self.assertGreaterEqual(rows["held_stream"]["write_issue"], 200)
        for name in ("drained_stream", "ordinary_read"):
            self.assertLess(rows[name]["write_issue"], 200)
        self.assertTrue(all(row["registration_order_equal"] for row in rows.values()))

    def test_frozen_archive_hashes(self):
        index = json.loads((PACKAGE / "completion_raw_index.json").read_text())
        expected = {item["archive_path"]: item["sha256"] for item in index["files"]}
        self.assertEqual(len(expected), len(index["files"]))
        with (PACKAGE / "raw_completion.tar.gz").open("rb") as stream:
            self.assertEqual(hashlib.file_digest(stream, "sha256").hexdigest(), index["archive"]["sha256"])
        seen = set()
        with tarfile.open(PACKAGE / "raw_completion.tar.gz", "r|gz") as archive:
            for member in archive:
                self.assertTrue(member.isfile())
                self.assertFalse(PurePosixPath(member.name).is_absolute())
                self.assertNotIn("..", PurePosixPath(member.name).parts)
                self.assertNotIn(member.name, seen)
                seen.add(member.name)
                self.assertEqual(hashlib.file_digest(archive.extractfile(member), "sha256").hexdigest(),
                                 expected[member.name])
        self.assertEqual(seen, set(expected))

    def test_existing_package_is_never_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            (output / "completion.json").touch()
            with self.assertRaises(FileExistsError):
                package_completion_checkpoint(ROOT, Path("missing"), output)


if __name__ == "__main__":
    unittest.main()
