"""Independent offline control contracts; no vendor, compiler or board required."""

import array
import copy
import itertools
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest

from spine_cycle_sim.experiments.original_regraph_execution.hardware.k4_control import analysis, board_analysis, build, inputs
from spine_cycle_sim.experiments.original_regraph_execution.hardware.semantics import arithmetic


def write(path, values):
    words = array.array("I", values)
    if sys.byteorder != "little":
        words.byteswap()
    path.write_bytes(words.tobytes())


def fixture(directory, duplicate=False):
    directory.mkdir()
    initial = array.array("I", [128, 64, 0]) + array.array("I", [0]) * (65536 - 3)
    degrees = array.array("I", [2 if duplicate else 1, 1, 0]) + array.array("I", [0]) * (65536 - 3)
    destinations = [2, 2, 2] if duplicate else [2, 2]
    offsets = [0, 2, 3, 3] if duplicate else [0, 1, 2, 2]
    for name, values in (("execution", [0x3447524F, 1, 3, len(destinations), 65536, 65536, 4, 1]),
                         ("initial", initial), ("degrees", degrees),
                         ("csr_offsets", offsets), ("csr_destinations", destinations)):
        write(directory / (name + ".u32le"), values)
    sums = arithmetic.csr_sums(array.array("I", offsets), array.array("I", destinations), initial, 3)
    return {"directory": str(directory), "arithmetic": {
        "author_initial": arithmetic.compare(sums, initial, 3),
        "csr_degree": arithmetic.compare(sums, degrees, 3)}}


