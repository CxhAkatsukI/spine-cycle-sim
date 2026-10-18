"""Bind synthetic admission records; these tests never admit real hardware."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.evaluation_impact.fullgraph_readiness import analysis, board_preparation, preparation


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def fixture(root, algorithm):
    preflight = root / "preflight"
    guard = preflight / "source/tools/weighted_pma_native_host.cpp"
    guard.parent.mkdir(parents=True)
    guard.write_text('select_xilinx_device() { std::getenv("GRASU_REGRAPH_EXPECT_BDF"); '
                     'CL_DEVICE_PCIE_BDF; return device; }')
    binary = preflight / algorithm
    binary.write_text("synthetic test binary; never executed")
    candidate, timing = root / "candidate.hw.xclbin", root / "timing.rpt"
    candidate.write_text("synthetic test bitstream; never programmed")
    timing.write_text("synthetic test timing; parser mocked")
    report = {"status": analysis.PASS, "pins": [preparation.identity(binary), preparation.identity(guard)],
              "source_revision": "synthetic-revision", "matrix": [
                  {"dataset": dataset, "algorithm": algorithm} for dataset in preparation.DATASETS]}
    checked = {"status": "ROUTED_METADATA_TIMING_PASS_AWAITING_BOARD" if algorithm == "weighted_sssp" else
               "ALGORITHM_ROUTED_METADATA_TIMING_PASS_AWAITING_BOARD", "algorithm": algorithm, "errors": [],
               "pins": [], "candidate": preparation.identity(candidate),
               "timing": {"report": preparation.identity(timing), "wns_ns": .001}}
    write(preflight / "results.json", report)
    admission = root / "admission.json"
    write(admission, checked)
    return preflight, admission, checked


class BoardPreparationTests(unittest.TestCase):
    def test_all_algorithms_replay_offline_evidence_and_bind_exact_eight_rows(self):
        for algorithm in preparation.ALGORITHMS:
            with self.subTest(algorithm=algorithm), tempfile.TemporaryDirectory() as directory:
                preflight, admission, checked = fixture(Path(directory), algorithm)
                with patch.object(board_preparation.recheck, "recheck") as replay, \
                        patch.object(board_preparation.bitstream, "parse_routed_timing", return_value=checked["timing"]):
                    plan = board_preparation.prepare(preflight, admission, algorithm)
                replay.assert_called_once()
                self.assertEqual([row["dataset"] for row in plan["rows"]], list(preparation.DATASETS))
                self.assertEqual(plan["smoke"]["vertices"], 327681)
                preparation.unchanged(plan["pins"], full=True)
                row = {**plan["smoke"], "source": 3}
                command = board_preparation.command(plan, row, Path("/result"))
                self.assertEqual(command[:2], [str(preflight / algorithm), checked["candidate"]["path"]])
                self.assertEqual(command[4:], [] if algorithm == "residual_pagerank" else ["3", "256"])

    def test_wrong_or_failed_admission_false_claims_and_stale_timing_rejected(self):
        for mutation in ("status", "algorithm", "errors", "board", "timing"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                preflight, admission, checked = fixture(Path(directory), "connected_components")
                actual_timing = checked["timing"].copy()
                if mutation == "status":
                    checked["status"] = "ROUTING"
                elif mutation == "algorithm":
                    checked["algorithm"] = "residual_pagerank"
                elif mutation == "errors":
                    checked["errors"] = ["unclosed gate"]
                elif mutation == "board":
                    checked["board_admitted"] = True
                else:
                    actual_timing["wns_ns"] = -.001
                write(admission, checked)
                with patch.object(board_preparation.recheck, "recheck"), \
                        patch.object(board_preparation.bitstream, "parse_routed_timing", return_value=actual_timing), \
                        self.assertRaises(ValueError):
                    board_preparation.prepare(preflight, admission, "connected_components")

    def test_missing_guard_stale_binary_missing_row_and_failed_replay_rejected(self):
        for mutation in ("guard", "binary", "rows", "replay"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                preflight, admission, checked = fixture(Path(directory), "weighted_sssp")
                if mutation == "guard":
                    (preflight / "source/tools/weighted_pma_native_host.cpp").write_text("old host")
                elif mutation == "binary":
                    (preflight / "weighted_sssp").write_text("drift")
                elif mutation == "rows":
                    report = json.loads((preflight / "results.json").read_text())
                    report["matrix"].pop()
                    write(preflight / "results.json", report)
                with patch.object(board_preparation.recheck, "recheck",
                                  side_effect=ValueError("bad raw evidence") if mutation == "replay" else None), \
                        patch.object(board_preparation.bitstream, "parse_routed_timing", return_value=checked["timing"]), \
                        self.assertRaises(ValueError):
                    board_preparation.prepare(preflight, admission, "weighted_sssp")

    def test_fullpr_cannot_reuse_convergence_contract(self):
        with self.assertRaisesRegex(ValueError, "not fixed-round FullPR"):
            board_preparation.prepare(Path("/unused"), Path("/unused"), "full_pagerank")

    def test_pin_hash_drift_and_conflicting_stat_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source"
            source.write_text("data")
            pin = preparation.identity(source)
            self.assertEqual(board_preparation.stamp_pins([pin, pin]), [pin])
            bad = {**pin, "sha256": "0" * 64}
            with self.assertRaises(ValueError):
                board_preparation.stamp_pins([pin, bad])
            source.write_text("drift")
            with self.assertRaises(ValueError):
                board_preparation.stamp_pins([pin])


if __name__ == "__main__":
    unittest.main()
