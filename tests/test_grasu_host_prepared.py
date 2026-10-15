import copy
import hashlib
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.shared_workloads import SliceGraph, SliceRecord
from spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.host_prepared import (
    analysis, delivery, preparation,
)
from spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.study import run
from spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.analysis import WARNING_PAIR
from spine_cycle_sim.experiments.evaluation_impact.common_g.search_pipeline.synthesis import unchanged


class HostPreparedTests(unittest.TestCase):
    def case(self):
        return {"case": "test", "vertices": 2, "shards": 1, "positive_updates": 1,
                "batches": [{"batch": 0, "updates": 0, "edges": 1},
                            {"batch": 1, "updates": 1, "edges": 0},
                            {"batch": 2, "updates": 1, "edges": 1}]}

    def rows(self):
        case = self.case()
        return [{"case": case["case"], "vertices": 2, "shards": 1, "registered": arm,
                 **facts, "packets": 2, "hot_even": facts["updates"], "cold_even": 0,
                 "hot_odd": 0, "cold_odd": 0, "complete_state_pass": True, "direct_handoff_pass": True}
                for arm in (0, 1) for facts in case["batches"]]

    def stdout(self, rows=None):
        return "\n".join([*("HOST_G_ROW " + json.dumps(r) for r in (self.rows() if rows is None else rows)),
                          analysis.MARKER])

    def stderr(self):
        return "\n".join(WARNING_PAIR)

    def test_independent_chronological_mutations_and_empty_batch(self):
        graph = SliceGraph("g", 2, (SliceRecord(0, 1, 3),))
        updates = SliceGraph("u", 2, (SliceRecord(0, 1, 3, -1), SliceRecord(0, 1, 4)))
        self.assertEqual(preparation.batch_facts(graph, updates), self.case()["batches"])

    def test_illegal_deletion_duplicate_initial_and_insertions_rejected(self):
        graph = SliceGraph("g", 2, (SliceRecord(0, 1, 3),))
        for records in ((SliceRecord(0, 1, 3),), (SliceRecord(0, 1, 4, -1),),
                        (SliceRecord(1, 0, 3, -1),), (SliceRecord(0, 1, 3, 0),)):
            with self.subTest(records=records), self.assertRaises(ValueError):
                preparation.batch_facts(graph, SliceGraph("u", 2, records))
        with self.assertRaises(ValueError):
            preparation.batch_facts(SliceGraph("g", 2, graph.records * 2), SliceGraph("u", 2, ()))

    def test_complete_matrix_checks_state_handoff_ports_and_arm_equality(self):
        self.assertEqual(analysis.analyze(self.case(), self.stdout(), self.stderr()), self.rows())
        for fault in ("missing", "order", "case", "edges", "updates", "cold_even", "packets",
                      "complete_state_pass", "direct_handoff_pass", "arm_packets"):
            rows = copy.deepcopy(self.rows())
            if fault == "missing": rows.pop()
            elif fault == "order": rows[0], rows[1] = rows[1], rows[0]
            elif fault == "case": rows[-1][fault] = "wrong"
            elif fault.endswith("pass"): rows[-1][fault] = False
            elif fault == "packets": rows[-1][fault] = 0
            elif fault == "arm_packets": rows[-1]["packets"] += 1
            else: rows[-1][fault] += 1
            with self.subTest(fault=fault), self.assertRaises(ValueError):
                analysis.analyze(self.case(), self.stdout(rows), self.stderr())

    def test_exact_pristine_hot_insert_diagnostics_required(self):
        for stderr in ("", self.stderr() * 2, self.stderr() + "new warning"):
            with self.subTest(stderr=stderr), self.assertRaises(ValueError):
                analysis.analyze(self.case(), self.stdout(), stderr)
        self.assertEqual(analysis.analyze(self.case(), self.stdout(), "".join(WARNING_PAIR)), self.rows())

    def test_capacity_and_bank_flags_preserved_vendor_dependencies_pinned(self):
        argv = preparation.command(Path("source"), Path("vendor"), "g++", Path("probe"))
        self.assertIn("source/host_prepared/control.cpp", argv)
        self.assertNotIn("source/control.cpp", argv)
        self.assertIn("-DGRASU_REGRAPH_BANK_STREAM=1", argv)
        self.assertIn("-DGRASU_REGRAPH_DIRECTORY_TILE_ROWS=1024", argv)
        self.assertIn("-DCACHE_BANK_REGISTERED", argv)
        self.assertIn("-MD", argv)
        self.assertNotIn("-MMD", argv)
        self.assertEqual(argv.count("-isystem"), 2)
        self.assertFalse(any("MAX_CACHE_SEGMENT=" in flag for flag in argv))

    def test_real_matrix_and_production_host_sources_frozen_separately(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            integration = root / "integration"
            for name in ("weighted_pma_graph.hpp", "weighted_pma_runtime_plan.hpp"):
                path = integration / "include" / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(name)
            def base(output, upstream, integration):
                (output / "source").mkdir(parents=True)
                return []
            with patch.object(preparation, "composition_prepare", base):
                pins, contract = preparation.prepare(root / "attempt", root / "upstream", integration)
            self.assertEqual(len(contract["cases"]), 7)
            self.assertEqual(sum(c["shards"] for c in contract["cases"]), 10)
            self.assertEqual(len(pins), len({p["path"] for p in pins}))
            self.assertTrue(all(c["batches"][0]["updates"] == 0 for c in contract["cases"]))
            self.assertEqual(sum(c["partition_vertices"] == 65536 for c in contract["cases"]), 6)
            self.assertEqual(contract["cache_capacity_per_half"], 131072)
            unchanged(pins)

    def test_failed_capsule_preserved_corruption_and_claim_promotion_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            attempt = root / "failed"
            source = attempt / "source/control.cpp"
            source.parent.mkdir(parents=True)
            source.write_text("frozen source")
            contract = self.case()
            (attempt / "contract.json").write_text(json.dumps(contract))
            report = {"status": "FAILED_RETAINED", "errors": ["retained failure"], "steps": [],
                      "rows": [], "contract": contract,
                      "source": [{"path": str(source), "sha256": sha256_file(source)}],
                      **dict.fromkeys(analysis.CLAIMS, False)}
            (attempt / "results.json").write_text(json.dumps(report))
            index = delivery.package(root / "evidence", [attempt])
            self.assertEqual(index, delivery.verify(root / "evidence"))
            for key in analysis.CLAIMS:
                with self.subTest(key=key), self.assertRaisesRegex(ValueError, "claim boundary"):
                    delivery.validate(attempt, {**report, key: True})
            archive = root / "evidence" / index["attempts"][0]["archive"]
            archive.write_bytes(archive.read_bytes() + b"corrupt")
            with self.assertRaisesRegex(ValueError, "archive identity"):
                delivery.verify(root / "evidence")

    def test_synthetic_reserve_can_only_change_within_declared_safe_range(self):
        for reserve in (0, 103, 121, True, 104.0):
            with self.subTest(reserve=reserve), self.assertRaisesRegex(ValueError, "104--120"):
                run(Path("unused"), Path("unused"), Path("unused"), Path("unused"), reserve)

    def test_passing_delivery_reanalyzes_raw_logs_and_requires_complete_steps(self):
        with tempfile.TemporaryDirectory() as temporary:
            attempt = Path(temporary)
            source = attempt / "source/control.cpp"
            source.parent.mkdir()
            source.write_text("source identity")
            (attempt / "probe").write_bytes(b"binary identity")
            contract = {"cases": [self.case()]}
            (attempt / "contract.json").write_text(json.dumps(contract))
            steps = []
            for label, stdout, stderr in (("compile", "", ""),
                                          ("test", self.stdout(), self.stderr())):
                out, err = attempt / (label + ".stdout.txt"), attempt / (label + ".stderr.txt")
                out.write_text(stdout)
                err.write_text(stderr)
                step = {"stdout": str(out), "stderr": str(err), "exit_code": 0, "timed_out": False}
                (attempt / (label + ".resources.json")).write_text(json.dumps(step))
                steps.append({"label": label, **step})
            report = {"status": analysis.PASS, "errors": [], "contract": contract,
                      "steps": steps, "rows": self.rows(), "dependencies": [],
                      "binary_sha256": sha256_file(attempt / "probe"),
                      "source": [{"path": str(source), "sha256": sha256_file(source)}],
                      **dict.fromkeys(analysis.CLAIMS, False)}
            delivery.validate(attempt, report)
            with self.assertRaisesRegex(ValueError, "complete matrix"):
                delivery.validate(attempt, {**report, "steps": steps[:1]})
            Path(steps[0]["stderr"]).write_text("unrecognized diagnostic")
            with self.assertRaisesRegex(ValueError, "unexpected diagnostics"):
                delivery.validate(attempt, report)
            Path(steps[0]["stderr"]).write_text("")
            Path(steps[1]["stdout"]).write_text(self.stdout(self.rows()[:-1]))
            with self.assertRaisesRegex(ValueError, "incomplete"):
                delivery.validate(attempt, report)

    def test_committed_capsules_keep_source_only_passes_and_failures(self):
        root = Path(__file__).resolve().parents[1]
        path = root / ("docs/experiments/comparisons/grasu_regraph_stage_validation/"
                       "evaluation_impact/hardware_validation/complete_pipeline/host_prepared")
        index = delivery.verify(path / "evidence")
        self.assertEqual([r["status"] for r in index["attempts"]],
                         ["FAILED_RETAINED", "FAILED_RETAINED", analysis.PASS])
        self.assertEqual(len(index["attempts"][-1]["rows"]), 42)
        regression = delivery.verify_archive(path / "regression_evidence")
        self.assertEqual([r["status"] for r in regression["attempts"]],
                         ["FAILED_RETAINED", "FAILED_RETAINED",
                          "COMPLETE_G_SOURCE_COMPOSITION_PASS_NOT_INTEGRATED_RTL"])
        self.assertEqual(len(regression["attempts"][-1]["rows"]), 12)

    def test_native_input_extraction_preserves_full_source_outputs(self):
        root = Path(__file__).resolve().parents[1]
        path = root / ("docs/experiments/comparisons/grasu_regraph_stage_validation/"
                       "evaluation_impact/hardware_validation/complete_pipeline/host_prepared")
        record = json.loads((path / "native_input_regression/equivalence.json").read_text())
        before = delivery.verify(path / "evidence")["attempts"][-1]
        after = delivery.verify(path / "native_input_regression")["attempts"][0]
        self.assertEqual(before["rows"], after["rows"])
        self.assertEqual(len(after["rows"]), record["rows_per_attempt"])
        observed = []
        for folder, entry, pin in zip((path / "evidence", path / "native_input_regression"),
                                       (before, after), record["reports"], strict=True):
            with tarfile.open(folder / entry["archive"]) as bundle:
                report_bytes = bundle.extractfile("results.json").read()
                report = json.loads(report_bytes)
                self.assertEqual(hashlib.sha256(report_bytes).hexdigest(), pin["sha256"])
                self.assertEqual(report["binary_sha256"], pin["binary_sha256"])
                self.assertEqual(entry["attempt"], pin["attempt"])
                contract = json.loads(bundle.extractfile("contract.json").read())
                case_data = []
                for case in contract["cases"]:
                    name = case["case"]
                    stdout = bundle.extractfile(name + ".stdout.txt").read()
                    stderr = bundle.extractfile(name + ".stderr.txt").read().decode()
                    analysis.analyze(case, stdout.decode(), stderr)
                    case_data.append((stdout, [stderr.count(w) for w in WARNING_PAIR],
                                      bundle.extractfile("source/inputs/" + Path(case["input"]).name).read()))
                    case["input"] = Path(case["input"]).name
                observed.append((contract, case_data))
        self.assertEqual(observed[0], observed[1])
        for claim in ("rows_identical", "stdout_byte_identical", "classified_diagnostics_identical",
                      "input_bytes_identical", "contracts_identical_after_input_path_relocation"):
            self.assertIs(record[claim], True)


if __name__ == "__main__":
    unittest.main()