class OriginalRegraphK4ControlTests(unittest.TestCase):
    def test_prepare_keeps_duplicates_and_independent_arithmetic(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            for duplicate, count in ((False, 0), (True, 1)):
                expected = analysis.prepare(fixture(directory / str(duplicate), duplicate))
                self.assertEqual(expected["duplicates"], count)
                self.assertEqual(expected["first_duplicate"], [0, 2] if duplicate else None)
                self.assertEqual(expected["logical_edges"], 3 if duplicate else 2)
                self.assertEqual(expected["capacity_vertices"], 65536)

    def test_prepare_rejects_audit_or_csr_drift(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp) / "input"
            item = fixture(directory)
            changed = copy.deepcopy(item)
            changed["arithmetic"]["csr_degree"]["float_logical_bits_sha256"] = "0" * 64
            with self.assertRaisesRegex(ValueError, "arithmetic differs"):
                analysis.prepare(changed)
            write(directory / "csr_offsets.u32le", [0, 4, 2, 2])
            with self.assertRaises(ValueError):
                analysis.prepare(item)

    def test_prepare_rejects_symlink_and_partial_descriptor(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp) / "input"
            item = fixture(directory)
            descriptor = directory / "execution.u32le"
            raw = descriptor.read_bytes()
            descriptor.write_bytes(raw + b"x")
            with self.assertRaisesRegex(ValueError, "descriptor words"):
                analysis.prepare(item)
            descriptor.write_bytes(raw)
            target = directory / "saved"
            descriptor.rename(target)
            descriptor.symlink_to(target)
            with self.assertRaises(ValueError):
                analysis.prepare(item)

    def test_inspect_requires_exact_profile_binary_outputs_and_bijection(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            expected = analysis.prepare(fixture(directory / "input"))
            report = {"schema_version": 1, "status": analysis.PASS, "binding": "csr_degree",
                **{key: expected[key] for key in ("vertices", "logical_edges", "capacity_vertices", "a4_published_vertices")},
                "partitions": 1, "partition_vertices": 65536, "graph_channels": 23,
                "cache_segments": 131072, "row_line_read": True, "iterations": 1,
                "damping_numerator": 108, "damping_denominator": 128, "base": 0,
                "dangling_share": 0, "rank_initial": 0, "updates": 0, "g_skipped": True,
                "source_prepare_skipped": True, "external_binary_encoding": "logical-V-u32le-binary32-bits",
                "permutation_encoding": "logical-V-u32le-external-to-internal",
                "assertions": dict.fromkeys(analysis.ASSERTIONS, True),
                **dict.fromkeys(("board_programmed", "hardware_timing_measured", "publication_match",
                                 "default_profile_equivalence"), False)}
            output = directory / "output"
            output.mkdir()
            bits = lambda number: struct.unpack("<I", struct.pack("<f", number))[0]
            write(output / "gathered_external.u32le", [0, 0, bits(192)])
            write(output / "payload_external.u32le", [0, 0, 0])
            write(output / "external_to_internal.u32le", [1, 0, 2])
            checked = analysis.inspect(report, output, expected, "csr_degree")
            self.assertEqual(len(checked), 3)
            for key, value in (("iterations", True), ("board_programmed", True),
                               ("graph_channels", 9), ("cycles", 100)):
                changed = {**report, key: value}
                with self.subTest(key=key), self.assertRaises(ValueError):
                    analysis.inspect(changed, output, expected, "csr_degree")
            write(output / "external_to_internal.u32le", [1, 1, 2])
            with self.assertRaisesRegex(ValueError, "bijection"):
                analysis.inspect(report, output, expected, "csr_degree")
            write(output / "external_to_internal.u32le", [1, 0, 2])
            write(output / "payload_external.u32le", [0, bits(1), 0])
            with self.assertRaisesRegex(ValueError, "independent CSR"):
                analysis.inspect(report, output, expected, "csr_degree")

    def test_matrix_retains_unsupported_rows_and_rejects_missing_or_changed(self):
        rows = [{"build": variant, "graph": graph, "binding": binding, "repetition": repeat,
                 "status": analysis.UNSUPPORTED if graph == "boundary_ring" else analysis.PASS,
                 "analysis": {"payload_sha256": graph + binding}}
                for variant, graph, binding, repeat in itertools.product(
                    analysis.BUILDS, inputs.GRAPHS, analysis.BINDINGS, range(2))]
        analysis.matrix(rows)
        with self.assertRaisesRegex(ValueError, "24-row"):
            analysis.matrix(rows[:-1])
        changed = copy.deepcopy(rows)
        changed[-1]["analysis"] = {}
        with self.assertRaisesRegex(ValueError, "outputs differ"):
            analysis.matrix(changed)
        changed = copy.deepcopy(rows)
        changed[0]["status"] = analysis.PASS
        with self.assertRaisesRegex(ValueError, "eligibility differs"):
            analysis.matrix(changed)

    def test_explicit_build_floating_point_and_ubsan_flags(self):
        paths = [Path(name) for name in ("g++", "source", "production", "binary", "dependency")]
        for variant in analysis.BUILDS:
            command = build.command(*paths, variant, "offline")
            self.assertIn("-ffp-contract=off", command)
            self.assertIn("-fno-fast-math", command)
            self.assertEqual(command[command.index("-MT") + 1], "probe")
            self.assertEqual("-fsanitize=undefined" in command, variant == "ubsan")
        with self.assertRaises(ValueError):
            build.command(*paths, "fast", "offline")

    def test_prepared_matrix_compares_values_and_complete_targets_not_pin_paths(self):
        rows = [{"build": variant, "graph": graph, "binding": binding, "repetition": repeat,
                 "status": analysis.UNSUPPORTED if graph == "boundary_ring" else board_analysis.PREPARED,
                 "analysis": {"values": graph + binding, "targets": {"rank": graph + binding},
                              "pins": [{"path": f"{variant}/{graph}/{binding}/{repeat}"}]}}
                for variant, graph, binding, repeat in itertools.product(
                    analysis.BUILDS, inputs.GRAPHS, analysis.BINDINGS, range(2))]
        board_analysis.matrix(rows)
        with self.assertRaisesRegex(ValueError, "24-row"):
            board_analysis.matrix(rows[:-1])
        changed = copy.deepcopy(rows)
        changed[-1]["analysis"]["targets"]["rank"] = "corrupted"
        with self.assertRaisesRegex(ValueError, "outputs differ"):
            board_analysis.matrix(changed)
        changed[-1]["status"] = board_analysis.PASS
        with self.assertRaisesRegex(ValueError, "only prepared"):
            board_analysis.matrix(changed)

    def test_reject_prior_board_claim_before_source_admission(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            (directory / "results.json").write_text(json.dumps({"status": "PASS"}))
            with self.assertRaisesRegex(ValueError, "complete offline"):
                inputs.admit(directory, directory, directory, directory)
