"""Independent host-layout/protocol gates, not timing or publication tests."""

import array
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.upstream_controls.grasu.analysis import WIDTH_WARNING
from spine_cycle_sim.experiments.upstream_controls.grasu.host.analysis import analyze
from spine_cycle_sim.experiments.upstream_controls.grasu.host.fixtures import NAMES, fixture, read, write
from spine_cycle_sim.experiments.upstream_controls.grasu.host.layout import EMPTY, locate, verify, words
from spine_cycle_sim.experiments.upstream_controls.grasu.host.preparation import prepare, validate
from spine_cycle_sim.experiments.upstream_controls.grasu.host.protocol import verify as protocol
from spine_cycle_sim.experiments.upstream_controls.grasu.host.validation import INVALID, capture_negatives

ROOT = Path(__file__).resolve().parents[1]


def capture(directory):
    """Small identity-mapped case whose equal priorities allow identity order."""
    path = directory / "input.txt"; write("mixed_reservation", path)
    vertices, initial, updates, final = read(path)
    union = sorted(set(initial) | {(s, d) for s, d, op in updates if op})
    offsets = [0]; binary = []; prepared = []
    for vertex in range(vertices):
        row = [(s << 32) | d for s, d in union if s == vertex]
        for begin in range(0, len(row), 16):
            chunk = row[begin:begin + 16]; binary.append(chunk[0])
            live = [edge for edge in chunk if (edge >> 32, edge & 0xffffffff) in initial]
            prepared += live + [EMPTY] * (16 - len(live))
        offsets.append(len(prepared))
    mapped = [(s << 32) | d | (EMPTY if not op else 0) for s, d, op in updates]
    updated = prepared.copy()
    for edge in mapped:
        begin = locate(binary, offsets, edge) * 16
        values = [value for value in updated[begin:begin + 16] if value != EMPTY]
        if edge & EMPTY: values.remove(edge & (EMPTY - 1))
        else: values.append(edge)
        values.sort(); updated[begin:begin + 16] = values + [EMPTY] * (16 - len(values))
    for name, width, values in (("mapping.u32le", 4, range(vertices)), ("row_offsets.u64le", 8, offsets),
            ("binary.u64le", 8, binary), ("prepared.u64le", 8, prepared), ("updated.u64le", 8, updated),
            ("mapped_initial.u64le", 8, [(s << 32) | d for s, d in initial]), ("mapped_updates.u64le", 8, mapped)):
        values = list(values); (directory / name).write_bytes(struct.pack(f"<{len(values)}{'I' if width == 4 else 'Q'}", *values))
    packets = []
    for edge in mapped:
        segment = locate(binary, offsets, edge)
        packets.extend((edge & 0xffffffff, edge >> 32, segment * 16, edge & 0xffffffff, edge >> 32, (segment & 1) * 2))
    requests = []
    for kernel in range(4):
        for lane in range(64):
            for i in range(kernel + lane * 4, len(mapped), 256):
                source = (mapped[i] & (EMPTY - 1)) >> 32
                value = (offsets[source] << 32) | offsets[source + 1]
                requests.extend((kernel, lane, 0, source, value & 0xffffffff, value >> 32))
    payload = [0x47485031, 1, len(updates), len(requests) // 6] + packets + requests
    (directory / "protocol.u32le").write_bytes(struct.pack(f"<{len(payload)}I", *payload))
    facts, _, _, _, insertions = verify(path, directory); facts["memory_requests"] = len(requests) // 6
    out, err = directory / "stdout.txt", directory / "stderr.txt"
    out.write_text(f"node_num: {vertices}\nstatic_edge_num: {len(initial)}\nupdate_edge_num: {len(updates)}\n"
        f"update_edge_size is {len(updates)}\nread graph file finish\ndispatch finish\nGRASU_HOST " + json.dumps(facts, separators=(",", ":")) + "\n")
    err.write_text(WIDTH_WARNING * insertions)
    return path, out, err


class OriginalGraSUHostTests(unittest.TestCase):
    def test_fixture_counts_and_sequential_updates(self):
        expected = [(8, 0, 0, 0), (64, 32, 0, 32), (64, 0, 32, 32), (64, 32, 32, 0),
            (96, 64, 80, 112), (128, 44, 44, 72), (32, 3, 62, 3)]
        with tempfile.TemporaryDirectory() as temporary:
            for name, counts in zip(NAMES[:-1], expected, strict=True):
                path = Path(temporary) / name; write(name, path); n, initial, updates, final = read(path)
                self.assertEqual((n, len(initial), len(updates), len(final)), counts)

    def test_cache_threshold_fixture_is_not_reduced(self):
        n, initial, updates = fixture("threshold_ring")
        self.assertEqual((n, len(initial), len(updates)), (262208, 262208, 262208))
        self.assertEqual(initial[:2], [(0, 1), (1, 2)])
        self.assertEqual(updates[0], (0, 0, 1)); self.assertEqual(updates[-1], (n - 1, n - 1, 1))
        self.assertEqual(n - 2 * 131072, 64)

    def test_invalid_and_trailing_input_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "input"
            for name, text, _ in INVALID:
                with self.subTest(name=name), self.assertRaises(ValueError): path.write_text(text); read(path)
            for text in ("0 0 0\n", "2 -1 0\n", "2 0 0 0\n", "2 0 1\n-1 0 1\n"):
                with self.assertRaises(ValueError): path.write_text(text); read(path)

    def test_unknown_fixture_rejected(self):
        with self.assertRaises(ValueError): fixture("unknown")

    def test_layout_protocol_complete_state_and_twelve_rejections(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary); path, out, err = capture(directory)
            result = analyze(path, directory, out, err)
            self.assertEqual((result["segments"], result["memory_requests"], result["final_edges"]), (8, 80, 112))
            self.assertEqual(result["max_occupancy"], 16)
            self.assertIsNone(result["device_cycles"])
            self.assertEqual(len(capture_negatives(path, directory, out, err)), 12)

    def test_counter_duplicate_boolean_and_unknown_diagnostic_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary); path, out, err = capture(directory); original = out.read_text()
            for invalid in (original.replace('"updates":80', '"updates":true'), original.replace('"updates":80', '"updates":80,"updates":80'),
                    original + "WARNING empty stream\n", original + original):
                out.write_text(invalid)
                with self.assertRaises(ValueError): analyze(path, directory, out, err)
            out.write_text(original); err.write_text(err.read_text() + "runtime error: UB\n")
            with self.assertRaisesRegex(ValueError, "diagnostics"): analyze(path, directory, out, err)

    def test_protocol_extent_order_and_binary_search(self):
        binary = [0, 16, 32]; offsets = [0, 48]; updates = [20]
        rows = [0x47485031, 1, 1, 3, 20, 0, 16, 20, 0, 2,
            0, 0, 0, 0, 48, 0, 0, 0, 1, 1, 16, 0, 0, 0, 1, 2, 32, 0]
        payload = struct.pack(f"<{len(rows)}I", *rows)
        self.assertEqual(protocol(payload, binary, offsets, updates), 3)
        for damaged in (payload[:-4], payload + b"\0" * 4, payload[:40] + payload[64:88] + payload[40:64] + payload[88:]):
            with self.assertRaises(ValueError): protocol(damaged, binary, offsets, updates)

    def test_capture_exact_extent(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "data"; path.write_bytes(b"\0" * 8)
            self.assertEqual(words(path, 8, 1), array.array("Q", [0]))
            with self.assertRaisesRegex(ValueError, "extent"): words(path, 8, 2)

    def test_contract_disallows_bool_integer_and_geometry_changes(self):
        contract = json.loads((ROOT / "configs/experiments/original_grasu_host_v1.json").read_text()); validate(contract)
        for key, value in (("segment_slots", 8), ("repetitions", True), ("instrument_all_cases", 1), ("variants", ["both_guards"]), ("reserve_gib", 0)):
            with self.assertRaises(ValueError): validate({**contract, key: value})

    def test_real_patch_application_and_source_isolation(self):
        original = """        int cur_count = 0;
        int cur_loc = 0;
        for (size_t i = 0; i < node_size; i++) {
            while ((all_edges[cur_loc] >> 32) == i) {
                cur_count++;
                cur_loc++;
            }
        std::sort(init_edges_vector.begin(), init_edges_vector.end());
        cur_loc = 0;
        for (size_t i = 0; i < data.size(); i++) {
            if (data[i] == init_edges_vector[cur_loc]) {
                cur_loc++;
            } else {
                data[i] = EMPTY;
"""
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source"; host = source / "GraSU/GraSU/src"; host.mkdir(parents=True)
            for name in ("host.cpp", "config.h", "kernel_config.h"): (host / name).write_text("unchanged\n")
            header = host / "pma_dynamic_graph.hpp"; header.write_text(original)
            with patch("spine_cycle_sim.experiments.upstream_controls.grasu.host.preparation.author_snapshot", return_value={"test_source": True}):
                records = prepare(ROOT, source, Path(temporary) / "prepared", {"original_header_sha256": sha256_file(header)})
            self.assertEqual([len(row["patches"]) for row in records], [0, 1, 2])
            self.assertEqual(header.read_text(), original)
            modified = (Path(records[-1]["directory"]) / header.name).read_text()
            self.assertIn("cur_loc < all_edges.size()", modified); self.assertIn("cur_loc < init_edges_vector.size()", modified)


if __name__ == "__main__": unittest.main()
