import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments import artifact_transport as transport


class ArtifactTransportTests(unittest.TestCase):
    def test_roundtrip_and_corruption_gates(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(transport, "CHUNK_BYTES", 8):
            root = Path(temporary)
            source = root / "raw.tar.xz"
            source.write_bytes(b"abcdefghijklmnopq")
            directory = root / "parts"
            report = transport.split(source, directory)
            self.assertEqual([part["bytes"] for part in report["parts"]], [8, 8, 1])
            output = root / "reassembled"
            transport.join(directory, output)
            self.assertEqual(source.read_bytes(), output.read_bytes())
            with self.assertRaises(FileExistsError):
                transport.join(directory, output)
            (directory / "part001").write_bytes(b"xxxxxxxx")
            with self.assertRaises(ValueError):
                transport.verify(directory)

    def test_reject_unsafe_or_incomplete_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.write_bytes(b"payload")
            report = transport.split(source, root / "parts")
            report["parts"][0]["name"] = "../source"
            (root / "parts/transport.json").write_text(json.dumps(report))
            with self.assertRaises(ValueError):
                transport.verify(root / "parts")


if __name__ == "__main__":
    unittest.main()
