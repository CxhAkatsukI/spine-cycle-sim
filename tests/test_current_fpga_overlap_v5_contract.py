from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "configs/contracts/current_fpga_spine_overlap_cases_v5.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


class CurrentFPGAOverlapV5ContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.contract = json.loads(CONTRACT.read_text(encoding="utf-8"))

    def test_roles_are_frozen_and_disjoint(self) -> None:
        self.assertEqual(
            self.contract["status"], "frozen_before_holdout_execution"
        )
        calibration = set(self.contract["roles"]["calibration"])
        holdout = set(self.contract["roles"]["holdout"])
        self.assertEqual(len(calibration), 8)
        self.assertEqual(holdout, {"au_u64", "su_u64"})
        self.assertTrue(calibration.isdisjoint(holdout))

    def test_plugin_and_profile_identities_match(self) -> None:
        for spec in (self.contract["simulator_plugin"], self.contract["profile"]):
            path = ROOT / spec["path"]
            self.assertTrue(path.is_file())
            self.assertEqual(sha256_file(path), spec["sha256"])

    def test_holdout_hashes_are_pinned(self) -> None:
        workloads = self.contract["holdout_workloads"]
        self.assertEqual(set(workloads), {"au_u64", "su_u64"})
        for spec in workloads.values():
            self.assertEqual(spec["batch_size"], 64)
            for key in (
                "graph_sha256",
                "initial_slice_sha256",
                "update_slice_sha256",
            ):
                self.assertEqual(len(spec[key]), 64)

    def test_overlap_form_never_sums_reader_and_compute(self) -> None:
        target = self.contract["timing_target"]
        self.assertEqual(target["iterative_span"], "median routed kernel_span_ms")
        self.assertFalse(
            self.contract["admission"]["hardware_reader_compute_intervals_summed"]
        )
        self.assertFalse(self.contract["model"]["holdout_may_fit"])


if __name__ == "__main__":
    unittest.main()
