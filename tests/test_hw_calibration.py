from __future__ import annotations

import unittest

from spine_cycle_sim.calibration import (
    aggregate_rows,
    analyze_summary,
    build_hw_command,
    default_matrix,
    parse_hw_maintenance_output,
)
from spine_cycle_sim.calibration.maintenance import ExperimentSpec


class HwMaintenanceCalibrationTests(unittest.TestCase):
    def test_parse_measure_carry_stdout(self) -> None:
        stdout = """
PARTITIONED_CSR_E2E_MEASURE_CARRY_COUNTERS target_level=1 cold_page_ids_written=16 hot_page_ids_written=0 cold_validation_failures=0 hot_validation_failures=0 cold_pages_visited=16 hot_pages_visited=0 cold_bits_inspected=4096 hot_bits_inspected=0 cold_rows_entered=16 hot_rows_entered=0 cold_payload_reads=1024 hot_payload_reads=0 cold_refill_stalls=4176 hot_refill_stalls=0 cold_merge_inputs=2048 hot_merge_inputs=0 cold_outputs=2048 hot_outputs=0
PARTITIONED_CSR_E2E_MEASURE_CARRY PASS target_level=1 batch_edges=1024 source_count=64 preloaded_edges=1024 persisted=2048 maint_ms=21.1603 timeout_s=120 errors=0
"""
        parsed = parse_hw_maintenance_output(stdout)

        self.assertEqual(parsed["mode"], "carry")
        self.assertEqual(parsed["path"], "cascade")
        self.assertEqual(parsed["status"], "PASS")
        self.assertEqual(parsed["target_level"], 1)
        self.assertEqual(parsed["batch_edges"], 1024)
        self.assertEqual(parsed["source_count"], 64)
        self.assertEqual(parsed["cold_page_ids_written"], 16)
        self.assertEqual(parsed["cold_refill_stalls"], 4176)
        self.assertAlmostEqual(parsed["maint_ms"], 21.1603)

    def test_parse_l0_store_stdout(self) -> None:
        stdout = """
PARTITIONED_CSR_E2E_BATCH case=star batch=1 input_edges=1024 target_level=0 consumed_mask=0 persisted=1024 overflow=0 l0_partitions_written=16 l0_pages_epoch_stamped=16 maint_ms=27.6916
"""
        parsed = parse_hw_maintenance_output(stdout)

        self.assertEqual(parsed["mode"], "l0_store")
        self.assertEqual(parsed["path"], "store_l0")
        self.assertEqual(parsed["status"], "PASS")
        self.assertEqual(parsed["host_case"], "star")
        self.assertNotIn("case", parsed)
        self.assertEqual(parsed["target_level"], 0)
        self.assertEqual(parsed["persisted"], 1024)
        self.assertEqual(parsed["l0_pages_epoch_stamped"], 16)

    def test_aggregate_rows_uses_successful_median(self) -> None:
        rows = []
        for repeat, maint_ms in enumerate([3.0, 1.0, 2.0], start=1):
            rows.append(
                {
                    "case": "carry_l1_batch_e1024_s64",
                    "sweep": "l1_batch_edges",
                    "mode": "carry",
                    "target_level": 1,
                    "batch_edges": 1024,
                    "source_count": 64,
                    "expected_path": "cascade",
                    "repeat": repeat,
                    "returncode": 0,
                    "status": "PASS",
                    "maint_ms": maint_ms,
                    "cold_payload_reads": 1024,
                }
            )
        summary = aggregate_rows(rows, freq_mhz=134.0)

        self.assertEqual(len(summary), 1)
        self.assertEqual(summary[0]["successful_repeats"], 3)
        self.assertEqual(summary[0]["median_maint_ms"], 2.0)
        self.assertEqual(summary[0]["median_hw_cycles"], 268_000.0)
        self.assertEqual(summary[0]["cold_payload_reads_median"], 1024)

    def test_default_matrix_matches_phase2b_sweeps(self) -> None:
        specs = default_matrix()
        sweeps = {spec.sweep for spec in specs}

        self.assertEqual(len(specs), 19)
        self.assertEqual(
            sweeps,
            {"l0_store", "l1_batch_edges", "source_count", "target_level"},
        )
        self.assertEqual(sum(1 for spec in specs if spec.sweep == "l0_store"), 6)
        self.assertEqual(sum(1 for spec in specs if spec.sweep == "l1_batch_edges"), 5)
        self.assertEqual(sum(1 for spec in specs if spec.sweep == "source_count"), 5)
        self.assertEqual(sum(1 for spec in specs if spec.sweep == "target_level"), 3)
        source_sweep = [spec for spec in specs if spec.sweep == "source_count"]
        self.assertTrue(all(spec.target_level == 9 for spec in source_sweep))
        self.assertTrue(all(spec.batch_edges == 128 for spec in source_sweep))

    def test_build_hw_command_sets_split_runtime_environment(self) -> None:
        spec = ExperimentSpec(
            case="carry_l1_batch_e1024_s64",
            sweep="l1_batch_edges",
            mode="carry",
            args=("--measure-carry", "1", "1024", "64"),
            target_level=1,
            batch_edges=1024,
            source_count=64,
            expected_path="cascade",
        )
        command = build_hw_command(
            spec,
            host_exe="/tmp/host_partitioned_csr_e2e_smoke",
            xclbin="/tmp/spine.hw.xclbin",
            timeout_s=120,
            xrt_setup="/opt/xilinx/xrt/setup.sh",
            split_kernels=True,
        )

        self.assertIn("source /opt/xilinx/xrt/setup.sh", command)
        self.assertIn("unset XCL_EMULATION_MODE", command)
        self.assertIn("export SPINE_PARTITIONED_SPLIT=1", command)
        self.assertIn("--measure-carry 1 1024 64 --timeout 120", command)

    def test_analyze_summary_returns_regression_sections(self) -> None:
        rows = aggregate_rows(
            [
                {
                    "case": "a",
                    "sweep": "l0_store",
                    "mode": "l0_store",
                    "target_level": 0,
                    "batch_edges": 256,
                    "source_count": 1,
                    "repeat": 1,
                    "returncode": 0,
                    "status": "PASS",
                    "maint_ms": 1.0,
                    "persisted": 256,
                },
                {
                    "case": "b",
                    "sweep": "l0_store",
                    "mode": "l0_store",
                    "target_level": 0,
                    "batch_edges": 512,
                    "source_count": 1,
                    "repeat": 1,
                    "returncode": 0,
                    "status": "PASS",
                    "maint_ms": 2.0,
                    "persisted": 512,
                },
            ],
            freq_mhz=134.0,
        )
        analysis = analyze_summary(rows)

        self.assertEqual(analysis["row_count"], 2)
        self.assertIn("univariate", analysis)
        self.assertIn("ridge", analysis)


if __name__ == "__main__":
    unittest.main()
