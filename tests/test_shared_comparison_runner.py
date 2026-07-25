from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from spine_cycle_sim.experiments.comparison import (
    RunInvocation,
    build_invocation,
    implementation_fingerprint,
    pair_rows,
    select_runs,
    validate_system_result,
)
from scripts.run_shared_comparison_matrix import ProcessRegistry
from spine_cycle_sim.experiments.shared_workloads import (
    validate_shared_comparison_manifest,
)


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = (
    ROOT / "configs" / "experiments" / "shared_comparison_workloads_20260725.json"
)


class SharedComparisonRunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = validate_shared_comparison_manifest(ROOT, MANIFEST)

    def test_selection_is_deterministic_and_filterable(self) -> None:
        runs = select_runs(
            self.manifest,
            roles=("holdout",),
            algorithms=("full_pagerank",),
        )
        self.assertEqual(len(runs), 10)
        self.assertTrue(all(run["role"] == "holdout" for run in runs))

    def test_dynamic_commands_preserve_identical_graph_and_update(self) -> None:
        run = next(
            run
            for run in self.manifest["runs"]
            if run["scenario"] == "full_rebuild_increase"
        )
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            output = Path(tmp)
            spine = build_invocation(
                ROOT,
                run,
                system="spine",
                output_root=output,
                python="python3",
                sst=Path("/data/feiyang/sst/bin/sst"),
                lib_dir=ROOT / "build" / "sst",
                spine_profile=ROOT
                / "configs"
                / "architectures"
                / "spine_latest_afb8199.json",
            )
            grasu = build_invocation(
                ROOT,
                run,
                system="grasu_regraph",
                output_root=output,
                python="python3",
                sst=Path("/data/feiyang/sst/bin/sst"),
                lib_dir=ROOT / "build" / "sst",
                spine_profile=ROOT
                / "configs"
                / "architectures"
                / "spine_latest_afb8199.json",
            )
        self.assertIn("dynamic_sssp_increase", spine.command)
        self.assertEqual(
            spine.command[spine.command.index("--workload") + 1],
            grasu.command[grasu.command.index("--workload") + 1],
        )
        self.assertEqual(
            spine.command[spine.command.index("--update-workload") + 1],
            grasu.command[grasu.command.index("--update-workload") + 1],
        )
        self.assertIn("--profile", grasu.command)

    def test_implementation_fingerprint_changes_with_binary(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            first = Path(tmp) / "first"
            second = Path(tmp) / "second"
            first.write_bytes(b"simulator-v1")
            second.write_bytes(b"profile-v1")
            before = implementation_fingerprint([first, second])
            first.write_bytes(b"simulator-v2")
            after = implementation_fingerprint([first, second])
        self.assertNotEqual(before["sha256"], after["sha256"])
        self.assertEqual(len(before["files"]), 2)

    def test_process_registry_preserves_first_failure(self) -> None:
        registry = ProcessRegistry()
        first = RunInvocation("first", "spine", (), ROOT)
        second = RunInvocation("second", "grasu_regraph", (), ROOT)
        registry.record_failure(first, RuntimeError("root cause"))
        registry.record_failure(second, RuntimeError("shutdown noise"))
        self.assertTrue(registry.stopping)
        self.assertEqual(
            registry.failure,
            {
                "run_id": "first",
                "system": "spine",
                "error_type": "RuntimeError",
                "message": "root cause",
            },
        )

    def test_parent_gate_rejects_wrong_clock_or_oracle(self) -> None:
        run = next(
            run
            for run in self.manifest["runs"]
            if run["algorithm"] == "full_pagerank"
        )
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            invocation = build_invocation(
                ROOT,
                run,
                system="spine",
                output_root=Path(tmp),
                python="python3",
                sst=Path("/data/feiyang/sst/bin/sst"),
                lib_dir=ROOT / "build" / "sst",
                spine_profile=ROOT
                / "configs"
                / "architectures"
                / "spine_latest_afb8199.json",
            )
        result = {
            "success": True,
            "correctness_mismatches": 0,
            "architecture_correctness_mismatches": 0,
            "mathematical_correctness_mismatches": 0,
            "architecture_oracle": "iterative_float32",
            "mathematical_oracle": "wrong",
            "core_mhz": 141.0,
            "vertices": run["graph"]["vertices"],
            "input_edges": run["graph"]["records"],
            "backend_requests": 7,
        }
        dram = {"channels": 32, "reads": 5, "writes": 2}
        binding = {
            "physical_channels": 32,
            "reachable_channels": list(range(32)),
            "instantiated_channels": list(range(32)),
            "channel_numbers_preserved": True,
            "unbound_request_policy": "fatal",
            "dram_energy_claim": "all_physical_channel_dramsim3",
        }
        self.assertEqual(
            set(validate_system_result(run, invocation, result, dram, binding)),
            {"mathematical_oracle", "clock"},
        )

    def test_pairing_requires_same_clock_and_reports_labeled_speedup(self) -> None:
        base = {
            "run_id": "case",
            "fixture_id": "fixture",
            "dataset_kind": "synthetic",
            "role": "holdout",
            "algorithm": "weighted_sssp",
            "core_mhz": 150.0,
            "simulated_ms": 0.001,
        }
        pairs = pair_rows(
            [
                {**base, "system": "spine", "cycles": 100},
                {**base, "system": "grasu_regraph", "cycles": 250},
            ]
        )
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0]["spine_speedup_over_grasu"], 2.5)
        self.assertEqual(
            pairs[0]["claim_label"], "normalized_structural_execution_driven"
        )


if __name__ == "__main__":
    unittest.main()
