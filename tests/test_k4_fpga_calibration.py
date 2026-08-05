from __future__ import annotations

import csv
import dataclasses
import json
from pathlib import Path
import tempfile
import unittest

from spine_cycle_sim.calibration.k4_fpga import (
    K4CaseSpec,
    K4MicrobenchSpec,
    K4TimingRecord,
    fit_k4_event_scale,
    fit_k4_fullpr_component_model,
    k4_component_prediction_rows,
    k4_group_summary,
    k4_prediction_rows,
    load_k4_microbench_records,
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
                    "shared_regraph_pipelines=1 conversion_cost=absent\n",
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
                        "vertices": 10,
                        "compute_pma_slots": 32 * supersteps,
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

    def test_reads_cc_sibling_result_and_superstep_protocol(self) -> None:
        for summary in self.summaries:
            with summary.open(encoding="utf-8") as source:
                rows = list(csv.DictReader(source, delimiter="\t"))
            for row in rows:
                row["algorithm"] = "connected_components"
            with summary.open("w", encoding="utf-8", newline="") as sink:
                writer = csv.DictWriter(sink, fieldnames=list(rows[0]), delimiter="\t")
                writer.writeheader()
                writer.writerows(rows)

        cc_specs = []
        for spec, rounds in zip(self.specs, (2, 3, 4)):
            manifest = self.root / f"cc_{spec.case}" / "run_manifest.json"
            manifest.parent.mkdir()
            manifest.write_text(
                json.dumps({"status": "PASS", "admitted": True}),
                encoding="utf-8",
            )
            result = json.loads(spec.simulation_manifest.read_text(encoding="utf-8"))["result"]
            result.pop("supersteps")
            result["iterations"] = rounds
            (manifest.parent / "result.json").write_text(
                json.dumps(result), encoding="utf-8"
            )
            cc_specs.append(dataclasses.replace(spec, simulation_manifest=manifest))
        records = load_k4_timing_records(self.summaries, cc_specs)
        self.assertEqual([record.supersteps for record in records], [2, 3, 4])

    def test_full_pagerank_uses_pipeline_executions(self) -> None:
        for summary in self.summaries:
            with summary.open(encoding="utf-8") as source:
                rows = list(csv.DictReader(source, delimiter="\t"))
            for row in rows:
                row["algorithm"] = "full_pagerank"
                log = summary.parent / row["case"] / "grasu_regraph" / "run.log"
                rounds = {"cal_a": 2, "cal_b": 3, "hold": 4}[row["case"]]
                log.write_text(
                    "FULL_PR_PMA_NATIVE_RESULT status=PASS rank_mismatches=0 "
                    "degree_mismatches=0 conversion_cost=absent "
                    f"pipeline_executions={rounds} rounds={rounds} "
                    "vertices=10 pma_slots_per_partition_pass=32 "
                    "destination_partitions=1 shared_regraph_pipelines=1\n",
                    encoding="utf-8",
                )
            with summary.open("w", encoding="utf-8", newline="") as sink:
                writer = csv.DictWriter(sink, fieldnames=list(rows[0]), delimiter="\t")
                writer.writeheader()
                writer.writerows(rows)
        pr_specs = []
        for spec, rounds in zip(self.specs, (2, 3, 4)):
            payload = json.loads(spec.simulation_manifest.read_text(encoding="utf-8"))
            payload["result"].pop("supersteps")
            payload["result"]["iterations"] = rounds
            spec.simulation_manifest.write_text(json.dumps(payload), encoding="utf-8")
            pr_specs.append(spec)
        records = load_k4_timing_records(self.summaries, pr_specs)
        self.assertEqual([record.supersteps for record in records], [2, 3, 4])

    def test_residual_pagerank_uses_correction_plus_propagation(self) -> None:
        for summary in self.summaries:
            with summary.open(encoding="utf-8") as source:
                rows = list(csv.DictReader(source, delimiter="\t"))
            for row in rows:
                row["algorithm"] = "residual_pagerank"
                log = summary.parent / row["case"] / "grasu_regraph" / "run.log"
                propagation = {"cal_a": 2, "cal_b": 3, "hold": 4}[row["case"]]
                log.write_text(
                    "RESIDUAL_PR_PMA_NATIVE_RESULT status=PASS rank_mismatches=0 "
                    "degree_mismatches=0 conversion_cost=absent "
                    f"pipeline_executions={propagation + 1} "
                    f"propagation_rounds={propagation} "
                    "destination_partitions=1 shared_regraph_pipelines=1\n",
                    encoding="utf-8",
                )
            with summary.open("w", encoding="utf-8", newline="") as sink:
                writer = csv.DictWriter(sink, fieldnames=list(rows[0]), delimiter="\t")
                writer.writeheader()
                writer.writerows(rows)
        residual_specs = []
        for spec, propagation in zip(self.specs, (2, 3, 4)):
            payload = json.loads(spec.simulation_manifest.read_text(encoding="utf-8"))
            payload["result"].pop("supersteps")
            payload["result"]["iterations"] = propagation
            payload["result"]["pipeline_executions"] = propagation + 1
            spec.simulation_manifest.write_text(json.dumps(payload), encoding="utf-8")
            residual_specs.append(spec)
        records = load_k4_timing_records(self.summaries, residual_specs)
        self.assertEqual([record.supersteps for record in records], [3, 4, 5])

    def test_fullpr_component_fit_preserves_holdout(self) -> None:
        def record(case: str, role: str, vertices: int, slots: int) -> K4TimingRecord:
            hardware_cycles = 1000.0 + 2.0 * vertices + 3.0 * slots
            return K4TimingRecord(
                case=case,
                role=role,
                algorithm="full_pagerank",
                graph=f"{case}.graph",
                simulation_manifest=f"{case}.json",
                simulation_cycles=hardware_cycles / 2.0,
                hardware_event_ms=hardware_cycles / 150_000.0,
                hardware_cycles=hardware_cycles,
                hardware_samples=3,
                hardware_cv_pct=0.0,
                supersteps=3,
                destination_partitions=1,
                vertices=vertices,
                executed_pma_slots=slots,
            )

        records = [
            record("cal_a", "calibration", 10, 100),
            record("cal_b", "calibration", 20, 100),
            record("cal_c", "calibration", 10, 200),
            record("hold", "holdout", 15, 150),
        ]
        model = fit_k4_fullpr_component_model(records)
        self.assertAlmostEqual(model.fixed_cycles, 1000.0)
        self.assertAlmostEqual(model.vertex_cycles, 2.0)
        self.assertAlmostEqual(model.pma_slot_cycles, 3.0)
        rows = k4_component_prediction_rows(records, model)
        self.assertAlmostEqual(rows[-1]["calibrated_absolute_error_pct"], 0.0)

        poisoned = [
            dataclasses.replace(
                row,
                hardware_cycles=row.hardware_cycles * 1000.0,
                hardware_event_ms=row.hardware_event_ms * 1000.0,
            )
            if row.role == "holdout"
            else row
            for row in records
        ]
        self.assertEqual(fit_k4_fullpr_component_model(poisoned), model)

    def test_loads_fullpr_microbenchmark_realized_work(self) -> None:
        manifest = self.root / "micro" / "manifest.json"
        manifest.parent.mkdir()
        manifest.write_text(
            json.dumps(
                {
                    "status": "PASS",
                    "result": {
                        "success": True,
                        "core_mhz": 150.0,
                        "cycles": 100.0,
                        "iterations": 3,
                        "vertices": 64,
                        "destination_partitions": 1,
                        "compute_pma_slots": 3024,
                        "correctness_mismatches": 0,
                        "architecture_correctness_mismatches": 0,
                        "mathematical_correctness_mismatches": 0,
                        "conversion_cost_included": False,
                    },
                }
            ),
            encoding="utf-8",
        )
        run_dir = self.root / "micro_hw"
        run_dir.mkdir()
        with (run_dir / "summary.tsv").open(
            "w", encoding="utf-8", newline=""
        ) as sink:
            writer = csv.DictWriter(
                sink,
                fieldnames=(
                    "algorithm",
                    "status",
                    "result_line",
                    "timing_line",
                ),
                delimiter="\t",
            )
            writer.writeheader()
            writer.writerow(
                {
                    "algorithm": "full_pagerank",
                    "status": "PASS",
                    "result_line": (
                        "RESULT status=PASS rank_mismatches=0 degree_mismatches=0 "
                        "pipeline_executions=3 rounds=3 vertices=64 "
                        "destination_partitions=1 shared_regraph_pipelines=1 "
                        "pma_slots_per_partition_pass=1008 conversion_cost=absent"
                    ),
                    "timing_line": "TIMING device_e2e_ms=2.0",
                }
            )
        records = load_k4_microbench_records(
            [K4MicrobenchSpec("micro", "calibration", manifest, run_dir)]
        )
        self.assertEqual(records[0].vertices, 64)
        self.assertEqual(records[0].executed_pma_slots, 3024)


if __name__ == "__main__":
    unittest.main()
