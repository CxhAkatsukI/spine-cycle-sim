from __future__ import annotations

from dataclasses import dataclass
import unittest

from spine_cycle_sim.experiments.grasu_addressing import (
    FROZEN_CANDIDATE10_ADDRESS_PARAMETERS,
    grasu_hbm_address_environment,
    partition_layout_footprints,
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


if __name__ == "__main__":
    unittest.main()
