"""Keep image identity and actual driver clock observations auditable."""

import json
from pathlib import Path
import shutil
import tempfile
import unittest

from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention import clocks
from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention.runtime import identity


class SourceRetentionClocksTest(unittest.TestCase):
    def fixture(self, root):
        device = root / "sysfs/0000:c1:00.1"
        icap = device / "icap.u.123"
        icap.mkdir(parents=True)
        expected = {"uuid": "9a8a3380-fec2-6cbf-2ff9-c9fadabc8998", "binary": {"sha256": "example"}}
        (device / "xclbinuuid").write_text(expected["uuid"] + "\n")
        (icap / "clock_freqs").write_text("145\n500\n430\n0\n")
        output = root / "campaign"
        output.mkdir()
        info = output / "image.txt"
        info.write_text("UUID (xclbin): " + expected["uuid"] + "\n")
        expected["info"] = identity(info)
        return device, expected, output

    def test_capture_preserves_observed_not_requested_frequency(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            device, expected, output = self.fixture(root)
            evidence = clocks.capture(device.name, expected, output, "current", device_root=device.parent)
            self.assertEqual(clocks.replay(evidence)["driver_reported_mhz"], [145, 500, 430, 0])
            archive = root / "archive/campaign"
            shutil.copytree(output, archive)
            self.assertEqual(clocks.replay(evidence, archive.parent)["uuid"], expected["uuid"])

    def test_wrong_image_and_zero_clocks_are_rejected_with_raw_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            device, expected, output = self.fixture(Path(temporary))
            (device / "xclbinuuid").write_text("00000000-0000-0000-0000-000000000000")
            with self.assertRaises(ValueError):
                clocks.capture(device.name, expected, output, "wrong", device_root=device.parent)
            self.assertTrue((output / "wrong.clock-raw.json").is_file())
            (device / "xclbinuuid").write_text(expected["uuid"])
            (device / "icap.u.123/clock_freqs").write_text("0\n500\n430\n0\n")
            with self.assertRaises(ValueError):
                clocks.capture(device.name, expected, output, "zero", device_root=device.parent)

    def test_changed_raw_record_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            device, expected, output = self.fixture(Path(temporary))
            evidence = clocks.capture(device.name, expected, output, "run", device_root=device.parent)
            path = output / "run.clock-raw.json"
            raw = json.loads(path.read_text())
            raw["clock_freqs"] = "150\n500\n430\n0\n"
            path.write_text(json.dumps(raw))
            with self.assertRaises(ValueError):
                clocks.replay(evidence)

    def test_image_output_must_have_exactly_one_uuid(self):
        for text in ("", "UUID (xclbin): invalid", "UUID (xclbin): 123\nUUID (xclbin): 456"):
            with self.assertRaises(ValueError):
                clocks.image_uuid(text)


if __name__ == "__main__":
    unittest.main()
