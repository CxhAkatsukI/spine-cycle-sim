from __future__ import annotations

from dataclasses import dataclass
import unittest

from spine_cycle_sim.experiments.grasu_addressing import (
    FROZEN_CANDIDATE10_ADDRESS_PARAMETERS,
    grasu_hbm_address_environment,
    partition_layout_footprints,
    source_state_prefetch_guard_bytes,
    validate_grasu_hbm_address_map,
    validate_partition_footprints,
)


@dataclass(frozen=True)
class Record:
    src: int
    dst: int
    weight: int
    diff: int = 1


def parameters() -> dict[str, object]:
    return {
        **FROZEN_CANDIDATE10_ADDRESS_PARAMETERS,
        "max_destination_partitions_without_address_remap": 4,
        "grasu_pma_hbm_first_channel": 0,
        "grasu_pma_hbm_channels": 4,
        "regraph_source_state_channel": 1,
        "regraph_source_state_mirror_channel": 3,
        "regraph_partition_vertices": 65_536,
        "regraph_source_buffer_vertices": 4_096,
        "regraph_apply_state_channel": 30,
        "regraph_degree_channel": 30,
    }


class GraSuAddressingTests(unittest.TestCase):
    def test_frozen_four_partition_map_is_physically_disjoint(self) -> None:
        windows = validate_grasu_hbm_address_map(
            parameters(), 512 << 20, 4, 157_107, 8_192
        )
        self.assertEqual(windows["binary"]["base_bytes"], 64 << 20)
        self.assertEqual(windows["row"]["base_bytes"], 128 << 20)
        self.assertEqual(windows["pma"]["base_bytes"], 256 << 20)
        self.assertEqual(windows["source_state"]["base_bytes"], 384 << 20)

    def test_four_gib_stride_is_rejected_on_a_512_mib_channel(self) -> None:
        invalid = parameters()
        invalid["grasu_partition_address_stride_bytes"] = 4 << 30
        with self.assertRaisesRegex(ValueError, "exceeds one"):
            validate_grasu_hbm_address_map(invalid, 512 << 20, 2, 8, 1)

    def test_fifth_partition_requires_a_new_address_map(self) -> None:
        with self.assertRaisesRegex(ValueError, "supports 4"):
            validate_grasu_hbm_address_map(
                parameters(), 512 << 20, 5, 5 * 65_536, 8
            )

    def test_full_word_reservation_counts_weight_variants(self) -> None:
        initial = [Record(0, 1, 1)]
        updates = [Record(0, 1, weight) for weight in range(2, 18)]
        weighted = partition_layout_footprints(
            initial, updates, 2, 2, (0, 1), weighted_full_word=True
        )
        destination_only = partition_layout_footprints(
            initial, updates, 2, 2, (0, 1), weighted_full_word=False
        )
        self.assertEqual(weighted[0]["segments"], 2)
        self.assertEqual(destination_only[0]["segments"], 1)
        validate_partition_footprints(parameters(), weighted)

    def test_environment_contains_every_physical_base(self) -> None:
        environment = grasu_hbm_address_environment(parameters())
        self.assertEqual(environment["GRASU_SST_BINARY_BASE"], str(64 << 20))
        self.assertEqual(
            environment["GRASU_SST_PARTITION_ADDRESS_STRIDE"], str(16 << 20)
        )

    def test_runtime_packed_map_supports_eight_partitions_without_aliasing(
        self,
    ) -> None:
        packed = parameters()
        packed.update(
            {
                "grasu_partition_address_layout": "runtime_packed_v1",
                "grasu_partition_address_arena_base_bytes": 16 << 20,
                "grasu_partition_address_alignment_bytes": 4096,
            }
        )
        vertices = 8 * 65_536
        footprints = [
            {
                "partition": partition,
                "row_bytes": vertices * 8,
                "binary_bytes": 1 << 20,
                "pma_bytes_per_channel": 8 << 20,
                "segments": 1,
            }
            for partition in range(8)
        ]
        windows = validate_grasu_hbm_address_map(
            packed, 512 << 20, 8, vertices, 8_192, footprints
        )
        self.assertEqual(len(windows["row"]["partition_bases"]), 8)
        self.assertLess(windows["source_state"]["end_bytes"], 512 << 20)
        self.assertEqual(
            windows["source_state"]["buffer_stride_bytes"], 2 << 20
        )
        self.assertEqual(
            windows["source_state"]["prefetch_guard_bytes"], 16 << 10
        )
        self.assertEqual(
            windows["source_state"]["size_bytes"], (4 << 20) + (16 << 10)
        )
        environment = grasu_hbm_address_environment(packed)
        self.assertEqual(environment["GRASU_SST_PACKED_PARTITION_ADDRESSES"], "1")

    def test_runtime_packed_map_fails_closed_on_true_capacity_overflow(self) -> None:
        packed = parameters()
        packed.update(
            {
                "grasu_partition_address_layout": "runtime_packed_v1",
                "grasu_partition_address_arena_base_bytes": 16 << 20,
                "grasu_partition_address_alignment_bytes": 4096,
            }
        )
        footprints = [
            {
                "partition": partition,
                "row_bytes": 100 << 20,
                "binary_bytes": 1 << 20,
                "pma_bytes_per_channel": 1 << 20,
                "segments": 1,
            }
            for partition in range(5)
        ]
        with self.assertRaisesRegex(ValueError, "exceeds one"):
            validate_grasu_hbm_address_map(
                packed, 512 << 20, 5, 5 * 65_536, 8, footprints
            )

    def test_interleaved_map_supports_metadata_larger_than_one_channel(self) -> None:
        interleaved = parameters()
        interleaved.update(
            {
                "grasu_partition_address_layout": "runtime_packed_interleaved_v2",
                "grasu_partition_address_arena_base_bytes": 16 << 20,
                "grasu_partition_address_alignment_bytes": 4096,
                "grasu_interleaved_hbm_first_channel": 0,
                "grasu_interleaved_hbm_channels": 23,
                "grasu_interleaved_hbm_bytes": 64,
                "grasu_physical_hbm_channels": 32,
                "hbm_pseudo_channels_budget": 23,
                "regraph_degree_channel": 31,
            }
        )
        vertices = 4_000_000
        footprints = [
            {
                "partition": partition,
                "row_bytes": vertices * 8,
                "binary_bytes": 2 << 20,
                "pma_bytes_per_channel": 4 << 20,
                "segments": 1,
            }
            for partition in range(62)
        ]
        windows = validate_grasu_hbm_address_map(
            interleaved, 512 << 20, 62, vertices, 8, footprints
        )
        self.assertGreater(windows["row"]["end_bytes"], 512 << 20)
        arena = windows["_interleaved_arena"]
        self.assertLessEqual(arena["arena_bytes"], 23 * (512 << 20))
        self.assertEqual(arena["channel_count"], 23)
        row_mappings = [
            mapping
            for mapping in arena["mappings"]
            if mapping["region"] == "row"
        ]
        self.assertEqual(len(row_mappings), 4)
        self.assertEqual(
            len({mapping["global_begin_bytes"] for mapping in row_mappings}), 1
        )
        environment = grasu_hbm_address_environment(interleaved, windows)
        self.assertEqual(
            environment["GRASU_SST_HBM_ADDRESS_MAPPING"],
            "interleaved_arena_v1",
        )
        self.assertIn(";", environment["GRASU_SST_HBM_ADDRESS_MAPPING_TABLE"])

    def test_exact_source_window_multiple_has_hls_lookahead_guard(self) -> None:
        interleaved = parameters()
        interleaved.update(
            {
                "grasu_partition_address_layout": "runtime_packed_interleaved_v2",
                "grasu_partition_address_arena_base_bytes": 16 << 20,
                "grasu_partition_address_alignment_bytes": 4096,
                "grasu_interleaved_hbm_first_channel": 0,
                "grasu_interleaved_hbm_channels": 23,
                "grasu_interleaved_hbm_bytes": 64,
                "grasu_physical_hbm_channels": 32,
                "hbm_pseudo_channels_budget": 23,
                "regraph_degree_channel": 31,
            }
        )
        vertices = 8 * 65_536
        footprints = [
            {
                "partition": partition,
                "row_bytes": vertices * 8,
                "binary_bytes": 4096,
                "pma_bytes_per_channel": 4096,
                "segments": 1,
            }
            for partition in range(8)
        ]
        windows = validate_grasu_hbm_address_map(
            interleaved, 512 << 20, 8, vertices, 16, footprints
        )
        source = windows["source_state"]
        guard = source_state_prefetch_guard_bytes(interleaved)
        self.assertEqual(guard, 16 << 10)
        self.assertEqual(
            source["end_bytes"],
            source["base_bytes"] + 2 * (2 << 20) + guard,
        )
        source_mappings = [
            mapping
            for mapping in windows["_interleaved_arena"]["mappings"]
            if mapping["region"] == "source_state"
        ]
        self.assertEqual(len(source_mappings), 2)
        self.assertTrue(
            all(
                mapping["logical_end_bytes"] == source["end_bytes"]
                for mapping in source_mappings
            )
        )

    def test_interleaved_map_fails_closed_on_aggregate_capacity(self) -> None:
        interleaved = parameters()
        interleaved.update(
            {
                "grasu_partition_address_layout": "runtime_packed_interleaved_v2",
                "grasu_partition_address_arena_base_bytes": 16 << 20,
                "grasu_partition_address_alignment_bytes": 4096,
                "grasu_interleaved_hbm_first_channel": 0,
                "grasu_interleaved_hbm_channels": 2,
                "grasu_interleaved_hbm_bytes": 64,
                "grasu_physical_hbm_channels": 32,
                "hbm_pseudo_channels_budget": 2,
                "regraph_degree_channel": 31,
            }
        )
        footprints = [
            {
                "partition": partition,
                "row_bytes": 300 << 20,
                "binary_bytes": 1 << 20,
                "pma_bytes_per_channel": 1 << 20,
                "segments": 1,
            }
            for partition in range(4)
        ]
        with self.assertRaisesRegex(ValueError, "exceeds the frozen HBM budget"):
            validate_grasu_hbm_address_map(
                interleaved, 512 << 20, 4, 4 * 65_536, 8, footprints
            )


if __name__ == "__main__":
    unittest.main()
