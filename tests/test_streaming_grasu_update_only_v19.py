import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "run_streaming_grasu_update_only_v19",
    ROOT / "scripts/run_streaming_grasu_update_only_v19.py",
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class StreamingGrasuUpdateOnlyV19Test(unittest.TestCase):
    def test_slice_metadata_is_streaming_and_validates_records(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "case.slice"
            path.write_text(
                "# spine_real_slice_version=1\n"
                "# case=unit\n"
                "# vertices=4\n"
                "# columns=src dst weight diff\n"
                "0 1 7 1\n2 3 5 -1\n",
                encoding="ascii",
            )
            self.assertEqual(MODULE.slice_metadata(path), ("unit", 4, 2))

    def test_profile_environment_uses_frozen_k4_shared_geometry(self) -> None:
        profile = json.loads(
            (
                ROOT
                / "configs/architectures/grasu_regraph_sharded_k4_cc_hls_v8.json"
            ).read_text(encoding="ascii")
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            environment, binding, stride = MODULE.profile_environment(
                profile,
                algorithm="connected_components",
                workload=output / "initial.slice",
                update_workload=output / "update.slice",
                result_path=output / "result.json",
                dram_dir=output / "dram",
                progress_path=output / "progress.json",
                source_vertex=0,
                vertices=4_847_571,
                max_cycles=1000,
            )
        self.assertEqual(environment["GRASU_SST_COMPUTE_PIPELINES"], "4")
        self.assertEqual(environment["GRASU_SST_SHARED_DOWNSTREAM"], "1")
        self.assertEqual(environment["GRASU_SST_SHARDED_RUNTIME_PLACEMENT"], "1")
        self.assertEqual(environment["GRASU_SST_UPDATE_ONLY"], "1")
        self.assertEqual(stride, 19_398_656)
        self.assertIn(30, binding["instantiated_channels"])

    def test_result_gate_requires_all_correctness_and_memory_ledgers(self) -> None:
        result = {
            "success": True,
            "mode": "grasu_regraph_hls_weighted_sssp",
            "measurement_window": "pure_update_only",
            "pipeline_order": "update_only_no_regraph_compute",
            "conversion_cost_included": False,
            "logical_updates": 8,
            "physical_updates": 8,
            "update_cycles": 42,
            "compute_cycles": 0,
            "update_state_match": True,
            "memory_locality_ledger_match": True,
            "correctness_mismatches": 0,
            "architecture_correctness_mismatches": 0,
            "mathematical_correctness_mismatches": 0,
            "update_observability": {
                "updates": 8,
                "destination_partitions_touched": 2,
            },
        }
        checks = MODULE.validate_result(
            result, algorithm="weighted_sssp", update_records=8
        )
        self.assertTrue(all(checks.values()))
        result["memory_locality_ledger_match"] = False
        self.assertFalse(
            MODULE.validate_result(
                result, algorithm="weighted_sssp", update_records=8
            )["memory_ledger"]
        )


if __name__ == "__main__":
    unittest.main()
