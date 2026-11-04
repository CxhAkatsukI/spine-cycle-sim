import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention import (
    respr_retention_audit as audit,
)


class ResPRRetentionAuditTests(unittest.TestCase):
    def setUp(self):
        self.bdf, self.device = audit.g_control.BDF, audit.g_control.DEVICE
        self.board = dict(status="BOARD_EXECUTION_PASS_PENDING_ANALYSIS",
                          bdf=self.bdf, device=self.device, matrix={"stages": ["R"]},
                          r_profile={"rounds": 1}, input_pins={}, rows=[],
                          pins={f"r_{name}": {"path": f"/{name}"}
                                for name in ("reference", "current", "host", "candidate")})
        self.mhz = [150, 500, 450, 0]
        self.clocks = {}
        for case in audit.CASES:
            fixture = f"/{case}"
            self.board["input_pins"][case] = [{"path": f"{fixture}/edges.u32le"}]
            for arm in ("reference", "current"):
                name, device = f"{case}-{arm}", str(self.device)
                command = (["/host", "board", fixture, "a4", "csr_degree", f"/{name}", "/reference", device]
                           if arm == "reference" else ["/candidate", "/current", fixture, device, "1"])
                self.board["rows"].append(dict(stage="R", case=case, arm=arm, repetitions=1,
                                               result_directory=f"/{name}", command=command, clock_evidence=name))
                self.clocks[name] = dict(binary=self.board["pins"][f"r_{arm}"], bdf=self.bdf,
                                         driver_reported_mhz=self.mhz)
        self.frozen = copy.deepcopy(self.board)
        self.ratio = 110
        for change in (
            patch.object(audit, "unchanged"),
            patch.object(audit.clocks, "replay", side_effect=self.clocks.__getitem__),
            patch.object(audit, "profiled_runs",
                         side_effect=lambda row: [{"repeat": 0, "event_span_ns":
                                                   100 if row["arm"] == "reference" else self.ratio}]),
        ):
            change.start()
            self.addCleanup(change.stop)

    def test_gate_requires_matching_actual_clock_not_just_ratio(self):
        self.assertTrue(all(row["retention_gate_pass"] for row in audit.r_controls(self.board, self.frozen).values()))
        self.clocks["amazon-current"]["driver_reported_mhz"] = [140, 500, 450, 0]
        amazon = audit.r_controls(self.board, self.frozen)["amazon"]
        self.assertTrue(amazon["at_most_15_percent_slower"])
        self.assertFalse(amazon["retention_gate_pass"])
        del self.board["rows"][-1]["clock_evidence"]
        self.assertFalse(audit.r_controls(self.board, self.frozen)["amazon"]["retention_gate_pass"])

    def test_over_budget_and_fixture_substitution_are_not_admitted(self):
        self.ratio = 116
        self.assertFalse(audit.r_controls(self.board, self.frozen)["amazon"]["retention_gate_pass"])
        self.board["rows"][-1]["command"][2] = "/different-input"
        with self.assertRaisesRegex(ValueError, "R command"):
            audit.r_controls(self.board, self.frozen)

    def test_recovery_retains_failure_and_checks_clocks(self):
        self.ratio = 116
        for row in self.board["rows"]:
            row.update(stdout={}, clock_preparation={})
        proof = {"path": "/proof"}
        image = self.board["pins"]["r_current"]
        screen = dict(status="FAILED_RETAINED", board_requested=True,
                      errors=['TypeError("\'NoneType\' object is not subscriptable")'],
                      bdf=self.bdf, device=self.device, returned_admission=proof, pins=[proof])
        rows = [dict(row, stage="R", case=case)
                for case, row in audit.r_controls(self.board, self.frozen).items()]
        with TemporaryDirectory() as directory:
            root = Path(directory)
            screen_path = root / "results.json"
            board_path = root / "board-once/results.json"
            frozen_path = root / "frozen.json"
            analysis = root / "analysis/summary.json"
            for path, record in ((screen_path, screen), (board_path, self.board),
                                 (frozen_path, self.frozen), (analysis, {"pairs": rows})):
                path.parent.mkdir(exist_ok=True)
                path.write_text(json.dumps(record))
            with patch.object(audit.returned_route, "replay", return_value=(Path("/current"), image, [proof])), \
                    patch.object(audit.matched_hbm, "validate_after") as clock:
                args = (root / "route", screen_path, board_path, frozen_path)
                recovered = audit.recover_failed_r_screen(*args)
                self.assertEqual(recovered["status"], "R_PERFORMANCE_GATE_FAILED_RETAINED")
                self.assertFalse(recovered["supported_r_gate_pass"])
                self.assertEqual(clock.call_count, 4)
                self.ratio = 110
                with self.assertRaisesRegex(ValueError, "not admit"):
                    audit.recover_failed_r_screen(*args)

    def test_g_reports_actual_clock_mismatch_even_when_times_pass(self):
        image, host = {"path": "/current"}, {"path": "/g-host"}
        graph, reference = {"path": "/graph"}, Path("/reference-report")
        profile = {"repeat": 0, "event_span_ns": 110, "config": {"static_edges": "390847"}}
        comparison = audit.summarize([{"repeat": 0, "event_span_ns": 100}], [profile], repetitions=1)
        row = dict(stdout={"path": "/stdout"}, stderr={"path": "/stderr"}, oracle={"path": "/oracle"},
                   clock_evidence="amazon-current",
                   command=["/g-host", "--update-only", "/current", "/graph", "/oracle"])
        report = dict(pins={"host": host, "input": graph, "reference": {"path": str(reference)}},
                      row=row, bdf=self.bdf, device=self.device, repetitions=1, board_launch_attempted=True,
                      profile=profile, comparison=comparison)
        self.clocks["amazon-current"]["driver_reported_mhz"] = [140, 500, 450, 0]
        with patch.object(audit, "identity", side_effect=lambda path: {"path": str(path)}), \
                patch.object(Path, "read_text", return_value="test"), \
                patch.object(audit, "update_only_profile", return_value=profile), \
                patch.object(audit.g_control, "reference_arm",
                             return_value=(graph, {}, self.clocks["amazon-reference"],
                                           [{"repeat": 0, "event_span_ns": 100}], None, None)):
            gate = audit.g_gate(report, reference, image, host)
            self.assertTrue(gate["at_most_15_percent_slower"])
            self.assertFalse(gate["retention_gate_pass"])
