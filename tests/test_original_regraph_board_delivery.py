import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.original_regraph_execution.hardware import artifact
from spine_cycle_sim.experiments.original_regraph_execution.hardware.board_execution import analysis, delivery, preparation
import test_original_regraph_board_analysis as fixtures


class BoardDeliveryTests(unittest.TestCase):
    def fixture(self, root, topology="original_example"):
        source, case, observed = fixtures.BoardAnalysisTests().fixture(root, topology)
        reference = case["reference"]["one_superstep_comparison"]
        reference["original_host_result_sha256"] = reference["csr_degree_result_sha256"]
        attempt = root / "attempt"
        rows, cases = [], []
        for graph in preparation.GRAPHS:
            for binding in ("author_initial", "csr_degree"):
                admitted = {**case, "graph": graph, "binding": binding,
                            "offline": {**case["offline"], "binding": binding}}
                cases.append(admitted)
                for repeat in range(3):
                    destination = attempt / "board/cases" / f"r{repeat}_{graph}_{binding}"
                    shutil.copytree(source, destination)
                    item = {**observed, "binding": binding}
                    atomic_write_json(destination / "result.json", item)
                    rows.append({"graph": graph, "binding": binding, "repeat": repeat,
                                 "directory": str(destination), "observation": item,
                                 "analysis": analysis.inspect(item, destination, admitted, item["bdf"])})
        report = {"status": analysis.pass_status(topology), "configuration": topology,
                  "errors": [], "boundary": preparation.BOUNDARY,
                  "board_launch_attempted": True, "board_programmed": True,
                  "hardware_timing_measured": True, **dict.fromkeys(delivery.EXCLUDED_CLAIMS, False),
                  "rows": rows, "summaries": analysis.matrix(rows),
                  "attempts": [{"name": f"r{row['repeat']}_{row['graph']}_{row['binding']}",
                                "exit_code": 0, "timed_out": False, "lease_fd_forwarded": True}
                               for row in rows], "pins": [], "runtime": {"device": {"bdf": observed["bdf"]}}}
        supervisor = {key: value for key, value in report.items() if key not in ("rows", "attempts")}
        atomic_write_json(attempt / "board/results.json", report)
        execution = {"exit_code": 0, "stop_reason": "process_exit", "cleanup_snapshot_error": None}
        atomic_write_json(attempt / "worker.resources.json", execution)
        route = root / "route"
        (route / "link/reports").mkdir(parents=True)
        atomic_write_json(route / "manifest.json", {})
        job = {"configuration": topology, "boundary": preparation.BOUNDARY, "cases": cases,
               "repeats": preparation.REPEATS, "policy": preparation.POLICY,
               **dict.fromkeys(delivery.EXCLUDED_CLAIMS, False), "xclbin": {"path": "indexed"}}
        atomic_write_json(attempt / "manifest.json", job)
        supervisor.update(child=artifact.identity(attempt / "board/results.json"), execution=execution,
                          pins=[artifact.identity(route / "manifest.json")],
                          routed_admission={"analysis": {"clock": [["DATA", "DATA_CLK", 150]]},
                                            "xclbin": job["xclbin"], "pins": []})
        atomic_write_json(attempt / "results.json", supervisor)
        return attempt, json.loads((attempt / "results.json").read_text()), report

    def test_recheck_replays_raw_oracle_and_strict_route_review(self):
        with tempfile.TemporaryDirectory() as directory:
            attempt, supervisor, board = self.fixture(Path(directory))
            with patch.object(delivery.gates, "inspect_routed",
                              return_value={"clock": [("DATA", "DATA_CLK", 150)]}) as inspect:
                self.assertEqual(delivery.recheck(attempt), (supervisor, board))
                self.assertEqual(inspect.call_args.kwargs, {"configuration": "original_example"})
                output = Path(board["rows"][0]["directory"]) / "replica13.u32le"
                payload = output.read_bytes()
                output.write_bytes(payload[:-1] + bytes([payload[-1] ^ 1]))
                with self.assertRaisesRegex(ValueError, "replica"):
                    delivery.recheck(attempt)
                output.write_bytes(payload)
            with patch.object(delivery.gates, "inspect_routed",
                              return_value={"clock": [("DATA", "DATA_CLK", 151)]}):
                with self.assertRaisesRegex(ValueError, "strict timing"):
                    delivery.recheck(attempt)
            atomic_write_json(attempt / "worker.resources.json", {**supervisor["execution"], "exit_code": 1})
            with self.assertRaisesRegex(ValueError, "bounded worker"):
                delivery.recheck(attempt)

    def test_terminal_claims_fail_closed_for_each_topology(self):
        with tempfile.TemporaryDirectory() as directory:
            _, supervisor, board = self.fixture(Path(directory))
            delivery.terminal(supervisor, "original_example")
            delivery.matrix(board)
            for key in ("board_launch_attempted", "board_programmed", "hardware_timing_measured"):
                with self.subTest(key=key), self.assertRaises(ValueError):
                    delivery.terminal({**supervisor, key: False}, "original_example")
            for key in delivery.EXCLUDED_CLAIMS:
                with self.subTest(key=key), self.assertRaises(ValueError):
                    delivery.terminal({**supervisor, key: True}, "original_example")
            with self.assertRaises(ValueError):
                delivery.terminal(supervisor, "a4")

    def test_attempts_missing_duplicate_failed_and_wrong_summary_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            _, _, board = self.fixture(Path(directory))
            for change in ("missing", "duplicate", "failed", "timeout", "lease", "summary"):
                changed = copy.deepcopy(board)
                if change == "missing":
                    changed["attempts"].pop()
                elif change == "duplicate":
                    changed["attempts"][0] = changed["attempts"][1]
                elif change == "failed":
                    changed["attempts"][0]["exit_code"] = 1
                elif change == "timeout":
                    changed["attempts"][0]["timed_out"] = True
                elif change == "lease":
                    changed["attempts"][0]["lease_fd_forwarded"] = False
                else:
                    changed["summaries"][0]["event_span_ns"]["median"] += 1
                with self.subTest(change=change), self.assertRaises(ValueError):
                    delivery.matrix(changed)

    def test_portable_capsule_each_topology_retains_failure_without_binary_outputs(self):
        for topology in ("original_example", "a4"):
            with self.subTest(topology=topology), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                attempt, supervisor, board = self.fixture(root, topology)
                failed = root / "failed"
                atomic_write_json(failed / "results.json", {"status": "FAILED_RETAINED", "errors": ["runtime"]})
                destination = root / "capsule"
                with patch.object(delivery, "recheck", return_value=(supervisor, board)):
                    result = delivery.package(attempt, destination, [failed])
                    with self.assertRaises(FileExistsError):
                        delivery.package(attempt, destination, [failed])
                self.assertEqual(delivery.verify(destination), result)
                self.assertTrue(result["hardware_timing_measured"])
                self.assertTrue(any(row["path"].startswith("attempts/failed/") for row in result["files"]))
                self.assertFalse(any(row["path"].endswith(".u32le") for row in result["files"]))
                self.assertFalse(result["publication_match"])
                self.assertEqual(result["rows"], 18)
                index = destination / "index.json"
                original = index.read_text()
                changed = json.loads(original)
                changed["summaries"][0]["event_span_ns"]["median"] += 1
                atomic_write_json(index, changed)
                with self.assertRaisesRegex(ValueError, "disagree"):
                    delivery.verify(destination)
                index.write_text(original)
                archive = destination / result["archive"]
                archive.write_bytes(archive.read_bytes() + b"tamper")
                with self.assertRaisesRegex(ValueError, "archive changed"):
                    delivery.verify(destination)

    def test_failed_or_raw_mismatched_attempt_cannot_be_sealed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            attempt, supervisor, board = self.fixture(root)
            failed = root / "not-failed"
            atomic_write_json(failed / "results.json", {"status": "PASS", "errors": []})
            with patch.object(delivery, "recheck", return_value=(supervisor, board)):
                with self.assertRaisesRegex(ValueError, "failed-attempt"):
                    delivery.package(attempt, root / "reject", [failed])
                changed = Path(board["rows"][0]["directory"]) / "result.json"
                atomic_write_json(changed, {**board["rows"][0]["observation"], "event_span_ns": 999})
                with self.assertRaisesRegex(ValueError, "raw observation"):
                    delivery.package(attempt, root / "mismatch", [])


if __name__ == "__main__":
    unittest.main()
