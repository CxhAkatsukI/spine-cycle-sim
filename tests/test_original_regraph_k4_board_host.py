"""Compile the real K4 board host, but test only preparation and no-lease rejection."""

import json
import copy
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import test_original_regraph_k4_model as fixtures
from spine_cycle_sim.experiments.original_regraph_execution.hardware import oracle
from spine_cycle_sim.experiments.original_regraph_execution.hardware.k4_control import board_analysis, board_build
from spine_cycle_sim.experiments.upstream_controls.execution import dependency_identities

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "cpp/tests/original_regraph/integrated"
PRODUCTION = fixtures.PRODUCTION_INCLUDE.parent


class OriginalRegraphK4BoardHostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.require_finite_cgroup()
        cls.temporary = tempfile.TemporaryDirectory(prefix="original-r-k4-host-tests-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.directory = Path(cls.temporary.name)
        cls.fixture = cls.directory / "fixture"
        fixtures.fixture(cls.fixture)
        cls.binaries = {}
        for variant in ("release", "ubsan"):
            for target in ("control", "schedule_tests"):
                binary = cls.directory / f"{target}-{variant}"
                dependency = binary.with_suffix(".d")
                command = board_build.command(Path("/usr/bin/g++"), SOURCES, PRODUCTION,
                                              binary, dependency, variant, target)
                result = subprocess.run(command, text=True, capture_output=True, timeout=90)
                if result.returncode:
                    raise RuntimeError(f"{variant}/{target} compile failed:\n{result.stdout}{result.stderr}")
                dependencies = dependency_identities(dependency, ROOT)
                expected = SOURCES / ("device.hpp" if target == "control" else "schedule.hpp")
                if not any(pin["path"] == str(expected.resolve()) for pin in dependencies):
                    raise RuntimeError("Real K4 host dependency closure missing")
                cls.binaries[variant, target] = binary

    def invoke(self, variant, target, arguments, *, ok=True):
        environment = {key: value for key, value in os.environ.items()
                       if key not in ("ORIGINAL_R_LEASE_FD", "ORIGINAL_R_EXPECT_BDF")}
        environment["UBSAN_OPTIONS"] = "halt_on_error=1:print_stacktrace=1"
        result = subprocess.run([str(self.binaries[variant, target]), *map(str, arguments)],
            text=True, capture_output=True, timeout=45, env=environment)
        self.assertEqual(result.returncode, 0 if ok else 1, result.stdout + result.stderr)
        self.assertNotIn("runtime error:", result.stderr)
        return result

    def test_real_xrt_linkage_and_canonical_dependency_target(self):
        for variant in ("release", "ubsan"):
            result = subprocess.run(["/usr/bin/ldd", str(self.binaries[variant, "control"])],
                                    text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            board_build.resolved_libraries(result.stdout, result.stderr)
        command = board_build.command(Path("/usr/bin/g++"), SOURCES, PRODUCTION,
                                      Path("/tmp/test"), Path("/tmp/test.d"), "release", "control")
        self.assertEqual(command[command.index("-MT") + 1], "probe")
        self.assertIn("-ffp-contract=off", command)
        self.assertIn("-fno-fast-math", command)
        with self.assertRaises(ValueError):
            board_build.command(Path("/usr/bin/g++"), SOURCES, PRODUCTION, Path("/tmp/test"),
                                Path("/tmp/test.d"), "unknown", "control")
        with self.assertRaises(ValueError):
            board_build.command(Path("/usr/bin/g++"), SOURCES, PRODUCTION, Path("/tmp/test"),
                                Path("/tmp/test.d"), "release", "unknown")

    def test_stream_schedule_and_overlap_windows(self):
        for variant in ("release", "ubsan"):
            result = self.invoke(variant, "schedule_tests", [])
            self.assertEqual(result.stdout.strip(), "K4_SCHEDULE_TESTS_PASS_NOT_FPGA")

    def check_preparation(self, directory, variant, binding):
        output = self.directory / f"{self._testMethodName}-{directory.name}-{variant}-{binding}"
        self.invoke(variant, "control", ["prepare", directory, binding, output])
        result = json.loads((output / "result.json").read_text())
        self.assertEqual(result["status"], "K4_BOARD_HOST_PREFLIGHT_PASS_NOT_FPGA")
        self.assertEqual(result["binding"], binding)
        for key in ("board_programmed", "hardware_timing_measured", "complete_buffers_verified",
                    "publication_match", "default_profile_equivalence", "same_resource_claim",
                    "host_inclusive_measured", "convergence_measured"):
            self.assertIs(result[key], False)
        for key in ("enqueue_to_completion_ms", "event_union_ns", "event_span_ns"):
            self.assertIsNone(result[key])
        self.assertEqual(result["events"], [])
        vertices = fixtures.words(directory / "execution.u32le")[2]
        partitions = (vertices + 65535) // 65536
        self.assertEqual(result["worker_partitions"], [(partitions + 3 - worker) // 4 for worker in range(4)])
        self.assertEqual(len(result["commands"]), 2 + 3 * partitions)
        for index, command in enumerate(result["commands"]):
            expected = []
            if index >= 2:
                ordinal, role = divmod(index - 2, 3)
                self.assertEqual(command["ordinal"], ordinal)
                self.assertEqual(command["lane"], ordinal % 4)
                self.assertEqual(command["role"], ("adapter", "little", "frontend_mux")[role])
                if role < 2 and ordinal >= 4:
                    expected = [index - 12]
                elif role == 2 and ordinal:
                    expected = [index - 3]
            self.assertEqual(command["waits"], expected)
        offsets = fixtures.words(directory / "csr_offsets.u32le")
        destinations = fixtures.words(directory / "csr_destinations.u32le")
        initial = fixtures.words(directory / "initial.u32le")
        divisors = initial if binding == "author_initial" else fixtures.words(directory / "degrees.u32le")
        sums = [0] * vertices
        for source in range(vertices):
            for offset in range(offsets[source], offsets[source + 1]):
                sums[destinations[offset]] += initial[source]
        self.assertEqual(list(fixtures.words(output / "expected_gather.u32le")),
                         [fixtures.bits(float(value)) for value in sums])
        expected = [fixtures.bits(fixtures.f32(fixtures.f32(108 / 128 * total) / divisors[vertex]))
                    if divisors[vertex] else 0 for vertex, total in enumerate(sums)]
        self.assertEqual(list(fixtures.words(output / "expected_payload.u32le")), expected)
        self.assertEqual(sorted(fixtures.words(output / "external_to_internal.u32le")), list(range(vertices)))
        self.assertFalse((output / "gathered_external.u32le").exists())
        self.assertFalse((output / "payload_external.u32le").exists())
        descriptor = fixtures.words(directory / "execution.u32le")
        reference = {"vertices": vertices, "logical_edges": len(destinations),
            "capacity_vertices": int(descriptor[4]), "a4_published_vertices": int(descriptor[5]),
            "expected_gather_sha256": oracle.digest(fixtures.words(output / "expected_gather.u32le")),
            "expected_payload": {binding: oracle.digest(fixtures.words(output / "expected_payload.u32le"))}}
        checked = board_analysis.prepared(result, output, reference, binding)
        self.assertEqual(len(checked["targets"]), 10 * partitions + 7)
        self.invoke(variant, "control", ["prepare", directory, binding, output], ok=False)
        return output, result, reference, checked

    def test_preparation_rejects_metadata_canary_and_projection_corruption(self):
        output, report, reference, _ = self.check_preparation(self.fixture, "release", "csr_degree")
        for key, value in (("commands", [{**report["commands"][0], "lane": False}, *report["commands"][1:]]),
                           ("worker_partitions", [True, 0, 0, 0]), ("board_programmed", True)):
            with self.subTest(key=key), self.assertRaises(ValueError):
                board_analysis.prepared({**report, key: value}, output, reference, "csr_degree")
        for name, offset in (("source_a0", -4), ("rank", 0)):
            path = output / "expected_buffers" / (name + ".u32le")
            saved = path.read_bytes()
            changed = bytearray(saved)
            changed[offset] ^= 1
            path.write_bytes(changed)
            try:
                with self.subTest(name=name), self.assertRaises(ValueError):
                    board_analysis.prepared(report, output, reference, "csr_degree")
            finally:
                path.write_bytes(saved)

    def fabricated_readback_fixture(self):
        # Deliberately synthetic validator input: this never represents FPGA evidence.
        output, report, reference, expected = self.check_preparation(self.fixture, "release", "csr_degree")
        destination = output.with_name(output.name + "-fabricated-readback")
        shutil.copytree(output, destination)
        (destination / "expected_buffers").rename(destination / "readback")
        for source, target in (("expected_gather", "gathered_external"), ("expected_payload", "payload_external")):
            (destination / (source + ".u32le")).rename(destination / (target + ".u32le"))
        events = []
        for index, command in enumerate(report["commands"]):
            events.append({key: command[key] for key in ("role", "ordinal", "lane")})
            start, end = (10, 10000) if index < 2 else (20 + index * 10, 25 + index * 10)
            events[-1].update(queued_ns=1, submitted_ns=2, start_ns=start, end_ns=end)
        observed = {**report, "status": board_analysis.PASS, "bdf": "0000:01:00.1",
                    "board_programmed": True, "hardware_timing_measured": True, "complete_buffers_verified": True,
                    "events": events, "event_union_ns": 9990, "event_span_ns": 9990,
                    "enqueue_to_completion_ms": 0.02}
        (destination / "result.json").write_text(json.dumps(observed))
        return destination, observed, {"offline": report, "reference": reference,
            "binding": "csr_degree", "expected": expected}

    def test_independent_raw_readback_and_overlapping_timing_validator(self):
        output, report, case = self.fabricated_readback_fixture()
        checked = board_analysis.readback(report, output, case, report["bdf"])
        self.assertEqual(checked["event_union_ns"], 9990)
        self.assertLess(9990, sum(event["end_ns"] - event["start_ns"] for event in report["events"]))
        for key, value in (("bdf", "0000:02:00.1"), ("complete_buffers_verified", False),
                           ("publication_match", True), ("event_union_ns", 9991),
                           ("enqueue_to_completion_ms", 0.001), ("events", report["events"][:-1])):
            with self.subTest(key=key), self.assertRaises(ValueError):
                board_analysis.readback({**report, key: value}, output, case, report["bdf"])
        changed = copy.deepcopy(report)
        changed["events"][2]["lane"] = True
        with self.assertRaises(ValueError):
            board_analysis.readback(changed, output, case, report["bdf"])
        for filename in ("rank.u32le", "shard0_row.u32le", "source_a0.u32le"):
            path = output / "readback" / filename
            saved = path.read_bytes()
            path.write_bytes(saved[:-1] + bytes([saved[-1] ^ 1]))
            try:
                with self.subTest(filename=filename), self.assertRaises(ValueError):
                    board_analysis.readback(report, output, case, report["bdf"])
            finally:
                path.write_bytes(saved)

    def test_independent_schedule_including_worker_and_mux_reuse(self):
        commands = board_analysis.schedule(12)
        self.assertEqual(len(commands), 38)
        self.assertEqual(commands[14]["waits"], [2])
        self.assertEqual(commands[15]["waits"], [3])
        self.assertEqual(commands[16]["waits"], [13])
        self.assertEqual(commands[2]["waits"], [])
        self.assertEqual(commands[4]["waits"], [])

    def test_synthetic_both_builds_and_bindings(self):
        for variant in ("release", "ubsan"):
            for binding in ("author_initial", "csr_degree"):
                self.check_preparation(self.fixture, variant, binding)

    def test_admitted_skewed_source_input(self):
        for variant in ("release", "ubsan"):
            for binding in ("author_initial", "csr_degree"):
                self.check_preparation(fixtures.ADMITTED / "skewed_sources", variant, binding)

    def test_duplicate_input_rejects_before_output_or_device_access(self):
        for variant in ("release", "ubsan"):
            output = self.directory / f"duplicates-{variant}"
            result = self.invoke(variant, "control", ["prepare", fixtures.ADMITTED / "boundary_ring",
                                  "csr_degree", output], ok=False)
            self.assertIn("duplicate edge rejected", result.stderr)
            self.assertFalse(output.exists())

    def test_no_lease_rejects_before_context_programming_or_output(self):
        for variant in ("release", "ubsan"):
            output = self.directory / f"no-lease-{variant}"
            result = self.invoke(variant, "control", ["board", self.fixture, "csr_degree", output,
                                  "/nonexistent.xclbin", 0], ok=False)
            self.assertIn("external exclusive board lease required", result.stderr)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
