import array
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

from spine_cycle_sim.experiments.original_regraph_execution.hardware import control_analysis, oracle
from spine_cycle_sim.experiments.original_regraph_execution.hardware.board_execution import analysis, preparation


def write_words(path, words):
    payload = array.array("I", words)
    if sys.byteorder != "little":
        payload.byteswap()
    path.write_bytes(payload.tobytes())


class BoardAnalysisTests(unittest.TestCase):
    def fixture(self, root):
        output, inputs = root / "output", root / "input"
        output.mkdir()
        inputs.mkdir()
        words = [108, 0, 0, 0, 0, 0] + [control_analysis.GUARD] * 16
        write_words(output / "expected.u32le", words)
        for lane in range(14):
            write_words(output / f"replica{lane}.u32le", words)
        write_words(inputs / "mixed.u32le",
                    [0x4D47524F, 1, 3, 2, 4, 6, 6, 2, 0, 1, 11, 3] +
                    [0, 0, 0, 0, 6, 0, 8, 1] + [0, 1, 11, 0, 6, 8, 8, 1])
        offline = {"status": "ORIGINAL_R_CONTROL_OFFLINE_PASS_NOT_FPGA", "board_programmed": False,
                   "hardware_timing_measured": False, "publication_match": False, "events": [], "bdf": "",
                   "enqueue_to_completion_ms": None, "event_union_ns": None, "event_span_ns": None,
                   "binding": "csr_degree", "iterations": 1, "argument": 0, "guard_words": 16,
                   "vertices": 3, "aligned_vertices": 4, "published_vertices": 6, "allocation_vertices": 6,
                   "extra_padding_vertices": 2, "logical_edges": 2, "physical_edges": 8, "dummy_edges": 6,
                   "tasks": 2, "little": 11, "big": 3, "topology": "original_example"}
        reference = {"vertices": 3, "original_allocation_words": 4, "device_publication_words": 6,
                     "logical_edges": 2, "physical_edges": 8, "one_superstep_comparison":
                         {"csr_degree_result_sha256": oracle.digest(array.array("I", [108, 0, 0, 0]))}}
        case = {"graph": "amazon", "binding": "csr_degree", "input": str(inputs), "offline": offline,
                "reference": reference, "expected": control_analysis.inspect(offline, output, reference)}
        events = [{"role": role, "ordinal": ordinal, "lane": lane, "queued_ns": 1, "submitted_ns": 2,
                   "start_ns": start, "end_ns": end}
                  for role, ordinal, lane, start, end in (("hbm_wrapper", 0, 0, 10, 100),
                      ("apply", 0, 0, 20, 90), ("little", 0, 0, 30, 80), ("big", 1, 11, 40, 70))]
        observed = {**offline, "status": "ORIGINAL_R_GUARDED_BOARD_CONTROL_PASS", "board_programmed": True,
                    "hardware_timing_measured": True, "bdf": "0000:82:00.1", "events": events,
                    "enqueue_to_completion_ms": 0.001, "event_union_ns": 90, "event_span_ns": 90}
        (output / "result.json").write_text(json.dumps(observed))
        return output, case, observed

    def test_all_replicas_oracle_and_overlapping_events(self):
        with tempfile.TemporaryDirectory() as directory:
            output, case, observed = self.fixture(Path(directory))
            checked = analysis.inspect(observed, output, case, observed["bdf"])
            self.assertEqual(checked["event_union_ns"], 90)
            self.assertEqual(checked["event_span_cycles_at_implemented_clock"], 13.5)
            self.assertEqual(len(checked["pins"]), 16)
            self.assertEqual(observed["status"], "ORIGINAL_R_GUARDED_BOARD_CONTROL_PASS")

    def test_event_window_gaps_overlap_and_invalid_timestamps(self):
        def event(start, end):
            return dict(queued_ns=0, submitted_ns=0, start_ns=start, end_ns=end)
        self.assertEqual(analysis.event_window([event(50, 60), event(1, 10), event(5, 20)]), (29, 59))
        for events in ([], None, [None], [event(3, 3)], [event(4, 2)], [event(True, 2)],
                       [event(-1, 2)], [event(0, 2**64)], [{**event(2, 4), "submitted_ns": 3}]):
            with self.subTest(events=events), self.assertRaises(ValueError):
                analysis.event_window(events)

    def test_board_claims_geometry_event_assignment_and_wall_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            output, case, observed = self.fixture(Path(directory))
            for changes in ({"bdf": "other"}, {"status": "offline"}, {"publication_match": True},
                            {"hardware_timing_measured": False}, {"board_programmed": 1},
                            {"iterations": 2}, {"binding": "author_initial"}, {"tasks": 3},
                            {"event_span_ns": 91}, {"event_union_ns": 91}, {"event_union_ns": True},
                            {"enqueue_to_completion_ms": float("nan")}, {"enqueue_to_completion_ms": 0},
                            {"enqueue_to_completion_ms": 0.00001}, {"events": None}, {"events": [None]},
                            {"events": observed["events"][:-1]}, {"events": observed["events"][::-1]}):
                with self.subTest(changes=changes), self.assertRaises(ValueError):
                    analysis.inspect({**observed, **changes}, output, case, observed["bdf"])
            for changes in ({"ordinal": True}, {"lane": 12}, {"role": "little"}):
                changed = copy.deepcopy(observed)
                changed["events"][-1].update(changes)
                with self.assertRaises(ValueError):
                    analysis.inspect(changed, output, case, observed["bdf"])

    def test_expected_guard_and_each_output_replica_are_checked(self):
        with tempfile.TemporaryDirectory() as directory:
            output, case, observed = self.fixture(Path(directory))
            for name in ("expected.u32le", *(f"replica{lane}.u32le" for lane in range(14))):
                path = output / name
                original = path.read_bytes()
                path.write_bytes(original[:-1] + bytes([original[-1] ^ 1]))
                with self.subTest(name=name), self.assertRaises(ValueError):
                    analysis.inspect(observed, output, case, observed["bdf"])
                path.write_bytes(original)
            changed = copy.deepcopy(case)
            changed["expected"]["expected_sha256"] = "not-the-audited-oracle"
            with self.assertRaises(ValueError):
                analysis.inspect(observed, output, changed, observed["bdf"])
            path = Path(case["input"]) / "mixed.u32le"
            payload = bytearray(path.read_bytes())
            payload[40:44] = (4).to_bytes(4, "little")
            path.write_bytes(payload)
            with self.assertRaises(ValueError):
                analysis.inspect(observed, output, case, observed["bdf"])

    def rows(self):
        return [{"graph": graph, "binding": binding, "repeat": repeat, "analysis": {
            "independent_oracle": {"expected_sha256": graph + binding}, "enqueue_to_completion_ms": repeat + 1,
            "event_union_ns": repeat + 10, "event_span_ns": repeat + 20}}
            for graph in preparation.GRAPHS for binding in control_analysis.BINDINGS
            for repeat in range(preparation.REPEATS)]

    def test_matrix_requires_all_rows_and_stable_repeated_outputs(self):
        rows = self.rows()
        summaries = analysis.matrix(rows)
        self.assertEqual(len(summaries), 6)
        self.assertEqual(summaries[0]["enqueue_to_completion_ms"], {"minimum": 1, "median": 2, "maximum": 3})
        for bad in (rows[:-1], rows[1:] + [rows[1]]):
            with self.assertRaises(ValueError):
                analysis.matrix(bad)
        changed = copy.deepcopy(rows)
        changed[0]["analysis"]["independent_oracle"]["expected_sha256"] = "changed"
        with self.assertRaises(ValueError):
            analysis.matrix(changed)


if __name__ == "__main__":
    unittest.main()
