from __future__ import annotations

import unittest

from scripts.package_current_fpga_fig10_v15 import (
    mechanism_admission_rows,
    select_breakdown_rows,
)


class PackageCurrentFPGAFig10V15Tests(unittest.TestCase):
    def test_breakdown_rejects_structure_only_row(self) -> None:
        rows = []
        for _group, entries in (
            ("SI", (("AU", "current_fpga_v12_au_weighted_sssp_u8"), ("SU", "current_fpga_v12_su_weighted_sssp_u8"), ("WK", "current_fpga_v12_wk_weighted_sssp_u8"))),
            ("Carry", (("L1", "rq3_trace_carry_l1_e8"), ("L3", "rq3_trace_carry_l3_e8"), ("L5", "rq3_trace_carry_l5_e8"))),
            ("Del", (("Syn", "current_fpga_v12_delete_fallback_sssp"),)),
        ):
            for _tick, execution_id in entries:
                rows.append(
                    {
                        "execution_id": execution_id,
                        "algorithm": "weighted_sssp",
                        "timing_admission": "CALIBRATED_COMPONENT_ENVELOPE",
                    }
                )
        rows[0]["timing_admission"] = "STRUCTURE_ONLY"
        with self.assertRaisesRegex(ValueError, "unadmitted"):
            select_breakdown_rows(rows)

    def test_mechanism_admission_requires_three_holdout_points(self) -> None:
        rows = []
        mechanisms = (
            "sort_frontend",
            "carry",
            "directory",
            "physical_resolve_apply",
            "seed",
            "switch",
            "drain",
        )
        for mechanism in mechanisms:
            rows.extend(
                (
                    {
                        "role": "all",
                        "mechanism": mechanism,
                        "samples": "5",
                        "r2": "0.99",
                        "slope": "1",
                        "intercept": "0",
                    },
                    {
                        "role": "trace_holdout",
                        "mechanism": mechanism,
                        "samples": "2" if mechanism == "carry" else "4",
                        "r2": "1.0" if mechanism == "carry" else "0.95",
                        "slope": "1",
                        "intercept": "0",
                    },
                )
            )
        admitted = {row["mechanism"]: row["status"] for row in mechanism_admission_rows(rows)}
        self.assertEqual(admitted["carry"], "LIMITED_TWO_POINT_HOLDOUT")
        self.assertEqual(admitted["seed"], "SUPPORTED_HOLDOUT_CORRELATION")


if __name__ == "__main__":
    unittest.main()
