"""Bounded CPU model tests; compiler and test children inherit the caller's cgroup."""

from array import array
import json
import math
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

from spine_cycle_sim.experiments.original_regraph_execution.hardware.k4_control import build
from spine_cycle_sim.experiments.upstream_controls.execution import dependency_identities

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "cpp/tests/original_regraph/integrated"
PRODUCTION_INCLUDE = Path("/home/chuxiao/grasu-regraph-complete-g/include")
ADMITTED = Path(
    "/data/chuxiao/experiments/baseline_hardware_validation_20261015/"
    "original-r-control-validation-v4/inputs/a4"
)


def words(path):
    values = array("I")
    with path.open("rb") as stream:
        values.frombytes(stream.read())
    if sys.byteorder != "little":
        values.byteswap()
    return values


def write_words(path, values):
    payload = array("I", values)
    if sys.byteorder != "little":
        payload.byteswap()
    path.write_bytes(payload.tobytes())


def f32(value):
    return struct.unpack("<f", struct.pack("<f", value))[0]


def bits(value):
    return struct.unpack("<I", struct.pack("<f", value))[0]


def require_finite_cgroup():
    entry = next(line for line in Path("/proc/self/cgroup").read_text().splitlines() if line.startswith("0::"))
    cgroup = Path("/sys/fs/cgroup") / entry[3:].lstrip("/")
    memory = (cgroup / "memory.max").read_text().strip()
    cpu = (cgroup / "cpu.max").read_text().split()[0]
    swap = (cgroup / "memory.swap.max").read_text().strip()
    if memory == "max" or int(memory) > 2 * 1024**3 or cpu == "max" or swap != "0":
        raise RuntimeError("Focused tests require finite <=2GiB memory, finite CPU quota and zero swap cgroup limits")
    if len(os.sched_getaffinity(0)) != 1:
        raise RuntimeError("Focused tests require single-CPU affinity")


def fixture(directory, *, duplicate=False):
    directory.mkdir()
    vertices, capacity = 6, 65536
    edges = [(1, 0), (1, 2), (2, 1), (3, 2), (4, 3)]
    if duplicate:
        edges.insert(1, (1, 0))
    offsets = [0]
    for source in range(vertices):
        offsets.append(offsets[-1] + sum(src == source for src, _ in edges))
    initial = [0, 128, 64, 0, 256, 0] + [0] * (capacity - vertices)
    degrees = [offsets[i + 1] - offsets[i] for i in range(vertices)] + [0] * (capacity - vertices)
    descriptor = [0x3447524F, 1, vertices, len(edges), capacity, capacity, 4, 1]
    tasks = []
    for lane in range(4):
        start = len(tasks)
        pairs = edges if lane == 0 else []
        for source, destination in pairs:
            tasks.extend([source, destination])
        while len(tasks) - start < 16:
            tasks.extend([5, 0xFFFFFFFF])
        descriptor.extend([0, lane, lane, 0, capacity, start, len(tasks) - start, 0])
    for name, values in {
        "execution": descriptor,
        "tasks": tasks,
        "initial": initial,
        "degrees": degrees,
        "csr_offsets": offsets,
        "csr_destinations": [dst for _, dst in edges],
    }.items():
        write_words(directory / f"{name}.u32le", values)


