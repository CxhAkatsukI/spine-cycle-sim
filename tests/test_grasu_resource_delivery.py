"""Retain query failures without promoting storage screens to hardware evidence."""

import json
from pathlib import Path
import tempfile
import unittest

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.resource_delivery import (
    CLAIMS, package, validate_query, verify)


class ResourceDeliveryTests(unittest.TestCase):
    def fixture(self, root):
        attempt = root / "query-timeout"
        source = attempt / "source/probe.py"
        source.parent.mkdir(parents=True)
        source.write_text("# frozen probe\n")
        platform = attempt / "platform/checkpoint.dcp"
        platform.parent.mkdir()
        platform.write_bytes(b"vendor placeholder must not be archived")
        execution = {"exit_code": -9, "timed_out": True}
        (attempt / "execution.resources.json").write_text(json.dumps(execution))
        result = {"status": "FAILED_RETAINED", "errors": ["timeout"], "execution": execution,
                  "source": [{"path": str(path), "sha256": sha256_file(path)} for path in (source, platform)],
                  **dict.fromkeys((*CLAIMS, "platform_available_resources_admitted"), False)}
        (attempt / "results.json").write_text(json.dumps(result))
        return attempt, result

    def test_failure_portable_and_vendor_checkpoint_excluded(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            attempt, _ = self.fixture(root)
            output = root / "delivery"
            index = package(output, [attempt])
            self.assertEqual(verify(output), index)
            entry = index["attempts"][0]
            self.assertEqual(entry["status"], "FAILED_RETAINED")
            self.assertFalse(any(row["path"].startswith("platform/") for row in entry["files"]))
            self.assertEqual(len(entry["external_input_pins"]), 1)
            self.assertFalse(index["complete_g_resource_fit_admitted"])
            (output / entry["archive"]).write_bytes(b"changed")
            with self.assertRaises(ValueError):
                verify(output)

    def test_cannot_relabel_timeout_as_completed_or_promote_claim(self):
        with tempfile.TemporaryDirectory() as folder:
            attempt, result = self.fixture(Path(folder))
            result.update(status="PHYSICAL_SITE_CAPACITY_QUERIED_NOT_ROUTE_ADMISSION", errors=[])
            with self.assertRaises(ValueError):
                validate_query(attempt, result)
            result.update(status="FAILED_RETAINED", errors=["timeout"], hardware_timing_admitted=True)
            with self.assertRaises(ValueError):
                validate_query(attempt, result)

    def test_changed_frozen_source_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            attempt, _ = self.fixture(root)
            (attempt / "source/probe.py").write_text("# modified after execution\n")
            with self.assertRaises(ValueError):
                package(root / "delivery", [attempt])


if __name__ == "__main__":
    unittest.main()
