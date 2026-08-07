from __future__ import annotations

import unittest

from spine_cycle_sim.evidence.matched_energy import MatchedEnergyError
from spine_cycle_sim.evidence.weighted_energy import subtract_detailed_dram


def _dram(scale: int) -> dict[str, object]:
    return {
        "controller_instances": 32,
        "controller_cycles_min": 100 * scale,
        "controller_cycles_max": 100 * scale,
        "reads": 10 * scale,
        "writes": 5 * scale,
        "read_row_hits": 4 * scale,
        "write_row_hits": 2 * scale,
        "activates": 3 * scale,
        "precharges": 2 * scale,
        "activate_energy_pj": 30.0 * scale,
        "read_energy_pj": 20.0 * scale,
        "write_energy_pj": 10.0 * scale,
        "refresh_energy_pj": 4.0 * scale,
        "active_standby_energy_pj": 3.0 * scale,
        "precharge_standby_energy_pj": 2.0 * scale,
        "self_refresh_energy_pj": 1.0 * scale,
        "total_energy_pj": 70.0 * scale,
    }


class WeightedEnergyTest(unittest.TestCase):
    def test_exact_prefix_subtraction_closes_components(self) -> None:
        result = subtract_detailed_dram(_dram(3), _dram(1))
        self.assertEqual(result["reads"], 20)
        self.assertEqual(result["controller_cycles_min"], 200)
        self.assertAlmostEqual(result["command_dynamic_energy_pj"], 120.0)
        self.assertAlmostEqual(
            result["background_and_refresh_energy_pj"], 20.0
        )
        self.assertAlmostEqual(result["total_energy_pj"], 140.0)

    def test_rejects_non_32_controller_or_negative_prefix(self) -> None:
        cumulative = _dram(2)
        cumulative["controller_instances"] = 4
        with self.assertRaisesRegex(MatchedEnergyError, "32 controllers"):
            subtract_detailed_dram(cumulative, _dram(1))
        with self.assertRaisesRegex(MatchedEnergyError, "prefix exceeds"):
            subtract_detailed_dram(_dram(1), _dram(2))


if __name__ == "__main__":
    unittest.main()
