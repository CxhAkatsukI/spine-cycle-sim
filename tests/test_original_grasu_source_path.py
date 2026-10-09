"""Strict functional admission for the separately owned original G source path."""

import json
from pathlib import Path
import struct
import tempfile
import unittest

from spine_cycle_sim.experiments.upstream_controls.grasu.analysis import check_protocol, parse_stdout, analyze, check_diagnostics, WIDTH_WARNING
from spine_cycle_sim.experiments.upstream_controls.grasu.fixtures import (
    HOT, SEGMENTS, NAMES, batches, edge, final_state, request_rows, route, targets)
from spine_cycle_sim.experiments.upstream_controls.grasu.preparation import preserve, validate_contract


def protocol(case):
    rows = [0x47535031, 1, case, len(batches(case)), SEGMENTS, HOT]
    for index, batch in enumerate(batches(case)):
        requests = request_rows(batch); rows += [index, len(batch), len(requests)]
        for item in batch:
            value = edge(item); rows += [value & 0xffffffff, value >> 32, item[0] * 16, value & 0xffffffff, value >> 32, route(item[0])]
        for kernel, lane, kind, address, value in requests: rows += [kernel, lane, kind, address, value & 0xffffffff, value >> 32]
    return struct.pack(f"<{len(rows)}I", *rows)


def stdout(expected):
    keys = ("case", "batches", "updates", "memory_requests", "route_updates", "checked_buffer_slots",
        "search_lane_end_checks", "cache_invocations", "ddr_invocations")
    return "dispatch finish\n" * expected["batches"] + "GRASU_PATH " + json.dumps({key: expected[key] for key in keys}) + "\n"


class OriginalGraSUPathTests(unittest.TestCase):
    def test_all_fixed_fixtures_and_update_counts(self):
        counts = [check_protocol(protocol(case), case)["updates"] for case in range(8)]
        self.assertEqual(counts, [0, 1, 3, 65, 257, 192, 192, 896])
        for case in range(8): parse_stdout(stdout(check_protocol(protocol(case), case)), check_protocol(protocol(case), case))

    def test_routes_banks_and_boundary_rows(self):
        self.assertEqual(len(targets()), 128)
        self.assertEqual([sum(route(segment) == i for segment in targets()) for i in range(4)], [32] * 4)
        for half in range(2):
            for row in (0, HOT - 16, HOT, HOT + 16):
                self.assertEqual({segment // 2 % 16 for segment in targets() if segment % 2 == half and row <= segment // 2 < row + 16}, set(range(16)))

    def test_zero_batch_still_preloads_and_writes_full_cache(self):
        result = check_protocol(protocol(0), 0)
        self.assertEqual(result["source_loop_cache_read_bytes"], 16777216)
        self.assertEqual(result["source_loop_cache_write_bytes"], 16777216)
        self.assertEqual(result["source_access_ddr_read_bytes"], 0)
        self.assertEqual(result["search_lane_end_checks"], 512)

    def test_short_batch_and_all_256_search_lanes(self):
        self.assertEqual(sum(item[2] == 0 for item in request_rows(batches(2)[0])), 3)
        self.assertEqual(len({item[:2] for item in request_rows(batches(4)[0])}), 256)

    def test_damaged_capture_fields_rejected(self):
        payload = protocol(1)
        for offset in (0, 8, 24, 36, 44, 56, 60, 76):
            damaged = bytearray(payload); damaged[offset] ^= 1
            with self.subTest(offset=offset), self.assertRaises(ValueError): check_protocol(bytes(damaged), 1)

    def test_truncated_trailing_and_wrong_case_rejected(self):
        payload = protocol(1)
        for damaged in (payload[:-1], payload[:-4], payload + b"\0" * 4):
            with self.assertRaises(ValueError): check_protocol(damaged, 1)
        with self.assertRaises(ValueError): check_protocol(payload, 2)

    def test_observed_counter_warnings_duplicates_and_booleans_rejected(self):
        result = check_protocol(protocol(1), 1); text = stdout(result)
        for invalid in (text + "WARNING empty stream\n", text + text, text.replace('"updates": 1', '"updates": true'), text.replace("dispatch finish\n", "")):
            with self.assertRaises(ValueError): parse_stdout(invalid, result)
        with self.assertRaises(ValueError): parse_stdout(text.replace('"case": 1', '"case": 1, "case": 1'), result)

    def test_only_exact_upstream_width_diagnostic_is_admitted(self):
        self.assertEqual(check_diagnostics(WIDTH_WARNING, 1), 2)
        for invalid in ("", WIDTH_WARNING * 2, WIDTH_WARNING + "runtime error: UB", WIDTH_WARNING + "empty stream"):
            with self.assertRaises(ValueError): check_diagnostics(invalid, 1)

    def test_full_merged_state_and_runtime_diagnostics(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary); (directory / "protocol.u32le").write_bytes(protocol(1))
            state = final_state(1); (directory / "state.u32le").write_bytes(state)
            out = directory / "out.txt"; err = directory / "err.txt"
            out.write_text(stdout(check_protocol(protocol(1), 1))); err.write_text(WIDTH_WARNING)
            result = analyze(directory, 1, out, err)
            self.assertEqual(result["state_sha256"], result["oracle_state_sha256"])
            damaged = bytearray(state); damaged[-4] ^= 1; (directory / "state.u32le").write_bytes(damaged)
            with self.assertRaisesRegex(ValueError, "full-state"): analyze(directory, 1, out, err)
            err.write_text("undefined behavior")
            with self.assertRaisesRegex(ValueError, "diagnostics"): analyze(directory, 1, out, err)

    def test_invalid_fixture_identity(self):
        for case in (-1, 8, True, "1"):
            with self.assertRaises(ValueError): batches(case)

    def test_old_identity_cannot_be_relabeled_as_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); baseline = root / "baseline"; baseline.mkdir()
            (root / "old.cpp").write_text("changed")
            (baseline / "baseline.json").write_text(json.dumps({"files": [{"path": "old.cpp", "sha256": "0" * 64}]}))
            with self.assertRaisesRegex(ValueError, "old code/evidence"): preserve(root, baseline)

    def test_contract_names(self):
        root = Path(__file__).resolve().parents[1]
        contract = json.loads((root / "configs/experiments/original_grasu_source_path_v1.json").read_text())
        self.assertEqual(contract["cases"], list(NAMES)); self.assertTrue(contract["instrument_all_cases"])
        self.assertIn("G_paper8_geometry", contract["not_claimed"])
        validate_contract(contract)
        for field, value in (("segment_slots", 8), ("instrument_all_cases", 1), ("search_kernels", 1), ("run_timeout_seconds", 0)):
            with self.assertRaises(ValueError): validate_contract({**contract, field: value})


if __name__ == "__main__": unittest.main()
