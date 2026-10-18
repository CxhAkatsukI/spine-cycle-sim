import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.original_regraph_execution.hardware import artifact
from spine_cycle_sim.experiments.original_regraph_execution.hardware.board_execution import model_audit as audit
import test_original_regraph_board_comparison as fixtures


class ModelBoardAuditTests(unittest.TestCase):
    def controls(self, root):
        _, controls = fixtures.BoardComparisonTests().controls(root)
        board = controls[1]
        plan = json.loads(Path(board["reports"][1]["path"]).read_text())
        inputs, cases = [], []
        for graph, case_id in audit.BASE_CASES.items():
            case = next(row for row in plan["cases"] if row["graph"] == graph)
            task = Path(case["input"]) / "tasks.u32le"
            task.write_bytes(b"task")
            board["pins"].append(artifact.identity(task))
            captures = [artifact.identity(Path(case["input"]) / name) for name in audit.INPUTS]
            inputs.append({"id": graph, "files": captures})
            row = next(item for item in board["board"]["rows"] if item["graph"] == graph)
            result = {key: row["observation"][key] for key in
                      ("vertices", "logical_edges", "physical_edges", "dummy_edges", "published_vertices")}
            result.update(cycles=1000, clock_mhz=210)
            output = row["analysis"]["independent_oracle"]["canonical_aligned_sha256"]
            analysis = {"result": result, "files": [{"sha256": output}] * 4}
            cases.append({"id": case_id, "runs": [{"analysis": analysis}] * 2})
        return {"report": {"inputs": inputs, "cases": cases, "boundary": "frozen model"},
                "contract": {"memory_model": "mock memory"}, "pins": [],
                "historical_source_dependency_drift": []}, board

    def test_compare_checks_all_three_rows_without_calibration_or_figure_claims(self):
        with tempfile.TemporaryDirectory() as directory:
            model, board = self.controls(Path(directory))
            result = audit.compare(model, board)
            self.assertEqual(len(result["rows"]), 3)
            self.assertEqual(result["status"], audit.STATUS)
            self.assertTrue(all(result[name] is False for name in audit.CLAIMS))
            self.assertFalse(result["frozen_model_recomputed"])
            self.assertFalse(result["current_model_revalidated"])
            self.assertEqual(result["excluded_board_bindings"][0]["rows"], 9)
            self.assertEqual(len(result["timing_match_blockers"]), 3)
            for row in result["rows"]:
                self.assertFalse(row["timing_match_eligible"])
                self.assertIsNone(row["timing_error_pct"])
                self.assertAlmostEqual(row["diagnostic_cycle_count_ratio"],
                                       1000 / row["board_event_span_cycles_median"])
            self.assertIn("not speedup", result["ratio_definition"])
            self.assertIn("not rerun or fitted", audit.markdown(result))

    def test_compare_rejects_unmatched_inputs_tasks_outputs_work_repeats_and_clock(self):
        with tempfile.TemporaryDirectory() as directory:
            model, board = self.controls(Path(directory))
            for change in ("input", "task", "output", "work", "repeat", "clock", "case"):
                changed = copy.deepcopy(board)
                row = next(item for item in changed["board"]["rows"] if item["binding"] == "csr_degree")
                if change == "input":
                    changed["cases"][(row["graph"], "csr_degree")]["inputs"][audit.INPUTS[0]] = "f" * 64
                elif change == "task":
                    changed["pins"] = [pin for pin in changed["pins"] if not pin["path"].endswith("tasks.u32le")]
                elif change == "output":
                    row["analysis"]["independent_oracle"]["canonical_aligned_sha256"] = "f" * 64
                elif change == "work":
                    row["observation"]["physical_edges"] += 1
                elif change == "repeat":
                    changed["board"]["rows"].remove(row)
                elif change == "clock":
                    row["analysis"]["clock_mhz"] = 210
                else:
                    changed["cases"].pop((row["graph"], "author_initial"))
                with self.subTest(change=change), self.assertRaises(ValueError):
                    audit.compare(model, changed)

    def checkpoint(self, root):
        contract = {"boundary": "frozen model", "cases": []}
        report = {"status": audit.model_analysis.STATUS, "ubsan_identical_no_diagnostics": True,
                  "FPGA_measured_cycles": None, "publication_rate_error_pct": None,
                  "boundary": contract["boundary"], "inputs": [], "cases": [], "steps": [],
                  "analysis": {"complete": True}}
        binary = root / "binary"
        binary.write_bytes(b"frozen binary")
        report["binaries"] = [{**artifact.identity(binary), "dependencies": [artifact.identity(binary)]}]
        for graph, name in audit.BASE_CASES.items():
            directory = root / graph
            directory.mkdir()
            for capture in (*audit.INPUTS, "execution.u32le"):
                (directory / capture).write_bytes(capture.encode())
            report["inputs"].append({"id": graph, "directory": str(directory),
                "descriptor_sha256": artifact.identity(directory / "execution.u32le")["sha256"],
                "files": [artifact.identity(directory / capture) for capture in audit.INPUTS]})
            variants = [name] if graph != "boundary_ring" else [name, "boundary_reverse",
                        "boundary_two_parents", "boundary_latency128"]
            if graph != "boundary_ring":
                variants.append(name + "_reverse")
            for case_id in variants:
                contract["cases"].append({"id": case_id, "input": graph})
                runs = []
                for suffix in ("first", "repeat"):
                    destination = root / (case_id + "_" + suffix)
                    destination.mkdir()
                    output = destination / "final_replica0.u32le"
                    output.write_bytes(b"replica")
                    analysis = {"files": [{"path": output.name}]}
                    atomic_write_json(destination / "analysis.json", analysis)
                    for stream in ("stdout", "stderr"):
                        (destination / stream).write_text("")
                    runs.append({"directory": str(destination), "analysis": analysis,
                                 "analysis_sha256": artifact.identity(destination / "analysis.json")["sha256"]})
                    report["steps"].append({"id": case_id + "_" + suffix, "exit_code": 0,
                        "timed_out": False, "stdout": str(destination / "stdout"),
                        "stderr": str(destination / "stderr")})
                report["cases"].append({"id": case_id, "status": audit.model_analysis.STATUS, "runs": runs})
        contract_path, report_path, verification_path = [root / name for name in
            ("contract.json", "report.json", "verification.json")]
        atomic_write_json(contract_path, contract)
        report["contract_sha256"] = artifact.identity(contract_path)["sha256"]
        atomic_write_json(report_path, report)
        atomic_write_json(verification_path, {"results_sha256": artifact.identity(report_path)["sha256"],
            "status": audit.model_analysis.STATUS,
            "all_raw_numerical_inputs_binary_and_resource_evidence_rechecked": True})
        return report_path, verification_path, contract_path

    def test_load_replays_complete_checkpoint_and_normalizes_binary_dependency_pins(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = self.checkpoint(Path(directory))
            with patch.object(audit.model_analysis, "analyze", side_effect=lambda text, dest, *args:
                              json.loads((dest / "analysis.json").read_text())) as replay, \
                    patch.object(audit.model_analysis, "analyze_matrix", return_value={"complete": True}):
                result = audit.load_model(*paths)
            self.assertEqual(replay.call_count, 16)
            self.assertEqual(len(result["report"]["cases"]), 8)
            audit.unchanged(result["pins"])
            self.assertTrue(all(set(pin) == {"path", "sha256"} for pin in result["pins"]))

    def test_load_rejects_changed_checkpoint_input_binary_stderr_and_raw_analysis(self):
        for change in ("report", "input", "binary", "stderr", "analysis"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                paths = self.checkpoint(root)
                target = {"report": paths[0], "input": root / "amazon/tasks.u32le",
                          "binary": root / "binary", "stderr": root / "boundary_first/stderr",
                          "analysis": root / "boundary_first/analysis.json"}[change]
                target.write_text("changed")
                with self.assertRaises((ValueError, json.JSONDecodeError)):
                    audit.load_model(*paths)

    def test_historical_dependency_drift_is_explicit_not_current_model_admission(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report_path, verification, contract = self.checkpoint(root)
            report = json.loads(report_path.read_text())
            dependency = root / "header"
            dependency.write_bytes(b"old header")
            frozen = artifact.identity(dependency)
            report["binaries"][0]["dependencies"] = [frozen]
            atomic_write_json(report_path, report)
            record = json.loads(verification.read_text())
            atomic_write_json(verification, {**record, "results_sha256": artifact.identity(report_path)["sha256"]})
            dependency.write_bytes(b"current header")
            with patch.object(audit.model_analysis, "analyze", side_effect=lambda text, dest, *args:
                              json.loads((dest / "analysis.json").read_text())), \
                    patch.object(audit.model_analysis, "analyze_matrix", return_value={"complete": True}):
                result = audit.load_model(report_path, verification, contract)
            self.assertEqual(result["historical_source_dependency_drift"],
                             [{"frozen": frozen, "current": artifact.identity(dependency)}])
            audit.unchanged(result["pins"])

    def test_run_uses_complete_loaders_and_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model, board = self.controls(root)
            output = root / "audit"
            with patch.object(audit, "load_model", return_value=model) as load, \
                    patch.object(audit.comparison, "load", return_value=board) as board_load:
                result = audit.run(root / "report", root / "verification", root / "contract", root / "a4", output)
                self.assertEqual(json.loads((output / "results.json").read_text()), result)
                self.assertIn("No Timing-Match Admission", (output / "README.md").read_text())
                load.assert_called_once()
                board_load.assert_called_once_with(root / "a4", "a4")
                with self.assertRaises(FileExistsError):
                    audit.run(root / "report", root / "verification", root / "contract", root / "a4", output)


if __name__ == "__main__":
    unittest.main()
