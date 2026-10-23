"""The delivered A4 control is verifiable without machine-local inputs."""

import copy
import json
from pathlib import Path
import tarfile
import unittest

from spine_cycle_sim.experiments.evaluation_impact.warm_comparison import a4_delivery

ROOT = Path(__file__).resolve().parents[1]
CAPSULE = ROOT / "docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/warm_comparison/same_batch_a4"


class WarmA4DeliveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = a4_delivery.verify(CAPSULE)
        with tarfile.open(CAPSULE / "evidence.tar.gz") as archive:
            cls.files = {member.name: archive.extractfile(member).read() for member in archive.getmembers()}
        cls.report = json.loads(cls.files["results.json"])

    def validate(self, report=None, files=None, states=None):
        return a4_delivery.validate(report or self.report, (files or self.files).__getitem__,
                                    states or self.index["states"], self.index["warm_states"])

    def test_committed_capsule_retains_nonpassing_conditions(self):
        result = self.validate()
        self.assertEqual(sum(r["within_15pct"] for r in result), 1)
        self.assertEqual(len(result), 4)
        self.assertFalse(self.index["baseline_admitted"])
        self.assertFalse(self.index["host_time_included"])

    def test_changed_raw_record_is_rejected(self):
        files = dict(self.files)
        files["raw/smoke_lat64_a4_order0.stdout.txt"] = b"WARM_INPUT {}\nDEMO_RESULT {}\nDEMO_ROUND {}\n"
        with self.assertRaisesRegex(ValueError, "raw"):
            self.validate(files=files)

    def test_full_state_extent_and_identity_cannot_be_changed(self):
        for field in ("bytes", "sha256"):
            states = copy.deepcopy(self.index["states"])
            states["amazon_lat64_a4_order0/final.u32le"][field] = 0
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "state"):
                self.validate(states=states)

    def test_deleted_row_or_claimed_host_time_rejected(self):
        report = copy.deepcopy(self.report)
        report["rows"].pop()
        with self.assertRaises(ValueError):
            self.validate(report=report)
        report = copy.deepcopy(self.report)
        report["host_time_included"] = True
        with self.assertRaisesRegex(ValueError, "device prediction"):
            self.validate(report=report)


if __name__ == "__main__":
    unittest.main()
