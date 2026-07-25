from __future__ import annotations

import json
from pathlib import Path
import unittest

from scripts.run_sst_grasu_regraph_partitioned_dynamic_pagerank import (
    expected_update_summary,
    partition_layout_footprints,
    validate_address_map,
    validate_partition_footprints,
)


ROOT = Path(__file__).resolve().parents[1]
PROFILE = (
    ROOT
    / "configs"
    / "architectures"
    / "grasu_regraph_partitioned_dynamic_pagerank_spine23.json"
)


class GraSuPartitionedDynamicRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        profile = json.loads(PROFILE.read_text(encoding="utf-8"))
        self.params = profile["parameters"]
        self.channel_bytes = profile["memory"]["channel_capacity_bytes"]

    def test_slice_summary_distinguishes_topology_and_weight_updates(self) -> None:
        summary = expected_update_summary(
            ROOT
            / "tests"
            / "data"
            / "grasu_regraph_partitioned_dynamic_initial.slice",
            ROOT
            / "tests"
            / "data"
            / "grasu_regraph_partitioned_dynamic_update.slice",
            16,
        )
        self.assertEqual(summary["vertices"], 33)
        self.assertEqual(summary["initial_edges"], 4)
        self.assertEqual(summary["final_edges"], 4)
        self.assertEqual(summary["inserts"], 2)
        self.assertEqual(summary["deletes"], 2)
        self.assertEqual(summary["weight_decreases"], 1)
        self.assertEqual(summary["weight_increases"], 1)
        self.assertEqual(summary["partitions_touched"], 3)

    def test_frozen_two_partition_address_map_is_disjoint(self) -> None:
        regions = validate_address_map(
            self.params, self.channel_bytes, 2, 65_537, 6
        )
        self.assertEqual(regions["binary"][0], 64 << 20)
        self.assertEqual(regions["row"][0], 128 << 20)
        self.assertEqual(regions["pma"][0], 256 << 20)
        self.assertEqual(regions["source_state"][0], 384 << 20)

    def test_layout_footprint_is_derived_from_reserved_edges(self) -> None:
        footprints = partition_layout_footprints(
            ROOT
            / "tests"
            / "data"
            / "grasu_regraph_partitioned_dynamic_initial.slice",
            ROOT
            / "tests"
            / "data"
            / "grasu_regraph_partitioned_dynamic_update.slice",
            16,
        )
        self.assertEqual([row["segments"] for row in footprints], [2, 2, 2])
        validate_partition_footprints(self.params, footprints)

    def test_partition_payload_larger_than_stride_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "pma_bytes_per_channel"):
            validate_partition_footprints(
                self.params,
                [
                    {
                        "partition": 0,
                        "row_bytes": 8,
                        "binary_bytes": 8,
                        "pma_bytes_per_channel": 16 * 1024 * 1024 + 64,
                        "segments": 1,
                    }
                ],
            )

    def test_fifth_partition_requires_address_remap(self) -> None:
        with self.assertRaisesRegex(ValueError, "windows overlap"):
            validate_address_map(
                self.params, self.channel_bytes, 5, 5 * 65_536, 6
            )

    def test_degree_and_vertex_state_alias_is_rejected(self) -> None:
        params = dict(self.params)
        params["grasu_degree_base_bytes"] = params["grasu_vertex_state_base_bytes"]
        with self.assertRaisesRegex(ValueError, "vertex-state and degree"):
            validate_address_map(params, self.channel_bytes, 2, 65_537, 6)


if __name__ == "__main__":
    unittest.main()
