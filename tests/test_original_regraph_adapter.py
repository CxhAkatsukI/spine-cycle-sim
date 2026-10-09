"""Source16 PMA and observed adapter stream gates, separate from cycle calibration."""

import json
from pathlib import Path
import struct
import tempfile
import unittest

from spine_cycle_sim.experiments.original_regraph_execution.adapter.analysis import analyze, inspect
from spine_cycle_sim.experiments.original_regraph_execution.adapter.preparation import EMPTY, load, prepare, save_words, task_layout
from spine_cycle_sim.experiments.original_regraph_execution.adapter.validation import capture_negatives

ROOT = Path(__file__).resolve().parents[1]


def fixture(directory):
    words = []; tasks = []
    for index in range(4):
        tasks += [0, index, index, 0, 65536, len(words), 16, 0]
        words += [index, (index + 1) % 8] + [value for _ in range(7) for value in (index, 0xffffffff)]
    for name, values in (("execution.u32le", [0x3447524f, 1, 8, 4, 65536, 65536, 4, 1] + tasks), ("tasks.u32le", words)):
        with (directory / name).open("xb") as stream: save_words(stream, values)
    prepare(directory)


def capture(directory):
    descriptor = load(directory / "adapter.u32le"); rows = load(directory / "rows.u32le"); pma = load(directory / "pma.u32le")
    with (directory / "adapter_edges.u32le").open("xb") as stream:
        for base in range(8, len(descriptor), 8):
            _, _, _, destination, row_offset, pma_offset, _, _ = descriptor[base:base + 8]
            for source in range(descriptor[2]):
                end, begin = rows[row_offset + source * 2:row_offset + source * 2 + 2]
                for word in pma[pma_offset + begin:pma_offset + end]:
                    dummy = EMPTY if word == EMPTY else 0
                    stream.write(struct.pack("<2I", source | dummy, destination + (word & 0x7ffff) | dummy))
    facts, _ = inspect(directory); out, err = directory / "stdout", directory / "stderr"
    out.write_text("ADAPTER_SOURCE " + json.dumps(facts, separators=(",", ":")) + "\n"); err.write_text("")
    return out, err


class AdapterSourceTests(unittest.TestCase):
    def test_source16_golden_bounds_and_padding(self):
        bounds, slots, logical, empty = task_layout(3, [0, 1, 0, 2, 2, 0, 2, 0xffffffff], 0)
        self.assertEqual(list(bounds), [16, 0, 16, 16, 32, 16])
        self.assertEqual(list(slots), [1, 2] + [EMPTY] * 14 + [0] + [EMPTY] * 15)
        self.assertEqual((logical, empty), (3, 0))

    def test_empty_task_reserves_one_segment_at_original_dummy_source(self):
        bounds, slots, logical, empty = task_layout(4, [2, 0xffffffff] * 8, 0)
        self.assertEqual(list(bounds), [0, 0, 0, 0, 16, 0, 16, 16])
        self.assertEqual(list(slots), [EMPTY] * 16); self.assertEqual((logical, empty), (0, 1))

    def test_multiple_segments_and_nonzero_partition(self):
        _, slots, logical, _ = task_layout(1, [value for target in range(17) for value in (0, 65536 + target)], 65536)
        self.assertEqual(len(slots), 32); self.assertEqual(logical, 17)
        self.assertEqual(list(slots)[17:], [EMPTY] * 15)

    def test_duplicate_entries_are_preserved_not_deduplicated(self):
        _, slots, logical, _ = task_layout(3, [0, 1, 0, 1], 0)
        self.assertEqual(list(slots)[:2], [1, 1]); self.assertEqual(logical, 2)

    def test_invalid_source_destination_and_extent_rejected(self):
        for compact in ([3, 1], [0, 65536], [], [0]):
            with self.subTest(compact=compact), self.assertRaises(ValueError): task_layout(3, compact, 0)

    def test_full_packets_and_all_actual_capture_rejections(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary); fixture(directory); out, err = capture(directory)
            result = analyze(directory, directory, out, err)
            self.assertEqual(result["result"]["logical_edges"], 4); self.assertEqual(result["result"]["physical_edges"], 64)
            self.assertEqual(result["result"]["row_word_reads"], 36)
            self.assertIsNone(result["device_cycles"]); self.assertIsNone(result["matched_A4_B_overhead"])
            self.assertEqual(len(capture_negatives(directory, directory, out, err)), 6)

    def test_descriptor_bounds_multiset_and_truncation_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary); fixture(directory)
            for name, byte in (("adapter.u32le", 0), ("rows.u32le", 0), ("pma.u32le", 0)):
                path = directory / name; original = path.read_bytes(); damaged = bytearray(original); damaged[byte] ^= 1
                path.write_bytes(damaged)
                with self.subTest(name=name), self.assertRaises(ValueError): inspect(directory)
                path.write_bytes(original)
            path = directory / "pma.u32le"; path.write_bytes(path.read_bytes()[:-4])
            with self.assertRaises(ValueError): inspect(directory)

    def test_typed_counters_duplicates_and_no_extra_diagnostics(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary); fixture(directory); out, err = capture(directory); original = out.read_text()
            for text in (original.replace('"passed":true', '"passed":1'), original.replace('"tasks":4', '"tasks":4,"tasks":4'), original + "warning\n"):
                out.write_text(text)
                with self.assertRaises(ValueError): analyze(directory, directory, out, err)

    def test_contract_excludes_matched_overhead_and_routed_assignment(self):
        contract = json.loads((ROOT / "configs/experiments/original_regraph_adapter_source_v1.json").read_text())
        self.assertEqual(contract["inputs"], ["boundary_ring", "skewed_sources", "amazon"])
        self.assertEqual(contract["segment_slots"], 16); self.assertTrue(contract["instrument_all_cases"])
        self.assertIn("adapter_R_overlap_or_cycles", contract["not_claimed"])
        self.assertIn("actual_routed_K4_task_assignment_or_placement", contract["not_claimed"])


if __name__ == "__main__": unittest.main()
