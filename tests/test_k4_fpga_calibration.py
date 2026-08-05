from __future__ import annotations

import csv
import dataclasses
import json
from pathlib import Path
import tempfile
import unittest

from spine_cycle_sim.calibration.k4_fpga import (
    K4CaseSpec,
    fit_k4_event_scale,
    k4_group_summary,
    k4_prediction_rows,
    load_k4_timing_records,
)


class K4FpgaCalibrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.summaries = [self._summary(index) for index in range(3)]
        self.specs = [
            self._spec("cal_a", "calibration", 100.0, 2),
            self._spec("cal_b", "calibration", 200.0, 3),
            self._spec("hold", "holdout", 300.0, 4),
        ]

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _summary(self, repeat: int) -> Path:
        path = self.root / f"repeat{repeat}" / "summary.tsv"
        path.parent.mkdir(parents=True)
        fields = [
            "case", "algorithm", "graph", "gr_status", "spine_status",
            "comparison_status", "gr_event_e2e_ms",
        ]
        with path.open("w", encoding="utf-8", newline="") as sink:
            writer = csv.DictWriter(sink, fieldnames=fields, delimiter="\t")
            writer.writeheader()
            for case, base in (("cal_a", 2.0), ("cal_b", 4.0), ("hold", 6.0)):
                writer.writerow(
                    {
                        "case": case,
                        "algorithm": "weighted_sssp",
                        "graph": f"{case}.graph",
                        "gr_status": "PASS",
                        "spine_status": "PASS",
                        "comparison_status": "ADMITTED",
                        "gr_event_e2e_ms": base + (repeat - 1) * 0.1,
                    }
                )
                log = path.parent / case / "grasu_regraph" / "run.log"
                log.parent.mkdir(parents=True)
                supersteps = {"cal_a": 2, "cal_b": 3, "hold": 4}[case]
                log.write_text(
                    "WEIGHTED_PMA_NATIVE_RESULT status=PASS mismatches=0 "
                    f"executed_supersteps={supersteps} destination_partitions=1 "
                    "conversion_cost=absent\n",
                    encoding="utf-8",
                )
        return path

    def _spec(
        self, case: str, role: str, simulation_cycles: float, supersteps: int
    ) -> K4CaseSpec:
        path = self.root / f"{case}.json"
        path.write_text(
            json.dumps(
                {
                    "status": "PASS",
                    "result": {
                        "success": True,
                        "core_mhz": 150.0,
                        "cycles": simulation_cycles,
                        "supersteps": supersteps,
                        "correctness_mismatches": 0,
                        "architecture_correctness_mismatches": 0,
                        "mathematical_correctness_mismatches": 0,
                        "conversion_cost_included": False,
                    },
                }
            ),
            encoding="utf-8",
        )
        return K4CaseSpec(case, role, path)

    def test_load_fit_and_holdout(self) -> None:
        records = load_k4_timing_records(self.summaries, self.specs)
        model = fit_k4_event_scale(records)
        rows = k4_prediction_rows(records, model)
        summary = k4_group_summary(rows)
        self.assertEqual(len(records), 3)
        self.assertEqual(model.calibration_cases, ("cal_a", "cal_b"))
        self.assertAlmostEqual(model.scale, 3000.0)
        self.assertAlmostEqual(
            next(row for row in summary if row["role"] == "holdout")[
                "calibrated_max_absolute_error_pct"
            ],
            0.0,
        )

    def test_holdout_cannot_change_fit(self) -> None:
        records = load_k4_timing_records(self.summaries, self.specs)
        baseline = fit_k4_event_scale(records)
        poisoned = [
            dataclasses.replace(
                row,
                hardware_cycles=row.hardware_cycles * 1000,
                hardware_event_ms=row.hardware_event_ms * 1000,
            )
            if row.role == "holdout"
            else row
            for row in records
        ]
        self.assertEqual(fit_k4_event_scale(poisoned).scale, baseline.scale)

    def test_rejects_round_mismatch(self) -> None:
        bad = dataclasses.replace(self.specs[-1], simulation_manifest=self.specs[0].simulation_manifest)
        with self.assertRaises(ValueError):
            load_k4_timing_records(self.summaries, [*self.specs[:-1], bad])

    def test_rejects_failed_hardware_row(self) -> None:
        text = self.summaries[0].read_text(encoding="utf-8")
        self.summaries[0].write_text(text.replace("ADMITTED", "REJECTED", 1), encoding="utf-8")
        with self.assertRaises(ValueError):
            load_k4_timing_records(self.summaries, self.specs)


if __name__ == "__main__":
    unittest.main()
