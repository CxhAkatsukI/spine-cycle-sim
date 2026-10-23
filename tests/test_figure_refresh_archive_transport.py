"""Multipart publication preserves the sealed bytes and rejects broken transport."""

import json
from pathlib import Path
import tempfile
import unittest

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.evaluation_impact.figure_refresh.multialgorithm import delivery


class ArchiveTransportTests(unittest.TestCase):
    def source(self, root):
        source = root / "source"
        (source / "evidence").mkdir(parents=True)
        (source / "data").mkdir()
        (source / "data/summary.json").write_text('{"fixture": true}\n')
        for name in ("README.md", "TEST_REPORT.md"):
            (source / name).write_text("Fixture\n")
        archive = source / "evidence/evidence.tar.gz"
        archive.write_bytes(bytes(range(256)) * 4)
        atomic_write_json(source / "evidence/index.json",
                          dict(archive=archive.name, sha256=sha256_file(archive)))
        return source

    def assembled_bytes(self, destination, index):
        record = dict(index, archive_sha256=index["sha256"])
        with delivery.assembled(destination / "evidence", record,
                                archive_name=index["archive"]) as archive:
            return archive.read_bytes()

    def test_lossless_publication_leaves_source_intact(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self.source(root)
            destination = root / "published"
            index = delivery.publish(source, destination, part_bytes=256)
            original = source / "evidence/evidence.tar.gz"
            self.assertEqual(self.assembled_bytes(destination, index), original.read_bytes())
            self.assertEqual(len(index["archive_parts"]), 4)
            self.assertFalse((destination / "evidence/evidence.tar.gz").exists())
            self.assertEqual(json.loads((destination / "evidence/index.json").read_text()), index)
            self.assertEqual((destination / "data/summary.json").read_bytes(),
                             (source / "data/summary.json").read_bytes())
            with self.assertRaises(ValueError):
                delivery.publish(source, destination)

    def test_corruption_missing_and_reordered_parts_rejected(self):
        for mode in ("corrupt", "missing", "reordered", "symlink", "total"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                source = self.source(root)
                destination = root / "published"
                index = delivery.publish(source, destination, part_bytes=256)
                part = destination / "evidence" / index["archive_parts"][0]["path"]
                if mode == "corrupt":
                    part.write_bytes(b"x" * 256)
                elif mode == "missing":
                    part.unlink()
                elif mode == "reordered":
                    index["archive_parts"].reverse()
                elif mode == "symlink":
                    part.unlink()
                    part.symlink_to(source / "evidence/evidence.tar.gz")
                else:
                    index["archive_bytes"] += 1
                with self.assertRaises((ValueError, FileNotFoundError)):
                    self.assembled_bytes(destination, index)

    def test_unknown_files_and_source_corruption_rejected(self):
        for mode in ("extra", "nested", "corrupt", "split"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                source = self.source(root)
                if mode == "extra":
                    (source / "forgotten.txt").write_text("Do not omit\n")
                elif mode == "nested":
                    (source / "evidence/forgotten.txt").write_text("Do not omit\n")
                elif mode == "corrupt":
                    (source / "evidence/evidence.tar.gz").write_bytes(b"changed")
                else:
                    path = source / "evidence/index.json"
                    record = json.loads(path.read_text())
                    record["archive_parts"] = []
                    atomic_write_json(path, record)
                with self.assertRaises(ValueError):
                    delivery.publish(source, root / "published")


if __name__ == "__main__":
    unittest.main()
