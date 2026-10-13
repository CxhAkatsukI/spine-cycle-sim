"""Reject incomplete resident state, free copies and altered fixed allocations."""

from copy import deepcopy
import unittest

from spine_cycle_sim.experiments.evaluation_impact.common_g.sharded.metadata_layout.lifecycle.analysis import analyze
from spine_cycle_sim.experiments.evaluation_impact.common_g.sharded.metadata_layout.lifecycle.preparation import (
    ARMS, CASES, contract)
from spine_cycle_sim.experiments.evaluation_impact.common_g.sharded.metadata_layout.lifecycle.resources import (
    BASE_NAMES, REPLICA_CHANNELS)


def resource_fixture(replicated):
    regions, spans = [], [0] * 23

    def append(shard, name, channel, base, logical=4096):
        regions.append({"shard": shard, "name": name, "channel": channel,
                        "base": base, "logical_bytes": logical, "allocated_bytes": 4096})
        spans[channel] = base + 4096

    for shard in range(3):
        for name in BASE_NAMES:
            channel = {"row": 1, "binary": 2}.get(name)
            if channel is None:
                channel = (0, 6, 12, 18)[int(name[-1])]
            append(shard, name, channel, spans[channel])
    if replicated:
        for shard in range(3):
            for name in ("row", "binary"):
                base = max(spans)
                for cu, channel in enumerate(REPLICA_CHANNELS):
                    append(shard, name + "-cu" + str(cu), channel, base)
    return {"regions": regions, "allocated_bytes": len(regions) * 4096,
        "channel_span_bytes": sum(spans), "used_channels": sum(bool(n) for n in spans),
        "extra_metadata_bytes": 24 * 4096 if replicated else 0,
        "initial_metadata_upload_bytes": (30 if replicated else 6) * 4096,
        "interbatch_metadata_upload_bytes": 0, "metadata_reservations_fixed": True}


def fixture():
    rows = []
    for item in contract()["matrix"]:
        batches = []
        for count in CASES[item["case"]]:
            touched = count // 64
            pma = touched * 2 * 131072 * 64
            batches.append({"cycles": (100 if item["arm"] == ARMS[0] else 104) if count else 0,
                "physical_updates": count, "updated_shards": touched, "cache_updates": count,
                "ddr_updates": 0, "row_reads": count, "binary_probes": count,
                "multi_segment_updates": count, "pma_read_bytes": pma, "pma_write_bytes": pma,
                "read_bytes": pma + count * 24, "write_bytes": pma, "full_payload_pass": True})
        rows.append({**item, "observation": {**item, "vertices": 161, "total_shards": 3,
            "timing_kind": "declared_prediction", "batches": batches,
            "resources": None if item["arm"] == ARMS[0] else resource_fixture(item["arm"] == ARMS[2])},
            "batch_states": [{"path": str(i), "sha256": digest * 64}
                             for i, digest in enumerate(("a", "a", "b"))], "state_sha256": "b" * 64})
    return rows


class MetadataLifecycleTests(unittest.TestCase):
    def test_complete_sequence_is_not_baseline_or_hardware_admission(self):
        result = analyze(fixture())
        self.assertEqual(result["prediction_rows"], 12)
        self.assertEqual(result["batch_observations"], 36)
        self.assertEqual(len(result["comparisons"]), 12)
        self.assertIsNone(result["four_bank_ten_percent_target_met"])
        self.assertTrue(result["copies_ten_percent_diagnostic_met"])
        for key in ("production_baseline_admitted", "hardware_timing_admitted",
                    "publication_match_admitted", "host_inclusive_timing_admitted", "production_layout_changed"):
            self.assertFalse(result[key])

    def test_missing_duplicate_or_unknown_row_is_rejected(self):
        rows = fixture()
        for bad in (rows[:-1], rows + rows[:1], rows[:-1] + rows[:1]):
            with self.assertRaises(ValueError):
                analyze(bad)

    def test_missing_batches_work_or_empty_batch_charge_is_rejected(self):
        for key, value in (("physical_updates", 0), ("pma_read_bytes", 0),
                           ("binary_probes", 0), ("full_payload_pass", False), ("cycles", -1)):
            rows = fixture()
            rows[-1]["observation"]["batches"][0][key] = value
            with self.assertRaises(ValueError):
                analyze(rows)
        rows = fixture()
        rows[-1]["observation"]["batches"][1]["cycles"] = 1
        with self.assertRaises(ValueError):
            analyze(rows)
        rows = fixture()
        rows[-1]["observation"]["batches"].pop()
        with self.assertRaises(ValueError):
            analyze(rows)

    def test_empty_batch_changes_or_cross_arm_state_divergence_is_rejected(self):
        rows = fixture()
        rows[-1]["batch_states"][1]["sha256"] = "c" * 64
        with self.assertRaises(ValueError):
            analyze(rows)
        rows = fixture()
        rows[-1]["batch_states"][2]["sha256"] = rows[-1]["state_sha256"] = "c" * 64
        with self.assertRaisesRegex(ValueError, "between arms"):
            analyze(rows)

    def test_free_copy_upload_or_overlapping_resources_is_rejected(self):
        for key, value in (("allocated_bytes", 1), ("extra_metadata_bytes", 0),
                           ("initial_metadata_upload_bytes", 0), ("interbatch_metadata_upload_bytes", 1),
                           ("used_channels", 1), ("metadata_reservations_fixed", False)):
            rows = fixture()
            rows[-1]["observation"]["resources"][key] = value
            with self.assertRaises(ValueError):
                analyze(rows)
        for key, value in (("channel", 23), ("channel", 22), ("base", 1),
                           ("base", 512 * 1024**2), ("logical_bytes", 1), ("allocated_bytes", 8192)):
            rows = fixture()
            rows[-1]["observation"]["resources"]["regions"][-1][key] = value
            with self.assertRaises(ValueError):
                analyze(rows)

    def test_retained_original_table_or_lane_connectivity_is_required(self):
        rows = fixture()
        regions = rows[-1]["observation"]["resources"]["regions"]
        regions.pop(next(i for i, region in enumerate(regions) if region["name"] == "row"))
        with self.assertRaises(ValueError):
            analyze(rows)
        rows = fixture()
        rows[-1]["observation"]["resources"]["regions"][0]["channel"] = 22
        with self.assertRaises(ValueError):
            analyze(rows)

    def test_recomputed_ledger_cannot_hide_a_changed_original_allocation(self):
        rows = fixture()
        value = rows[-1]["observation"]["resources"]
        region = value["regions"][0]
        region["base"] += 4096 * 100
        value["channel_span_bytes"] = sum(max(
            (r["base"] + r["allocated_bytes"] for r in value["regions"] if r["channel"] == bank),
            default=0) for bank in range(23))
        with self.assertRaisesRegex(ValueError, "allocations changed"):
            analyze(rows)

    def test_slow_copy_row_is_kept_without_cherry_picking(self):
        rows = deepcopy(fixture())
        rows[-1]["observation"]["batches"][2]["cycles"] = 200
        result = analyze(rows)
        self.assertEqual(result["batch_observations"], 36)
        self.assertFalse(result["copies_ten_percent_diagnostic_met"])


if __name__ == "__main__":
    unittest.main()
