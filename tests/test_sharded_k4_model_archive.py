"""Portable model archives reject unsafe, incomplete or mutated evidence."""

import copy
import hashlib
import io
from pathlib import Path
import tarfile
import tempfile
import unittest

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.model_archive import extracted


class ModelArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.archive = Path(self.temporary.name) / "evidence.tar.gz"

    def write_archive(self, name="nested/result.json", *, symlink=False):
        data = b'{"status":"PASS"}\n'
        with tarfile.open(self.archive, "w:gz") as stream:
            member = tarfile.TarInfo(name)
            if symlink:
                member.type, member.linkname = tarfile.SYMTYPE, "/etc/passwd"
            else:
                member.size = len(data)
            stream.addfile(member, None if symlink else io.BytesIO(data))
        return {"archive_sha256": sha256_file(self.archive), "archive_bytes": self.archive.stat().st_size,
                "files": [{"path": name, "bytes": 0 if symlink else len(data),
                           "sha256": hashlib.sha256(data).hexdigest()}]}

    def test_exact_regular_file_extracts_in_temporary_directory(self):
        record = self.write_archive()
        with extracted(self.archive, record, max_bytes=128) as root:
            self.assertEqual((root / "nested/result.json").read_bytes(), b'{"status":"PASS"}\n')
        self.assertFalse(root.exists())

    def test_changed_identity_size_or_content_rejected(self):
        record = self.write_archive()
        for field, value in (("archive_sha256", "0" * 64), ("archive_bytes", 0)):
            changed = record | {field: value}
            with self.subTest(field=field), self.assertRaises(ValueError):
                with extracted(self.archive, changed, max_bytes=128):
                    pass
        for field, value in (("sha256", "0" * 64), ("bytes", 0), ("path", "missing")):
            changed = copy.deepcopy(record)
            changed["files"][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                with extracted(self.archive, changed, max_bytes=128):
                    pass

    def test_paths_links_duplicates_and_oversize_rejected(self):
        for name in ("../escape", "/absolute"):
            record = self.write_archive(name)
            with self.subTest(name=name), self.assertRaises(ValueError):
                with extracted(self.archive, record, max_bytes=128):
                    pass
        record = self.write_archive(symlink=True)
        with self.assertRaises(ValueError):
            with extracted(self.archive, record, max_bytes=128):
                pass
        record = self.write_archive()
        for changed, limit in ((record | {"files": record["files"] * 2}, 128), (record, 1)):
            with self.assertRaises(ValueError):
                with extracted(self.archive, changed, max_bytes=limit):
                    pass


if __name__ == "__main__":
    unittest.main()
