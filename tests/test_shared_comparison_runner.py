from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from spine_cycle_sim.experiments.comparison import (
    RunInvocation,
    build_invocation,
    implementation_fingerprint,
    normalized_grasu_profile_paths,
    pair_rows,
    select_runs,
    validate_normalized_profile_contract,
    validate_system_result,
)
from scripts.run_shared_comparison_matrix import (
    DEFAULT_DRAM_CONFIG,
    FROZEN_DRAM_CONFIG_SHA256,
    ProcessRegistry,
    hbm_config_contract,
)
from spine_cycle_sim.experiments.shared_workloads import (
    validate_shared_comparison_manifest,
)


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = (
    ROOT
    / "configs"
    / "experiments"
    / "shared_comparison_candidate10_v2_20260726.json"
)
SPINE_PROFILE = (
    ROOT / "configs" / "architectures" / "spine_candidate10_normalized_v1.json"
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
                / "spine_candidate10_normalized_v1.json",
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
                / "spine_candidate10_normalized_v1.json",
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

    def test_hbm_config_contract_labels_baseline_and_sensitivity(self) -> None:
        baseline = hbm_config_contract(DEFAULT_DRAM_CONFIG)
        self.assertTrue(baseline["is_frozen_baseline"])
        self.assertEqual(baseline["sha256"], FROZEN_DRAM_CONFIG_SHA256)
        self.assertEqual(
            baseline["shared_by_systems"], ["spine", "grasu_regraph"]
        )
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            sensitivity_path = Path(tmp) / "sensitivity.ini"
            sensitivity_path.write_bytes(
                DEFAULT_DRAM_CONFIG.read_bytes() + b"\n; sensitivity\n"
            )
            sensitivity = hbm_config_contract(sensitivity_path)
            self.assertFalse(sensitivity["is_frozen_baseline"])
            self.assertEqual(sensitivity["experiment_role"], "hbm_sensitivity")
            with self.assertRaisesRegex(ValueError, "missing"):
                hbm_config_contract(Path(tmp) / "missing.ini")

    def test_normalized_contract_accepts_only_candidate10_lineage(self) -> None:
        contract = validate_normalized_profile_contract(
            SPINE_PROFILE, normalized_grasu_profile_paths(ROOT)
        )
        self.assertEqual(
            contract["spine_profile_id"], "spine_candidate10_normalized_v1"
        )
        with self.assertRaisesRegex(ValueError, "Candidate10-derived"):
            validate_normalized_profile_contract(
                ROOT / "configs" / "architectures" / "spine_latest_afb8199.json",
                normalized_grasu_profile_paths(ROOT),
            )

    def test_normalized_contract_rejects_silent_candidate10_drift(self) -> None:
        source = json.loads(SPINE_PROFILE.read_text(encoding="ascii"))
        source["parameters"]["tile_vertices"] = 32768
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            profile_dir = Path(tmp)
            candidate = profile_dir / SPINE_PROFILE.name
            parent = profile_dir / "spine_candidate10_one_pass_1e61fc0.json"
            candidate.write_text(json.dumps(source), encoding="ascii")
            parent.write_bytes(
                (
                    ROOT
                    / "configs"
                    / "architectures"
                    / "spine_candidate10_one_pass_1e61fc0.json"
                ).read_bytes()
            )
            with self.assertRaisesRegex(ValueError, "protected Candidate10"):
                validate_normalized_profile_contract(
                    candidate, normalized_grasu_profile_paths(ROOT)
                )

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
                / "spine_candidate10_normalized_v1.json",
            )
        result = {
            "success": True,
            "correctness_mismatches": 0,
            "architecture_correctness_mismatches": 0,
            "mathematical_correctness_mismatches": 0,
            "architecture_oracle": "iterative_float32",
            "mathematical_oracle": "wrong",
            "core_mhz": 141.0,
            "architecture_profile_path": str(invocation.profile_path),
            "architecture_profile_id": invocation.profile_id,
            "architecture_profile_sha256": invocation.profile_sha256,
            "spine_maintenance_architecture": invocation.expected_spine_maintenance,
            "spine_axi_profile": invocation.expected_spine_axi,
            "vertices": run["graph"]["vertices"],
            "input_edges": run["graph"]["records"],
            "backend_requests": 7,
            "maintenance_start_cycle": 2,
            "maintenance_end_cycle": 20,
            "maintenance_first_memory_issue_cycle": 4,
            "maintenance_last_memory_completion_cycle": 17,
            "maintenance_launch_to_first_memory_issue_cycles": 2,
            "maintenance_memory_active_span_cycles": 13,
            "maintenance_post_memory_drain_cycles": 3,
            "maintenance_memory_ledger_closed": True,
            "backend_arbitration": {
                "policy": "registered_round_robin_per_pseudo_channel",
                "unique_intents": 7,
                "grants": 7,
                "consumed_grants": 7,
                "pending_intents": 0,
                "pending_grants": 0,
                "ledger_closed": True,
            },
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
        result["architecture_profile_id"] = "spine_latest_afb8199"
        self.assertIn(
            "profile_id",
            validate_system_result(run, invocation, result, dram, binding),
        )
        result["architecture_profile_id"] = invocation.profile_id
        result["backend_arbitration"]["ledger_closed"] = False
        self.assertIn(
            "registered_arbitration_ledger",
            validate_system_result(run, invocation, result, dram, binding),
        )
        result["backend_arbitration"]["ledger_closed"] = True
        result["maintenance_memory_active_span_cycles"] = 12
        self.assertIn(
            "spine_maintenance_timing_ledger",
            validate_system_result(run, invocation, result, dram, binding),
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
            pairs[0]["claim_label"],
            "candidate10_derived_normalized_structural_execution_driven",
        )


if __name__ == "__main__":
    unittest.main()
