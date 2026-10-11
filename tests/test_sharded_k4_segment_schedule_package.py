"""Recheck helper RTL evidence without Vivado or external campaign files."""

import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile
import unittest

from spine_cycle_sim.experiments.sharded_k4_stages.segment_schedule import (
    BENCH, BENCH_SHA, FILES, FLOW_HASH, RTL_HASHES, parse_trace,
)


ROOT = Path(__file__).resolve().parents[1]
PARENT = ROOT / "docs/experiments/comparisons/grasu_regraph_stage_validation/actual_sharded_k4/model_sync/sst"
PACKAGE = PARENT / "occupied_row_rtl"


class SegmentSchedulePackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = json.loads((PACKAGE / "schedule_raw_index.json").read_text())
        cls.report = json.loads((PACKAGE / "schedule.json").read_text())
        with tarfile.open(PACKAGE / "raw_schedule.tar.gz") as stream:
            cls.members = stream.getmembers()
            cls.files = {m.name: stream.extractfile(m).read() for m in cls.members}

    def test_archive_paths_and_all_hashes(self):
        pins = {p["archive_path"]: p["sha256"] for p in self.index["files"]}
        self.assertEqual(len(pins), len(self.index["files"]))
        self.assertEqual(len(self.members), len(self.files))
        self.assertEqual(set(pins), set(self.files))
        for m in self.members:
            self.assertTrue(m.isfile())
            self.assertFalse(PurePosixPath(m.name).is_absolute())
            self.assertNotIn("..", PurePosixPath(m.name).parts)
            self.assertEqual(hashlib.sha256(self.files[m.name]).hexdigest(), pins[m.name])
        self.assertEqual(hashlib.sha256((PACKAGE / "raw_schedule.tar.gz").read_bytes()).hexdigest(),
                         self.index["archive"]["sha256"])
        dependency = PARENT / "empty_row_rtl/rtl_raw_index.json"
        self.assertEqual(len(self.index["dependencies"]), 1)
        self.assertEqual(hashlib.sha256(dependency.read_bytes()).hexdigest(),
                         self.index["dependencies"][0]["sha256"])

    def test_both_pinned_helpers_and_successful_twelve_case_logs(self):
        saved = json.loads(self.files["final/summary.json"])
        self.assertEqual(saved["status"], "SEGMENT_RTL_PASS")
        for arm in ("original", "candidate"):
            prefix = f"final/{arm}/"
            expected = {FILES[k]: RTL_HASHES[arm][k] for k in ("parent", "helper")}
            expected.update({FILES["flow"]: FLOW_HASH, BENCH: BENCH_SHA})
            for name, checksum in expected.items():
                self.assertEqual(hashlib.sha256(self.files[prefix + name]).hexdigest(), checksum)
            self.assertEqual(self.files[prefix + "run.tcl"].decode().strip(), "run all\nquit")
            inputs = json.loads(self.files[prefix + "inputs.json"])
            self.assertEqual(inputs["arm"], arm)
            self.assertEqual({Path(p["path"]).name for p in inputs["sources"]}, {*expected, "run.tcl"})
            for pin in inputs["sources"]:
                self.assertEqual(hashlib.sha256(self.files[prefix + Path(pin["path"]).name]).hexdigest(),
                                 pin["sha256"])
            for step in ("compile", "elaborate", "simulate"):
                record = json.loads(self.files[prefix + step + ".resources.json"])
                self.assertEqual(record["exit_code"], 0)
                self.assertFalse(record["timed_out"])
                self.assertEqual(record, self.report["arms"][arm]["verification"][step])
            rows = parse_trace(self.files[prefix + "simulate.stdout.txt"].decode())
            self.assertEqual(rows, saved["arms"][arm])
            self.assertEqual(rows, self.report["arms"][arm]["trials"])
        self.assertEqual(saved["arms"]["original"], saved["arms"]["candidate"])

    def test_scope_limits_and_exploratory_failures_preserved(self):
        self.assertEqual(self.report["status"], "OCCUPIED_SEGMENT_ROUTED_RTL_COMPONENT_PASS")
        for field in ("hardware_timing_admitted", "original_A4_match_admitted",
                      "timing_fit_performed", "simulator_profile_changed"):
            self.assertFalse(self.report[field])
        for attempt in ("attempt1", "attempt2"):
            log = self.files[f"exploratory/{attempt}/original/simulate.stdout.txt"].decode()
            with self.assertRaises(ValueError):
                parse_trace(log)
        for arm in ("original", "candidate"):
            log = self.files[f"exploratory/attempt3/{arm}/simulate.stdout.txt"].decode()
            self.assertEqual(parse_trace(log), self.report["arms"][arm]["trials"])


if __name__ == "__main__":
    unittest.main()
