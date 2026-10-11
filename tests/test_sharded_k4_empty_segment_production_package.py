"""Recheck the complete portable production archives without a vendor toolchain."""

import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile
import unittest

from spine_cycle_sim.experiments.sharded_k4_stages.empty_segment.production_validation import require_execution

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "docs/experiments/comparisons/grasu_regraph_stage_validation/actual_sharded_k4/adapter_optimization/empty_segment/production"


class EmptySegmentProductionPackageTests(unittest.TestCase):
    def read_archive(self, directory):
        verification = json.loads((directory / "verification.json").read_text())
        path = directory / Path(verification["archive"]["path"]).name
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), verification["archive"]["sha256"])
        expected = {row["path"]: row for row in verification["files"]}
        self.assertEqual(len(expected), len(verification["files"]))
        objects, observed = {}, set()
        with tarfile.open(path, "r|gz") as archive:
            for member in archive:
                name = PurePosixPath(member.name)
                self.assertFalse(name.is_absolute())
                self.assertNotIn("..", name.parts)
                self.assertTrue(member.isfile())
                self.assertNotIn(member.name, observed)
                observed.add(member.name)
                contents = archive.extractfile(member).read()
                self.assertEqual(member.size, expected[member.name]["bytes"])
                self.assertEqual(hashlib.sha256(contents).hexdigest(), expected[member.name]["sha256"])
                if member.name in ("manifest.json", "results.json", "compile.resources.json") or member.name.startswith("watchdog/") and member.name.endswith(".resources.json"):
                    objects[member.name] = json.loads(contents)
        self.assertEqual(observed, set(expected))
        return verification, expected, objects

    def test_both_production_attempts_keep_raw_sources_rtl_and_resources(self):
        for label in ("prior-v1", "current-v2"):
            with self.subTest(label=label):
                verification, entries, objects = self.read_archive(PACKAGE / label)
                self.assertEqual(verification["status"], "production_XO_ABI_rechecked_not_routed")
                report, manifest = objects["results.json"], objects["manifest.json"]
                self.assertEqual(report, json.loads((PACKAGE / label / "results.json").read_text()))
                self.assertEqual(report["status"], "production_XO_ABI_pass_not_routed")
                self.assertFalse(report["hardware_timing_admitted"])
                self.assertFalse(report["simulator_modified"])
                self.assertEqual(entries["adapter.hw.xo"]["sha256"], report["xo"]["sha256"])
                self.assertEqual(report["execution"], objects["compile.resources.json"])
                require_execution(objects["compile.resources.json"], budget=8, timeout=1200)
                watchdog = [value for key, value in objects.items() if key.startswith("watchdog/")]
                self.assertEqual(len(watchdog), 1)
                require_execution(watchdog[0], budget=10, timeout=1350)
                for pin in manifest["snapshots"]:
                    self.assertEqual(entries[pin["archive_path"]]["sha256"], pin["sha256"])
                self.assertTrue(any(name.endswith("syn/verilog/pma_to_regraph_adapter.v") for name in entries))
                self.assertTrue(any(name.endswith("syn/report/pma_to_regraph_adapter_csynth.xml") for name in entries))
                if label == "current-v2":
                    pins = [pin["path"] for pin in manifest["pins"]]
                    for suffix in ("sharded_k4_stages/rtl.py", "original_regraph_validation/analysis.py",
                                   "sssp_real_round/delivery.py", "functional_gate/raw_functional.tar.gz"):
                        self.assertTrue(any(name.endswith(suffix) for name in pins), suffix)
                    self.assertTrue(any("/paired-v2/skip_empty/project/solution/sim/tv/" in name for name in pins))

    def test_route_record_is_a_non_start_not_an_implementation_failure(self):
        verification, _, _ = self.read_archive(PACKAGE / "route-preparation")
        self.assertEqual(verification["status"], "ADMISSION_REJECTED_NOT_STARTED")
        self.assertFalse(verification["route_started"])
        admission = verification["admission"]
        self.assertLess(admission["available_bytes"], admission["required_bytes"])
        self.assertEqual(admission["required_bytes"], 56 * 1024**3)
        dependency = PACKAGE / "current-v2/verification.json"
        self.assertEqual(hashlib.sha256(dependency.read_bytes()).hexdigest(),
                         verification["production_dependency"]["sha256"])


if __name__ == "__main__":
    unittest.main()
