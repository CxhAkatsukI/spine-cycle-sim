from __future__ import annotations

import unittest

from spine_cycle_sim.evidence.component_power import (
    ComponentPowerError,
    aggregate_vivado_component_power,
    analyze_component_power_manifest,
)
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _ledger(children: list[tuple[str, float]], *, ulp: float) -> dict[str, object]:
    return {
        "status": "PASS",
        "summary": {
            "confidence_level": "Low",
            "dynamic_w": ulp + 2.0,
            "device_static_w": 1.0,
        },
        "hierarchy": [
            {"name": "level0_wrapper", "indent": 0, "power_w": ulp + 2.0},
            {"name": "ulp", "indent": 5, "power_w": ulp},
            *(
                {"name": name, "indent": 7, "power_w": power}
                for name, power in children
            ),
        ],
    }


class ComponentPowerTests(unittest.TestCase):
    def test_spine_categories_close_ulp(self) -> None:
        result = aggregate_vivado_component_power(
            _ledger(
                [
                    ("hmss_0", 5.0),
                    ("spine_partconv_rdmaint_kernel_1", 2.0),
                    ("spine_partconv_compute_kernel_1", 1.0),
                    ("buffer_edge", 0.5),
                    ("ulp_ucs", 1.5),
                ],
                ulp=10.0,
            ),
            system="spine",
        )
        self.assertEqual(result["components_w"]["hbm_subsystem"], 5.0)
        self.assertEqual(result["components_w"]["update_maintenance"], 2.0)
        self.assertEqual(result["components_w"]["other_user_logic"], 1.5)
        self.assertEqual(result["platform_dynamic_residual_w"], 2.0)

    def test_grasu_categories_separate_update_and_compute(self) -> None:
        result = aggregate_vivado_component_power(
            _ledger(
                [
                    ("hmss_0", 4.0),
                    ("bin_search_1", 1.0),
                    ("pma_to_regraph_adapter_1", 1.0),
                    ("pr_source_1", 2.0),
                    ("regraph_pagerank_apply_1", 1.5),
                    ("buffer_axis", 0.25),
                    ("ulp_cmp", 0.25),
                ],
                ulp=10.0,
            ),
            system="grasu_regraph",
        )
        self.assertEqual(result["components_w"]["update_maintenance"], 2.0)
        self.assertEqual(result["components_w"]["graph_compute"], 3.5)

    def test_rejects_open_hierarchy_ledger(self) -> None:
        with self.assertRaisesRegex(ComponentPowerError, "does not close"):
            aggregate_vivado_component_power(
                _ledger([("hmss_0", 1.0)], ulp=3.0), system="spine"
            )

    def test_repository_manifest_closes_all_four_builds(self) -> None:
        result = analyze_component_power_manifest(
            ROOT / "configs/evidence/candidate10_vivado_component_power_v1.json"
        )
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(len(result["builds"]), 4)


if __name__ == "__main__":
    unittest.main()
