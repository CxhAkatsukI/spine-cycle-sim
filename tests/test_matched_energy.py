from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from spine_cycle_sim.evidence.matched_energy import (
    MatchedEnergyError,
    aggregate_detailed_dramsim3,
    grasu_selected_array_energy,
)


def _dram_row(channel: int) -> dict[str, object]:
    return {
        "channel": 0,
        "num_cycles": 100,
        "num_reads_done": channel + 1,
        "num_writes_done": channel + 2,
        "num_read_row_hits": channel,
        "num_write_row_hits": channel + 1,
        "num_act_cmds": channel + 3,
        "num_pre_cmds": channel + 4,
        "act_energy": 1.0,
        "read_energy": 2.0,
        "write_energy": 3.0,
        "ref_energy": 4.0,
        "refb_energy": 5.0,
        "act_stb_energy": {"0": 6.0},
        "pre_stb_energy": {"0": 7.0},
        "sref_energy": {"0": 8.0},
        "total_energy": 36.0,
    }


def _write_dram(root: Path, row: dict[str, object], directory: int) -> None:
    output = root / f"channel{directory}"
    output.mkdir()
    (output / "dramsim3.json").write_text(
        json.dumps({"0": row}), encoding="utf-8"
    )


class MatchedEnergyTests(unittest.TestCase):
    def test_aggregates_detailed_energy_and_all_controllers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_dram(root, _dram_row(0), 0)
            _write_dram(root, _dram_row(1), 1)
            result = aggregate_detailed_dramsim3(root, expected_channels=2)
        self.assertEqual(result["reads"], 3)
        self.assertEqual(result["writes"], 5)
        self.assertEqual(result["controller_instances"], 2)
        self.assertEqual(result["total_energy_pj"], 72.0)
        self.assertEqual(result["component_sum_pj"], 72.0)
        self.assertEqual(result["command_dynamic_energy_pj"], 12.0)
        self.assertEqual(result["background_and_refresh_energy_pj"], 60.0)
        self.assertEqual(result["refresh_energy_pj"], 18.0)
        self.assertEqual(result["controller_cycles_min"], 100)
        self.assertEqual(result["controller_cycles_max"], 100)

    def test_rejects_missing_or_duplicate_controller_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_dram(root, _dram_row(0), 0)
            with self.assertRaisesRegex(MatchedEnergyError, "expected 2"):
                aggregate_detailed_dramsim3(root, expected_channels=2)
            _write_dram(root, _dram_row(1), 2)
            with self.assertRaisesRegex(MatchedEnergyError, "not exactly"):
                aggregate_detailed_dramsim3(root, expected_channels=2)

    def test_rejects_unclosed_dramsim_energy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            row = _dram_row(0)
            row["total_energy"] = 99.0
            _write_dram(root, row, 0)
            with self.assertRaisesRegex(MatchedEnergyError, "do not close"):
                aggregate_detailed_dramsim3(root, expected_channels=1)

    def test_rejects_mismatched_controller_windows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_dram(root, _dram_row(0), 0)
            row = _dram_row(1)
            row["num_cycles"] = 101
            _write_dram(root, row, 1)
            with self.assertRaisesRegex(MatchedEnergyError, "timing window"):
                aggregate_detailed_dramsim3(root, expected_channels=2)

    def test_maps_current_eight_lane_array_activity(self) -> None:
        activity = {
            "edge_lanes": 8,
            "gather_banks": 8,
            "partition_vertices": 65_536,
            "compute_pma_slots": 80,
            "source_cache_lane_writes": 16,
            "gather_bank_updates": 5,
            "gather_reset_cycles": 10,
            "gather_merge_cycles": 20,
            "gather_rows_emitted": 20,
        }
        chars = {
            "grasu_source_cache_bank_16k_x512": {
                "read_energy_nj": 0.1,
                "write_energy_nj": 0.2,
                "leakage_power_mw": 0.01,
                "area_mm2": 0.5,
            },
            "regraph_gather_bank_64k_x64": {
                "read_energy_nj": 0.3,
                "write_energy_nj": 0.4,
                "leakage_power_mw": 0.02,
                "area_mm2": 1.0,
            },
        }
        result = grasu_selected_array_energy(activity, chars, runtime_ns=100.0)
        source, gather = result["arrays"]
        self.assertEqual((source["reads"], source["writes"]), (80, 16))
        self.assertEqual((gather["reads"], gather["writes"]), (165, 245))
        self.assertAlmostEqual(source["dynamic_energy_pj"], 11_200.0)
        self.assertAlmostEqual(gather["dynamic_energy_pj"], 147_500.0)
        self.assertAlmostEqual(result["leakage_energy_pj"], 32.0)
        self.assertAlmostEqual(result["projected_asic_sram_area_mm2"], 16.0)

    def test_rejects_wrong_profile_or_unclosed_gather(self) -> None:
        activity = {
            "edge_lanes": 4,
            "gather_banks": 8,
            "partition_vertices": 65_536,
        }
        with self.assertRaisesRegex(MatchedEnergyError, "8-lane"):
            grasu_selected_array_energy(activity, {}, runtime_ns=1.0)


if __name__ == "__main__":
    unittest.main()