class OriginalRegraphK4ModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        require_finite_cgroup()
        if not PRODUCTION_INCLUDE.is_dir():
            raise RuntimeError("Exact clean production include directory is required")
        cls.temporary = tempfile.TemporaryDirectory(prefix="original-r-k4-focused-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.directory = Path(cls.temporary.name)
        cls.fixture = cls.directory / "fixture"
        fixture(cls.fixture)
        cls.executables = {}
        for variant in ("release", "ubsan"):
            for source in ("offline", "model_tests"):
                executable = cls.directory / f"{source}-{variant}"
                dependency = executable.with_suffix(".d")
                command = build.command(Path("/usr/bin/g++"), SOURCES,
                    PRODUCTION_INCLUDE.parent, executable, dependency, variant, source)
                compiled = subprocess.run(command, capture_output=True, text=True, timeout=75)
                if compiled.returncode:
                    raise RuntimeError(f"{source}-{variant} compile failed:\n{compiled.stdout}{compiled.stderr}")
                dependencies = dependency_identities(dependency, ROOT)
                if not any(pin["path"] == str((SOURCES / "model.hpp").resolve()) for pin in dependencies):
                    raise RuntimeError("Production build must preserve complete model dependency closure")
                cls.executables[variant, source] = executable

    def invoke(self, variant, source, *arguments, ok=True):
        result = subprocess.run(
            [str(self.executables[variant, source]), *map(str, arguments)],
            capture_output=True, text=True, timeout=45,
            env={**os.environ, "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1"},
        )
        self.assertEqual(result.returncode, 0 if ok else 1, result.stdout + result.stderr)
        self.assertNotIn("runtime error:", result.stderr)
        return result

    def check_control(self, variant, directory, binding):
        output = self.directory / f"{directory.name}-{binding}-{variant}-{self._testMethodName}"
        self.invoke(variant, "offline", "control", directory, binding, output)
        result = json.loads((output / "result.json").read_text())
        self.assertEqual(result["schema_version"], 1)
        self.assertEqual(result["status"], "OFFLINE_MATCHED_K4_A4_MODEL_PASS_NOT_FPGA")
        self.assertEqual(result["binding"], binding)
        self.assertTrue(all(result["assertions"].values()))
        self.assertFalse(result["board_programmed"])
        self.assertFalse(result["hardware_timing_measured"])
        self.assertFalse(result["default_profile_equivalence"])
        self.assertFalse(result["publication_match"])
        descriptor = words(directory / "execution.u32le")
        vertices = descriptor[2]
        self.assertEqual(result["vertices"], vertices)
        self.assertEqual(result["capacity_vertices"], descriptor[4])
        self.assertEqual(result["a4_published_vertices"], descriptor[5])
        self.assertEqual(result["partitions"], math.ceil(vertices / 65536))
        initial = words(directory / "initial.u32le")
        degree = words(directory / "degrees.u32le")
        offsets = words(directory / "csr_offsets.u32le")
        destinations = words(directory / "csr_destinations.u32le")
        sums = [0] * vertices
        for source in range(vertices):
            for offset in range(offsets[source], offsets[source + 1]):
                sums[destinations[offset]] += initial[source]
        divisor = initial if binding == "author_initial" else degree
        expected_gather = [bits(f32(value)) for value in sums]
        expected_payload = [
            bits(f32(f32(f32(108 / 128) * f32(total)) / f32(divisor[vertex])))
            if divisor[vertex] else 0 for vertex, total in enumerate(sums)
        ]
        self.assertEqual(list(words(output / "gathered_external.u32le")), expected_gather)
        self.assertEqual(list(words(output / "payload_external.u32le")), expected_payload)
        permutation = words(output / "external_to_internal.u32le")
        self.assertEqual(sorted(permutation), list(range(vertices)))
        expected_order = sorted(range(vertices), key=lambda vertex: (degree[vertex] == 0, vertex))
        for internal, external in enumerate(expected_order):
            self.assertEqual(permutation[external], internal)
        return output

    def test_invariants_release_and_ubsan(self):
        for variant in ("release", "ubsan"):
            with self.subTest(variant=variant):
                self.invoke(variant, "model_tests", self.fixture)

    def test_synthetic_both_bindings_release_and_ubsan(self):
        for variant in ("release", "ubsan"):
            for binding in ("author_initial", "csr_degree"):
                with self.subTest(variant=variant, binding=binding):
                    output = self.check_control(variant, self.fixture, binding)
                    self.invoke(variant, "offline", "control", self.fixture, binding, output, ok=False)

    def test_exact_admitted_bounded_inputs(self):
        for graph in ("skewed_sources",):
            directory = ADMITTED / graph
            self.assertTrue((directory / "execution.u32le").is_file(), str(directory))
            for variant in ("release", "ubsan"):
                for binding in ("author_initial", "csr_degree"):
                    with self.subTest(graph=graph, variant=variant, binding=binding):
                        self.check_control(variant, directory, binding)

    def test_exact_admitted_boundary_ring_rejects_64_duplicate_records(self):
        directory = ADMITTED / "boundary_ring"
        offsets = words(directory / "csr_offsets.u32le")
        destinations = words(directory / "csr_destinations.u32le")
        duplicates = 0
        first_duplicate = None
        for source in range(len(offsets) - 1):
            seen = set()
            for offset in range(offsets[source], offsets[source + 1]):
                destination = destinations[offset]
                if destination in seen:
                    duplicates += 1
                    if first_duplicate is None:
                        first_duplicate = (source, destination)
                seen.add(destination)
        self.assertEqual(duplicates, 64)
        self.assertEqual(first_duplicate, (352, 43409))
        for variant in ("release", "ubsan"):
            for binding in ("author_initial", "csr_degree"):
                with self.subTest(variant=variant, binding=binding):
                    output = self.directory / f"boundary-rejected-{binding}-{variant}"
                    result = self.invoke(variant, "offline", "control", directory, binding, output, ok=False)
                    self.assertIn("duplicate edge rejected", result.stderr)
                    self.assertFalse(output.exists())

    def test_reject_duplicate_bad_csr_and_symlink(self):
        duplicate = self.directory / "duplicate"
        fixture(duplicate, duplicate=True)
        malformed = self.directory / "malformed"
        shutil.copytree(self.fixture, malformed)
        offsets = words(malformed / "csr_offsets.u32le")
        offsets[1] = 100
        write_words(malformed / "csr_offsets.u32le", offsets)
        symlink = self.directory / "symlink"
        shutil.copytree(self.fixture, symlink)
        (symlink / "degrees.u32le").unlink()
        (symlink / "degrees.u32le").symlink_to(self.fixture / "degrees.u32le")
        inexact = self.directory / "inexact-source"
        shutil.copytree(self.fixture, inexact)
        initial = words(inexact / "initial.u32le")
        initial[0] = (1 << 24) + 1  # No outgoing edges: original signed gather stays safe.
        write_words(inexact / "initial.u32le", initial)
        for variant in ("release", "ubsan"):
            for directory in (duplicate, malformed, symlink, inexact):
                output = self.directory / f"reject-{directory.name}-{variant}"
                result = self.invoke(variant, "offline", "control", directory, "csr_degree", output, ok=False)
                self.assertTrue(result.stderr.strip())
                self.assertFalse(output.exists())
            self.invoke(variant, "offline", "control", self.fixture, "default", self.directory / "bad-binding", ok=False)


if __name__ == "__main__":
    unittest.main()
