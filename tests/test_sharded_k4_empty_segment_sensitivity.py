"""Synthetic admission checks for the unfitted empty-helper sensitivity."""

import copy
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest

from spine_cycle_sim.experiments.sharded_k4_stages.empty_segment.sensitivity import analysis


class EmptySegmentSensitivityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.geometry = {"padded_vertices": 16}
        self.payload = struct.pack("<16I", *range(16))
        self.digest = hashlib.sha256(self.payload).hexdigest()
        self.names = ("k4_primary", "k4_source0", "k4_source1")
        for name in self.names:
            (self.root / (name + ".u32le")).write_bytes(self.payload)
        self.reference = {
            "path": "actual_k4", "passed": True, "cycles": 1000,
            "read_bytes": 2112, "write_bytes": 196,
            "extent_reads": 4, "row_reads": 16, "segment_reads": 8,
            "source_lines": 4, "physical_packets": 4, "live_edges": 25,
            "dummy_edges": 7, "active_vertices": 5,
            "checked_words_per_replica": 16, "replicas": 3,
            "full_state_and_traffic_pass": True,
        }
        self.basis = {
            "paths": [{"path": "original_a4", "cycles": 250}, self.reference],
            "outputs": [{"path": str(self.root / "frozen" / (name + ".u32le")),
                         "sha256": self.digest, "bytes": len(self.payload)}
                        for name in self.names],
        }

    def metadata(self, arm):
        return {"mode": "legacy_v4_control" if arm == 73 else "empty_helper_bypass_uncalibrated",
                "empty_segment_exit_cycles": arm, "hardware_timing_admitted": False,
                "publication_match_admitted": False}

    def counters(self, arm, basis=None):
        row = copy.deepcopy((self.basis if basis is None else basis)["paths"][1])
        if arm == 0:
            row["cycles"] -= 100
        return row

    def stdout(self, arm, row=None, metadata=None):
        return ("SENSITIVITY " + json.dumps(self.metadata(arm) if metadata is None else metadata)
                + "\nREAL_ROUND " + json.dumps(self.counters(arm) if row is None else row) + "\n")

    def admit(self, arm, row=None, metadata=None, basis=None):
        return analysis.admit(self.stdout(arm, row, metadata), self.root, self.geometry,
                              self.basis if basis is None else basis, arm)

    def cases(self):
        cases = []
        for mode, latency in (("cold", 64), ("warm_update", 64), ("warm_update", 128)):
            basis = copy.deepcopy(self.basis)
            basis["paths"][1]["cycles"] = (30000 if mode == "cold" else 20000) + latency * 100
            for reverse in (0, 1):
                for arm in (73, 0):
                    admitted = self.admit(arm, self.counters(arm, basis), basis=basis)
                    cases.append({"mode": mode, "latency": latency, "reverse": reverse,
                                  "empty_exit": arm, **admitted})
        return cases

    def test_complete_12_arm_matrix_preserves_claim_boundaries(self):
        cases = self.cases()
        expected = [(mode, latency, reverse, arm)
                    for mode, latency in (("cold", 64), ("warm_update", 64), ("warm_update", 128))
                    for reverse in (0, 1) for arm in (73, 0)]
        self.assertEqual([(c["mode"], c["latency"], c["reverse"], c["empty_exit"]) for c in cases],
                         expected)
        self.assertEqual(analysis.matrix(cases), {
            "status": "passed_empty_helper_sensitivity_not_hardware_calibration", "cases": 12,
            "legacy_exact_replay": True, "complete_state_and_traffic": True,
            "registration_order_identical": True, "latency_sensitivity_checked": True,
            "convergence_comparison": False, "hardware_timing_admitted": False,
            "production_profile_modified": False, "publication_match_admitted": False,
            "strict_resource_match_admitted": False,
        })

    def test_both_arms_admit_all_complete_outputs_and_diagnostic_ratios(self):
        for arm in (73, 0):
            with self.subTest(arm=arm):
                result = self.admit(arm)
                self.assertEqual(result["counters"], self.counters(arm))
                self.assertEqual(result["outputs"], [
                    {"path": str(self.root / (name + ".u32le")), "sha256": self.digest,
                     "bytes": len(self.payload)} for name in self.names])
                self.assertEqual(result["legacy_over_arm_cycles_diagnostic_only"],
                                 1000 / result["counters"]["cycles"])
                self.assertEqual(result["arm_over_frozen_a4_cycles_diagnostic_only"],
                                 result["counters"]["cycles"] / 250)

    def test_missing_or_duplicate_trace_rows_are_rejected(self):
        for arm in (73, 0):
            declaration, row = self.stdout(arm).splitlines()
            for label, lines in (("missing_metadata", [row]), ("missing_case", [declaration]),
                                 ("duplicate_metadata", [declaration, declaration, row]),
                                 ("duplicate_case", [declaration, row, row]), ("empty", [])):
                with self.subTest(arm=arm, change=label):
                    with self.assertRaisesRegex(ValueError, "missing or duplicate"):
                        analysis.admit("\n".join(lines), self.root, self.geometry, self.basis, arm)

    def test_metadata_requires_exact_mode_arm_and_boolean_claims(self):
        for arm in (73, 0):
            changes = (("mode", "other"), ("empty_segment_exit_cycles", 0 if arm == 73 else 73),
                       ("empty_segment_exit_cycles", float(arm)),
                       ("hardware_timing_admitted", True), ("hardware_timing_admitted", 0),
                       ("publication_match_admitted", True), ("publication_match_admitted", 0))
            for key, value in changes:
                with self.subTest(arm=arm, key=key, value=value):
                    declaration = self.metadata(arm)
                    declaration[key] = value
                    with self.assertRaisesRegex(ValueError, "sensitivity declaration"):
                        self.admit(arm, metadata=declaration)
            for change in ("missing", "extra"):
                with self.subTest(arm=arm, change=change):
                    declaration = self.metadata(arm)
                    if change == "missing":
                        del declaration["publication_match_admitted"]
                    else:
                        declaration["unclaimed"] = False
                    with self.assertRaises(ValueError):
                        self.admit(arm, metadata=declaration)
        for arm in (-1, 1, 72, 74):
            with self.subTest(arm=arm):
                with self.assertRaises(ValueError):
                    self.admit(arm)

    def test_counter_schema_and_complete_state_flags_are_required(self):
        for change in ("missing", "extra"):
            with self.subTest(change=change):
                row = self.counters(73)
                if change == "missing":
                    del row["dummy_edges"]
                else:
                    row["unknown_counter"] = 0
                with self.assertRaisesRegex(ValueError, "counter schema"):
                    self.admit(73, row)
        for key, value in (("path", "original_a4"), ("passed", False), ("passed", 1),
                           ("full_state_and_traffic_pass", False), ("full_state_and_traffic_pass", 1),
                           ("replicas", 2), ("checked_words_per_replica", 15)):
            with self.subTest(key=key, value=value):
                row = self.counters(73)
                row[key] = value
                with self.assertRaisesRegex(ValueError, "complete state and traffic"):
                    self.admit(73, row)

    def test_every_counter_rejects_bool_float_string_null_and_negative(self):
        keys = [key for key, value in self.reference.items() if type(value) is int]
        for arm in (73, 0):
            for key in keys:
                for value in (True, False, float(self.reference[key]), str(self.reference[key]), None, -1):
                    with self.subTest(arm=arm, key=key, value=value):
                        row = self.counters(arm)
                        row[key] = value
                        with self.assertRaises(ValueError):
                            self.admit(arm, row)

    def test_cycle_budget_and_legacy_replay_are_enforced_without_selecting_speedup(self):
        for arm in (73, 0):
            for cycles in (0, 100000001):
                with self.subTest(arm=arm, cycles=cycles):
                    row = self.counters(arm)
                    row["cycles"] = cycles
                    with self.assertRaisesRegex(ValueError, "fixed budget"):
                        self.admit(arm, row)
        for cycles in (999, 1001):
            with self.subTest(legacy_cycles=cycles):
                row = self.counters(73)
                row["cycles"] = cycles
                with self.assertRaisesRegex(ValueError, "legacy cycles"):
                    self.admit(73, row)
        for cycles in (1000, 1001):
            with self.subTest(candidate_cycles=cycles):
                row = self.counters(0)
                row["cycles"] = cycles
                self.assertEqual(self.admit(0, row)["counters"]["cycles"], cycles)

    def test_candidate_must_preserve_every_traffic_and_work_counter(self):
        keys = [key for key, value in self.reference.items()
                if type(value) is int and key not in {"cycles", "replicas", "checked_words_per_replica"}]
        for key in keys:
            with self.subTest(key=key):
                row = self.counters(0)
                row[key] += 1
                with self.assertRaisesRegex(ValueError, "conserved traffic"):
                    self.admit(0, row)

    def test_each_output_requires_its_full_hash(self):
        for name in self.names:
            with self.subTest(name=name):
                path = self.root / (name + ".u32le")
                corrupted = bytearray(self.payload)
                corrupted[len(corrupted) // 2] ^= 1
                path.write_bytes(corrupted)
                try:
                    with self.assertRaisesRegex(ValueError, "complete K4 state"):
                        self.admit(0)
                finally:
                    path.write_bytes(self.payload)

    def test_each_output_requires_exact_full_size(self):
        for name in self.names:
            for payload in (self.payload[:-4], self.payload + b"\x00\x00\x00\x00"):
                with self.subTest(name=name, size=len(payload)):
                    path = self.root / (name + ".u32le")
                    path.write_bytes(payload)
                    basis = copy.deepcopy(self.basis)
                    frozen = next(item for item in basis["outputs"] if Path(item["path"]).name == path.name)
                    frozen["sha256"] = hashlib.sha256(payload).hexdigest()
                    try:
                        with self.assertRaisesRegex(ValueError, "complete K4 state"):
                            self.admit(0, basis=basis)
                    finally:
                        path.write_bytes(self.payload)

    def test_each_output_rejects_symlink_even_to_identical_bytes(self):
        target = self.root / "identical.u32le"
        target.write_bytes(self.payload)
        for name in self.names:
            with self.subTest(name=name):
                path = self.root / (name + ".u32le")
                path.unlink()
                path.symlink_to(target)
                try:
                    with self.assertRaisesRegex(ValueError, "complete K4 state"):
                        self.admit(0)
                finally:
                    path.unlink()
                    path.write_bytes(self.payload)

    def test_replicas_must_agree_even_if_each_matches_its_frozen_hash(self):
        path = self.root / "k4_source1.u32le"
        payload = self.payload[:-4] + struct.pack("<I", 999)
        path.write_bytes(payload)
        basis = copy.deepcopy(self.basis)
        basis["outputs"][2]["sha256"] = hashlib.sha256(payload).hexdigest()
        with self.assertRaisesRegex(ValueError, "complete K4 replicas differ"):
            self.admit(0, basis=basis)

    def test_matrix_rejects_missing_duplicate_and_reordered_cases(self):
        for change in ("missing", "extra_duplicate", "replacement_duplicate", "reordered"):
            with self.subTest(change=change):
                cases = self.cases()
                if change == "missing":
                    cases.pop()
                elif change == "extra_duplicate":
                    cases.append(copy.deepcopy(cases[-1]))
                elif change == "replacement_duplicate":
                    cases[1] = copy.deepcopy(cases[0])
                else:
                    cases[0], cases[1] = cases[1], cases[0]
                with self.assertRaisesRegex(ValueError, "missing, duplicated or reordered"):
                    analysis.matrix(cases)

    def test_registration_order_preserves_state_cycles_and_traffic_for_each_arm(self):
        for mode, latency in (("cold", 64), ("warm_update", 64), ("warm_update", 128)):
            for arm in (73, 0):
                for change in ("state", "cycles", "read_bytes"):
                    with self.subTest(mode=mode, latency=latency, arm=arm, change=change):
                        cases = self.cases()
                        reverse = next(c for c in cases if (c["mode"], c["latency"], c["empty_exit"],
                                       c["reverse"]) == (mode, latency, arm, 1))
                        if change == "state":
                            reverse["outputs"][0]["sha256"] = "0" * 64
                        else:
                            reverse["counters"][change] += 1
                        with self.assertRaisesRegex(ValueError, "registration order"):
                            analysis.matrix(cases)

    def test_latency_requires_increasing_cycles_and_identical_state_and_traffic(self):
        for arm in (73, 0):
            for change in ("equal_cycles", "lower_cycles", "state", "read_bytes", "write_bytes", "live_edges"):
                with self.subTest(arm=arm, change=change):
                    cases = self.cases()
                    low = next(c for c in cases if (c["mode"], c["latency"], c["empty_exit"],
                               c["reverse"]) == ("warm_update", 64, arm, 0))
                    # Change both registration orders to isolate the latency gate.
                    for high in cases:
                        if (high["mode"], high["latency"], high["empty_exit"]) != ("warm_update", 128, arm):
                            continue
                        if change in {"equal_cycles", "lower_cycles"}:
                            high["counters"]["cycles"] = low["counters"]["cycles"] - (change == "lower_cycles")
                        elif change == "state":
                            high["outputs"][0]["sha256"] = "0" * 64
                        else:
                            high["counters"][change] += 1
                    with self.assertRaisesRegex(ValueError, "latency sensitivity or conserved traffic"):
                        analysis.matrix(cases)


if __name__ == "__main__":
    unittest.main()
