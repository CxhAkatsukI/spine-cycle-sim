from __future__ import annotations

from pathlib import Path
import json
import tempfile
import unittest

from scripts.run_shared_hbm_sensitivity import (
    DEFAULT_CONTRACT,
    collect_profile_evidence,
    load_contract,
    select_profiles,
    summarize_pairs,
)


class SharedHbmSensitivityTests(unittest.TestCase):
    def test_frozen_contract_covers_axes_roles_and_algorithms(self) -> None:
        contract = load_contract(DEFAULT_CONTRACT)
        profiles = contract["resolved_profiles"]
        self.assertEqual(len(profiles), 5)
        self.assertEqual(len(contract["run_ids"]), 12)
        self.assertEqual(
            {(row["axis"], row["direction"]) for row in profiles},
            {
                ("baseline", "baseline"),
                ("latency", "low"),
                ("latency", "high"),
                ("bandwidth", "low"),
                ("bandwidth", "high"),
            },
        )

    def test_summary_reports_cycle_sensitivity_and_strict_inversion(self) -> None:
        base = {
            "run_id": "case",
            "role": "holdout",
            "algorithm": "weighted_sssp",
            "spine_cycles": "100",
            "grasu_regraph_cycles": "200",
            "spine_speedup_over_grasu": "2.0",
        }
        changed = {
            **base,
            "spine_cycles": "400",
            "grasu_regraph_cycles": "220",
            "spine_speedup_over_grasu": "0.55",
        }
        details, groups = summarize_pairs(
            {"baseline": [base], "latency_high": [changed]},
            [
                {"profile_id": "baseline", "axis": "baseline", "direction": "baseline"},
                {"profile_id": "latency_high", "axis": "latency", "direction": "high"},
            ],
            tolerance=1.01,
        )
        self.assertEqual(details[0]["spine_cycle_ratio"], 4.0)
        self.assertEqual(details[0]["grasu_regraph_cycle_ratio"], 1.1)
        self.assertTrue(details[0]["strict_rank_inversion"])
        self.assertEqual(groups[0]["strict_rank_inversions"], 1)

    def test_profile_selection_adds_baseline_and_rejects_unknown(self) -> None:
        profiles = [
            {"profile_id": "baseline"},
            {"profile_id": "latency_low"},
            {"profile_id": "latency_high"},
        ]
        selected = select_profiles(profiles, ["latency_high"])
        self.assertEqual(
            {row["profile_id"] for row in selected},
            {"baseline", "latency_high"},
        )
        with self.assertRaisesRegex(ValueError, "unknown"):
            select_profiles(profiles, ["missing"])

    def test_summary_rejects_profile_coverage_drift(self) -> None:
        baseline = {
            "run_id": "case",
            "spine_cycles": "1",
            "grasu_regraph_cycles": "2",
            "spine_speedup_over_grasu": "2",
        }
        with self.assertRaisesRegex(ValueError, "coverage"):
            summarize_pairs(
                {"baseline": [baseline], "latency_low": []},
                [
                    {"profile_id": "baseline", "axis": "baseline", "direction": "baseline"},
                    {"profile_id": "latency_low", "axis": "latency", "direction": "low"},
                ],
                tolerance=1.01,
            )

    def test_profile_evidence_is_hash_pinned_and_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile_root = root / "baseline"
            profile_root.mkdir()
            manifest = {
                "status": "PASS",
                "failure": None,
                "result_rows": 2,
                "paired_rows": 1,
                "claim_class": "baseline",
                "hbm_dram_config": {
                    "experiment_role": "frozen_baseline",
                    "sha256": "config-sha",
                },
                "simulation_implementation": {"sha256": "simulation-sha"},
            }
            (profile_root / "comparison_manifest.json").write_text(
                json.dumps(manifest), encoding="ascii"
            )
            (profile_root / "results.csv").write_text(
                "system\nspine\ngrasu_regraph\n", encoding="ascii"
            )
            (profile_root / "pairs.csv").write_text(
                "run_id\ncase\n", encoding="ascii"
            )
            rows, digest = collect_profile_evidence(
                root,
                {"baseline": {"sha256": "config-sha"}},
                expected_pairs=1,
            )
            self.assertEqual(rows[0]["simulation_sha256"], "simulation-sha")
            self.assertEqual(len(digest), 64)
            manifest["hbm_dram_config"]["sha256"] = "tampered"
            (profile_root / "comparison_manifest.json").write_text(
                json.dumps(manifest), encoding="ascii"
            )
            with self.assertRaisesRegex(ValueError, "invalid"):
                collect_profile_evidence(
                    root,
                    {"baseline": {"sha256": "config-sha"}},
                    expected_pairs=1,
                )


if __name__ == "__main__":
    unittest.main()
