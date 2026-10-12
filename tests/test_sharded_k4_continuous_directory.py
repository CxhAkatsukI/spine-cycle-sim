"""Reject relaxed replay checks and nominal schedules that HLS did not realize."""

import copy
import json
from pathlib import Path
import tempfile
import tarfile
import unittest

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.continuous_directory.analysis import (
    admit, validate_matrix,
)
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.continuous_directory.decision import (
    decide, loop_schedule,
)
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.continuous_directory.recheck import (
    require_pin, source_archive,
)
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.continuous_directory.archive_parts import (
    ARCHIVE, assembled, split,
)


class ContinuousDirectoryAdmissionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.state = Path(temporary.name)
        outputs = []
        for name in ("primary", "source0", "source1"):
            path = self.state / (name + ".u32le")
            path.write_bytes(bytes(range(64)))
            outputs.append({"path": str(path), "bytes": 64, "sha256": sha256_file(path)})
        self.counters = {"cycles": 500, "passed": True, "read_bytes": 2048,
                         "physical_packets": 8, "replicas": 3}
        self.invocations = [{"round": 1, "partition": p, "worker": p, "adapter": a,
                             "start": 0, "end": 490 + p}
                            for p in range(4) for a in (True, False)]
        self.basis = {"cases": [{"mode": "cold", "latency": 64, "reverse": 0, "arm": "original",
                                 "paths": [{"cycles": 100}], "outputs": outputs},
                                {"mode": "cold", "latency": 64, "reverse": 0, "arm": "cross_row",
                                 "counters": dict(self.counters, cycles=800), "outputs": outputs,
                                 "invocations": copy.deepcopy(self.invocations)}]}
        self.declaration = {"version": "continuous_directory_v1", "continuous_directory": 1,
                            "cross_row_pipeline": 1, "row_line_reads": 1, "fixed_rounds": 1,
                            "hardware_timing_admitted": False, "strict_resource_match_admitted": False}

    def stdout(self):
        return "\n".join(["MODEL_CONTROL " + json.dumps(self.declaration),
                          "REAL_ROUND " + json.dumps(self.counters),
                          *("INVOCATION " + json.dumps(row) for row in self.invocations)])

    def check(self, arm="continuous"):
        return admit(self.stdout(), self.state, self.basis, "cold", 64, 0, arm, self.stdout())

    def test_full_state_and_conserved_work(self):
        self.assertEqual(self.check()["candidate_over_A4"], 5)
        self.assertEqual(len(self.check()["outputs"]), 3)

    def test_default_reference_cycles_and_schedule_not_relaxed(self):
        self.declaration["continuous_directory"] = 0
        with self.assertRaisesRegex(ValueError, "replay"):
            self.check("cross_row")
        self.counters["cycles"] = 800
        self.check("cross_row")
        self.invocations[0]["end"] += 1
        with self.assertRaisesRegex(ValueError, "schedule"):
            self.check("cross_row")

    def test_numeric_and_bool_types_are_not_interchangeable(self):
        for owner, key in ((self.counters, "cycles"), (self.counters, "replicas"),
                           (self.counters, "passed"), (self.declaration, "continuous_directory"),
                           (self.invocations[0], "adapter"), (self.invocations[0], "partition")):
            before = owner[key]
            owner[key] = int(before) if type(before) is bool else bool(before)
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.check()
            owner[key] = before

    def test_missing_duplicate_and_extra_output_rejected(self):
        original = copy.deepcopy(self.invocations)
        for changed in (original[:-1], original + original[:1],
                        [dict(original[0], worker=3), *original[1:]],
                        [dict(original[0], extra=1), *original[1:]]):
            self.invocations = changed
            with self.assertRaises(ValueError):
                self.check()
        self.invocations = original
        with self.assertRaises(ValueError):
            self.check("other")
        with self.assertRaises(ValueError):
            admit(self.stdout() + "\nEXTRA {}", self.state, self.basis,
                  "cold", 64, 0, "continuous", self.stdout())

    def test_work_and_all_state_bytes_are_required(self):
        self.counters["read_bytes"] += 64
        with self.assertRaisesRegex(ValueError, "physical work"):
            self.check()
        self.counters["read_bytes"] -= 64
        (self.state / "source1.u32le").write_bytes(b"x" * 64)
        with self.assertRaisesRegex(ValueError, "state oracle"):
            self.check()

    def test_original_exact_typed_replay(self):
        self.basis["cases"][0]["outputs"] = self.basis["cases"][1]["outputs"]
        previous = self.stdout()
        self.counters["passed"] = 1
        with self.assertRaisesRegex(ValueError, "original A4"):
            admit(self.stdout(), self.state, self.basis, "cold", 64, 0, "original", previous)

    def test_matrix_complete_order_independent_and_sensitive(self):
        cases = [{"mode": mode, "latency": latency, "reverse": reverse, "arm": arm,
                  "cycles": latency * 100, "records": {"passed": True}}
                 for mode, latency in (("cold", 64), ("warm_update", 64), ("warm_update", 128))
                 for reverse in (0, 1) for arm in ("original", "cross_row", "continuous")]
        validate_matrix(list(reversed(cases)))
        with self.assertRaises(ValueError):
            validate_matrix(cases[:-1])
        changed = copy.deepcopy(cases)
        changed[-1]["cycles"] -= 1
        with self.assertRaisesRegex(ValueError, "registration order"):
            validate_matrix(changed)
        changed = copy.deepcopy(cases)
        for row in changed:
            if row["arm"] == "continuous":
                row["cycles"] = 6400
        with self.assertRaisesRegex(ValueError, "latency sensitivity"):
            validate_matrix(changed)


