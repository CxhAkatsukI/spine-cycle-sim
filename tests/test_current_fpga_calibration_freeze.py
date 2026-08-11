import hashlib
import json
from pathlib import Path
import unittest

from scripts.freeze_current_fpga_calibration_v4 import (
    group_component_models,
    group_total_models,
)
from scripts import analyze_current_fpga_calibration
from scripts import analyze_current_fpga_components
from scripts import audit_evaluation_refresh_alignment
from spine_cycle_sim.calibration.current_fpga import (
    CurrentFPGAComponentRecord,
    CurrentFPGATimingRecord,
)


ROOT = Path(__file__).resolve().parents[1]


class CurrentFPGACalibrationFreezeTests(unittest.TestCase):
    def test_analysis_defaults_follow_latest_frozen_contract(self) -> None:
        expected_cases = (
            ROOT / "configs/contracts/evaluation_refresh_fpga_cases_v5.json"
        )
        expected_contract = (
            ROOT / "configs/contracts/evaluation_refresh_fpga_calibration_v6.json"
        )
        self.assertEqual(analyze_current_fpga_calibration.DEFAULT_CASES, expected_cases)
        self.assertEqual(analyze_current_fpga_components.DEFAULT_CASES, expected_cases)
        self.assertEqual(
            analyze_current_fpga_calibration.DEFAULT_CONTRACT, expected_contract
        )
        self.assertEqual(analyze_current_fpga_components.DEFAULT_CONTRACT, expected_contract)
        self.assertEqual(
            audit_evaluation_refresh_alignment.DEFAULT_CALIBRATION_CONTRACT,
            expected_contract,
        )

    def test_v4_contract_keeps_disjoint_frozen_roles(self) -> None:
        cases = json.loads(
            (
                ROOT / "configs/contracts/evaluation_refresh_fpga_cases_v3.json"
            ).read_text(encoding="utf-8")
        )
        contract = json.loads(
            (
                ROOT
                / "configs/contracts/evaluation_refresh_fpga_calibration_v4.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(cases["calibration_contract_id"], contract["contract_id"])
        self.assertEqual(
            cases["roles"],
            {"au": "calibration", "su": "calibration", "wk": "holdout", "r19": "holdout"},
        )
        self.assertTrue(
            contract["manifest_gates"]["memory_ledger"][
                "spine_owner_request_formula_recomputed"
            ]
        )
        for profile in contract["architecture_profiles"]:
            profile_path = ROOT / profile["path"]
            self.assertTrue(profile_path.is_file())
            self.assertEqual(
                hashlib.sha256(profile_path.read_bytes()).hexdigest(),
                profile["sha256"],
            )

    def test_v5_contract_pins_final_plugin_and_clean_holdout_split(self) -> None:
        cases = json.loads(
            (
                ROOT / "configs/contracts/evaluation_refresh_fpga_cases_v4.json"
            ).read_text(encoding="utf-8")
        )
        contract = json.loads(
            (
                ROOT
                / "configs/contracts/evaluation_refresh_fpga_calibration_v5.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(cases["calibration_contract_id"], contract["contract_id"])
        self.assertEqual(
            cases["roles"],
            {
                "au": "calibration",
                "su": "calibration",
                "wk": "holdout",
                "r19": "holdout",
            },
        )
        self.assertEqual(
            cases["default_simulation_root"],
            "/data/tmp/chuxiao/evaluation_refresh_current_fpga_v9_20260812",
        )
        plugin = ROOT / contract["simulator_plugin"]["path"]
        self.assertEqual(
            contract["simulator_plugin"]["path"],
            "cpp/sst/build/sst-current-fpga-v9/libspine_cycle.so",
        )
        self.assertRegex(contract["simulator_plugin"]["sha256"], r"^[0-9a-f]{64}$")
        if plugin.is_file():
            self.assertEqual(
                hashlib.sha256(plugin.read_bytes()).hexdigest(),
                contract["simulator_plugin"]["sha256"],
            )
        self.assertIn(
            "source-completion",
            contract["supersedes"]["reason"],
        )

    def test_v6_contract_pins_complete_grasu_observability(self) -> None:
        cases = json.loads(
            (
                ROOT / "configs/contracts/evaluation_refresh_fpga_cases_v5.json"
            ).read_text(encoding="utf-8")
        )
        contract = json.loads(
            (
                ROOT
                / "configs/contracts/evaluation_refresh_fpga_calibration_v6.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(cases["calibration_contract_id"], contract["contract_id"])
        self.assertEqual(
            cases["default_simulation_root"],
            "/data/tmp/chuxiao/evaluation_refresh_current_fpga_v10_20260812",
        )
        self.assertEqual(
            contract["simulator_plugin"]["path"],
            "cpp/sst/build/sst-current-fpga-v10/libspine_cycle.so",
        )
        plugin = ROOT / contract["simulator_plugin"]["path"]
        self.assertRegex(contract["simulator_plugin"]["sha256"], r"^[0-9a-f]{64}$")
        if plugin.is_file():
            self.assertEqual(
                hashlib.sha256(plugin.read_bytes()).hexdigest(),
                contract["simulator_plugin"]["sha256"],
            )
        gates = contract["manifest_gates"]["memory_ledger"]
        self.assertTrue(gates["grasu_regraph_phase_request_byte_locality_ledgers_closed"])
        self.assertTrue(gates["grasu_regraph_compute_axi_issued_equal_completed"])
        self.assertTrue(gates["grasu_regraph_observable_fifos_profile_bounded"])
        self.assertTrue(gates["grasu_regraph_adapter_fifo_depth_and_stalls_serialized"])
        self.assertIn("changes only result observability", contract["supersedes"]["reason"])

    def test_total_freeze_groups_only_calibration_rows(self) -> None:
        rows = [
            CurrentFPGATimingRecord("spine", "sssp", "p", "au", "calibration", 10, 20),
            CurrentFPGATimingRecord("spine", "sssp", "p", "su", "calibration", 20, 40),
        ]
        models = group_total_models(rows)
        self.assertEqual(len(models), 1)
        self.assertEqual(models[0]["scale"], 2.0)
        self.assertEqual(models[0]["profile_id"], "p")
        self.assertFalse(models[0]["holdout_used_for_fit"])
        with self.assertRaisesRegex(ValueError, "holdout"):
            group_total_models(
                rows
                + [
                    CurrentFPGATimingRecord(
                        "spine", "sssp", "p", "wk", "holdout", 30, 60
                    )
                ]
            )

    def test_component_freeze_groups_only_calibration_rows(self) -> None:
        rows = [
            CurrentFPGAComponentRecord(
                "spine", "sssp", "p", "au", "calibration", "reader", 10, 30, "routed reader"
            ),
            CurrentFPGAComponentRecord(
                "spine", "sssp", "p", "su", "calibration", "reader", 20, 60, "routed reader"
            ),
        ]
        models = group_component_models(rows)
        self.assertEqual(len(models), 1)
        self.assertAlmostEqual(models[0]["scale"], 3.0)
        self.assertEqual(models[0]["profile_id"], "p")
        self.assertFalse(models[0]["holdout_used_for_fit"])


if __name__ == "__main__":
    unittest.main()