class RealizedScheduleTests(unittest.TestCase):
    def test_structured_loop_report_and_missing_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "loop.xml"
            path.write_text("""<profile><UserAssignments><TargetClockPeriod>6.67</TargetClockPeriod>
                </UserAssignments><PerformanceEstimates><SummaryOfTimingAnalysis>
                <EstimatedClockPeriod>13.845</EstimatedClockPeriod></SummaryOfTimingAnalysis>
                <SummaryOfLoopLatency><read_continuous_sources_loop><PipelineII>71</PipelineII>
                <PipelineDepth>74</PipelineDepth></read_continuous_sources_loop></SummaryOfLoopLatency>
                </PerformanceEstimates></profile>""")
            self.assertEqual(loop_schedule(path)["achieved_ii"], 71)
            path.write_text("<profile/>")
            with self.assertRaisesRegex(ValueError, "missing"):
                loop_schedule(path)

    def test_functional_pass_does_not_admit_nominal_prediction(self):
        from unittest.mock import patch
        hls = {"status": "PASS_HLS_AXI_NOT_ROUTED", "hardware_timing_admitted": False,
               "comparison": [], "arms": {
                   "reference": [{"trial": 0, "cycles": 100}],
                   "candidate": [{"trial": 0, "cycles": 200}]}}
        schedule = {"achieved_ii": 71, "target_period_ns": 6.67, "estimated_period_ns": 13.845}
        with patch("spine_cycle_sim.experiments.sharded_k4_stages.row_line.continuous_directory.decision.compare_traffic",
                   return_value=[]):
            result = decide(hls, schedule)
            self.assertEqual(result["status"], "REJECTED_CANDIDATE")
            self.assertEqual(len(result["reasons"]), 3)
            self.assertFalse(result["nominal_prediction_admitted"])
            self.assertFalse(result["production_promotion"])
            hls["arms"]["candidate"][0]["cycles"] = 90
            schedule.update(achieved_ii=1, estimated_period_ns=5)
            result = decide(hls, schedule)
            self.assertEqual(result["status"], "NEEDS_ROUTE_AND_BOARD")
            self.assertFalse(result["hardware_timing_admitted"])


class PortableEvidenceTests(unittest.TestCase):
    def test_sha_and_optional_size_are_required(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "output.bin"
            path.write_bytes(b"recorded output")
            pin = {"sha256": sha256_file(path)}
            require_pin(path, pin)
            with self.assertRaises(ValueError):
                require_pin(path, dict(pin, bytes=1))
            path.write_bytes(b"modified output")
            with self.assertRaises(ValueError):
                require_pin(path, pin)

    def test_executed_source_membership_and_bytes_are_required(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary)
            source = run / "CMakeLists.txt"
            source.write_text("project(frozen)\n")
            pin = {"path": "/frozen/repository/CMakeLists.txt", "sha256": sha256_file(source)}
            (run / "manifest.json").write_text(json.dumps({"sources": [pin]}))
            def seal(name):
                with tarfile.open(run / "sources.tar.gz", "w:gz") as archive:
                    archive.add(source, arcname=name)
            seal("simulator/CMakeLists.txt")
            source_archive(run)
            seal("simulator/unexpected.txt")
            with self.assertRaisesRegex(ValueError, "membership"):
                source_archive(run)
            source.write_text("project(changed)\n")
            seal("simulator/CMakeLists.txt")
            with self.assertRaisesRegex(ValueError, "bytes"):
                source_archive(run)


class ArchiveTransportTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "source.gz"
        self.source.write_bytes(bytes(range(37)))
        self.parts = self.root / "parts"
        self.record = {"archive_parts": split(self.source, self.parts, part_bytes=16),
                       "archive_bytes": 37, "archive_sha256": sha256_file(self.source)}

    def test_lossless_bounded_transport_and_legacy_path(self):
        self.assertEqual([p["bytes"] for p in self.record["archive_parts"]], [16, 16, 5])
        with assembled(self.parts, self.record) as archive:
            self.assertEqual(archive.read_bytes(), self.source.read_bytes())
        with assembled(self.parts, {}) as archive:
            self.assertEqual(archive, self.parts / ARCHIVE)

    def test_modified_part_and_aggregate_hash_rejected(self):
        changed = copy.deepcopy(self.record)
        changed["archive_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "reassembled archive hash"):
            with assembled(self.parts, changed):
                pass
        path = self.parts / self.record["archive_parts"][0]["path"]
        path.write_bytes(b"x" * 16)
        with self.assertRaisesRegex(ValueError, "part identity"):
            with assembled(self.parts, self.record):
                pass

    def test_order_paths_sizes_and_symlinks_rejected(self):
        for field, value in (("path", "../../outside"), ("bytes", 0), ("bytes", True)):
            changed = copy.deepcopy(self.record)
            changed["archive_parts"][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                with assembled(self.parts, changed):
                    pass
        changed = copy.deepcopy(self.record)
        changed["archive_parts"].reverse()
        with self.assertRaises(ValueError):
            with assembled(self.parts, changed):
                pass
        path = self.parts / self.record["archive_parts"][0]["path"]
        path.unlink()
        path.symlink_to(self.source)
        with self.assertRaisesRegex(ValueError, "part identity"):
            with assembled(self.parts, self.record):
                pass

    def test_refuse_existing_destination_or_unbounded_part_size(self):
        for path, size in ((self.parts, 16), (self.root / "extra", 0)):
            with self.assertRaises(ValueError):
                split(self.source, path, part_bytes=size)


if __name__ == "__main__":
    unittest.main()
