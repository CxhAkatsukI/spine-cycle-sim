"""Fresh figure data requires complete pairs, explicit scope and finite energy."""

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.evaluation_impact.figure_refresh import analysis, delivery, matrix, tables


class FigureRefreshTests(unittest.TestCase):
    def test_export_uses_repository_lf_line_endings(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "table.csv"
            tables.write_csv(path, [dict(dataset="AU", value=1)])
            self.assertEqual(path.read_bytes(), b"dataset,value\nAU,1\n")

    def test_declared_matrix_does_not_invent_algorithm_support(self):
        manifest = dict(graphs=dict(directed=dict(path="graph", vertices=100, records=200,
            source_cohorts=dict(default=0))), updates=[dict(user_mutations=n,
                projection="directed", scenario="insert", path=f"updates{n}")
                for n in (8, 64, 512, 4096)])
        with patch.object(Path, "read_text", return_value=json.dumps(manifest)):
            rows = matrix.cases()
        self.assertEqual(len(rows), 10)
        self.assertEqual(sum(r["figure"] == 8 for r in rows), 7)
        self.assertEqual({r["algorithm"] for r in rows if r["figure"] == 9}, {"SSSP"})
        self.assertEqual({r["dataset"]: r["root"] for r in rows if r["figure"] == 9},
                         {"AU": 11, "SU": 23, "WK": 0})
        missing = matrix.unsupported()
        self.assertEqual(len(missing), 6)
        self.assertEqual({r["algorithm"] for r in missing}, {"CC", "ResPR"})

    def test_process_and_correctness_gates(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "stdout"
            row = dict(cycles=10, read_bytes=64, write_bytes=0,
                       correctness=True, ledger_closed=True)
            step = dict(exit_code=0, timed_out=False, stdout=str(output))
            def write(marker=True):
                output.write_text("WARM_RESULT " + json.dumps(row) + "\n" +
                                  ("REFRESH_COMPLETE\n" if marker else ""))
            write()
            self.assertEqual(analysis.device(step), row)
            write(False)
            with self.assertRaisesRegex(ValueError, "completion"):
                analysis.device(step)
            write()
            step["timed_out"] = True
            with self.assertRaisesRegex(ValueError, "timed out"):
                analysis.device(step)
            step["timed_out"] = False
            row["ledger_closed"] = False
            write()
            with self.assertRaisesRegex(ValueError, "ledger"):
                analysis.device(step)

    def test_host_requires_repetitions_and_stable_payload(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "stdout"
            rows = [dict(repeat=i, nanoseconds=i + 1, initial_h2d_bytes=120,
                         update_h2d_bytes=16, bootstrap_complete=True,
                         batch_preparation_complete=True) for i in range(5)]
            step = dict(exit_code=0, timed_out=False, stdout=str(output))
            def write():
                output.write_text("\n".join("HOST_RESULT " + json.dumps(r) for r in rows) +
                                  "\nREFRESH_COMPLETE\n")
            write()
            self.assertEqual(analysis.host(step)["median_ns"], 3)
            rows[0]["bootstrap_complete"] = False
            write()
            with self.assertRaisesRegex(ValueError, "bootstrap"):
                analysis.host(step)
            rows[0]["bootstrap_complete"] = True
            rows[0]["batch_preparation_complete"] = False
            write()
            with self.assertRaisesRegex(ValueError, "batch preparation"):
                analysis.host(step)
            rows[0]["batch_preparation_complete"] = True
            rows[0]["nanoseconds"] = -1
            write()
            with self.assertRaisesRegex(ValueError, "finite"):
                analysis.host(step)
            rows[0]["nanoseconds"] = 1
            rows[1]["initial_h2d_bytes"] += 1
            write()
            with self.assertRaisesRegex(ValueError, "transfer sizes"):
                analysis.host(step)
            rows.pop()
            write()
            with self.assertRaisesRegex(ValueError, "five"):
                analysis.host(step)

    def test_spine_host_requires_complete_constructor_payload_accounting(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "stdout"
            rows = [dict(arm="spine", repeat=i, nanoseconds=100, initial_h2d_bytes=120,
                update_h2d_bytes=16, bootstrap_complete=True, batch_preparation_complete=True,
                graph_bytes=100, directory_bytes=10, metadata_bytes=10,
                constructor_payload_calls=3) for i in range(5)]
            step = dict(exit_code=0, timed_out=False, stdout=str(output))
            def write():
                output.write_text("\n".join("HOST_RESULT " + json.dumps(r) for r in rows) +
                                  "\nREFRESH_COMPLETE\n")
            write()
            self.assertEqual(analysis.host(step)["initial_h2d_bytes"], 120)
            rows[0]["directory_bytes"] = 9
            write()
            with self.assertRaisesRegex(ValueError, "conserve bytes"):
                analysis.host(step)

    def test_energy_requires_all_budget_channels(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            for channel in range(32):
                path = directory / "dram" / f"channel{channel}" / "dramsim3.json"
                path.parent.mkdir(parents=True)
                path.write_text(json.dumps({"0": {"total_energy": 2}}))
            self.assertEqual(analysis.energy(directory), 64)
            path.write_text(json.dumps({"0": {"total_energy": float("inf")}}))
            with self.assertRaisesRegex(ValueError, "invalid"):
                analysis.energy(directory)
            path.unlink()
            with self.assertRaisesRegex(ValueError, "32"):
                analysis.energy(directory)

    def test_setup_and_memory_ratios_use_both_complete_arms(self):
        arm = dict(cycles=150, read_bytes=64, write_bytes=64, energy_pj=10,
                   host=dict(median_ns=1000, initial_h2d_bytes=12000, update_h2d_bytes=0))
        arms = dict(spine=copy.deepcopy(arm), gr=copy.deepcopy(arm))
        case = dict(figure=8, dataset="AU", algorithm="update_only", updates=512)
        row = analysis.comparison(case, arms)
        self.assertAlmostEqual(row["speedup"], 1)
        self.assertAlmostEqual(row["spine"]["setup_inclusive_seconds"], 13e-6)
        arms["gr"].update(read_bytes=192, energy_pj=30)
        case.update(figure=9, algorithm="SSSP", updates=8)
        row = analysis.comparison(case, arms)
        self.assertEqual(row["accepted_bytes_ratio"], 2)
        self.assertEqual(row["hbm_energy_ratio"], 3)
        self.assertFalse(row["baseline_admitted"])

    def test_energy_components_must_close(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            values = dict(act_energy=1, act_stb_energy={"0": 2}, pre_stb_energy={"0": 3},
                read_energy=4, write_energy=5, ref_energy=6, refb_energy=7, sref_energy={"0": 8},
                total_energy=36, num_read_cmds=2, num_write_cmds=3)
            for channel in range(32):
                path = directory / "dram" / f"channel{channel}" / "dramsim3.json"
                path.parent.mkdir(parents=True)
                path.write_text(json.dumps({"0": values}))
            details = analysis.energy_details(directory)
            self.assertEqual(details["total_energy_pj"], 1152)
            self.assertEqual(details["act_stb_energy_pj"], 64)
            self.assertEqual(details["num_write_cmds"], 96)
            values["total_energy"] = 35
            path.write_text(json.dumps({"0": values}))
            with self.assertRaisesRegex(ValueError, "conserve"):
                analysis.energy_details(directory)

    def test_default_source_cannot_be_delivered_as_historical(self):
        with tempfile.TemporaryDirectory() as temp:
            empty = Path(temp) / "empty.json"
            wrong = Path(temp) / "wrong.json"
            report = dict(pins_unchanged=True, baseline_admitted=False, status="COMPLETE_SUPPORTED_SCOPE",
                          matrix=[], rows=[])
            empty.write_text(json.dumps(report))
            report["matrix"] = [dict(figure=9, dataset="AU", updates=8, algorithm="SSSP", root=15811)]
            wrong.write_text(json.dumps(report))
            with self.assertRaisesRegex(ValueError, "historical source"):
                tables.selected(empty, empty, wrong)

    def test_old_incomplete_setup_cannot_be_selected(self):
        with tempfile.TemporaryDirectory() as temp:
            report = Path(temp) / "report.json"
            case = dict(figure=8, dataset="AU", updates=512, algorithm="update_only")
            row = dict(**case, status="PREDICTION_ONLY", spine={}, gr={})
            data = dict(pins_unchanged=True, baseline_admitted=False,
                status="COMPLETE_SUPPORTED_SCOPE", matrix=[case], rows=[row])
            def write():
                report.write_text(json.dumps(data))
            write()
            with self.assertRaisesRegex(ValueError, "physical Spine"):
                tables.selected(report, report, report)
            row["spine"] = dict(physical_image_checked=True, host=dict(samples=[]))
            write()
            with self.assertRaisesRegex(ValueError, "complete bootstrap and batch"):
                tables.selected(report, report, report)

    def test_equivalence_checks_states_and_counters_not_only_completion(self):
        with tempfile.TemporaryDirectory() as temp:
            before, after = (Path(temp) / name for name in ("before.json", "after.json"))
            rows = [dict(workload=w, latency=l, arm=a, reverse=r, input=dict(vertices=3),
                result=dict(cycles=9, read_bytes=64), state_hashes=dict(final="digest"))
                for w in ("smoke", "amazon") for l in (64, 128)
                for a, r in (("spine", 0), ("gr", 0), ("gr", 1))]
            report = dict(rows=rows, pins_unchanged=True, failures=[])
            before.write_text(json.dumps(report))
            after.write_text(json.dumps(report))
            self.assertEqual(delivery.equivalence(before, after)["status"], "EXACT_TWELVE_EXECUTION_REPLAY")
            rows[0]["result"]["cycles"] += 1
            after.write_text(json.dumps(report))
            with self.assertRaisesRegex(ValueError, "changed result"):
                delivery.equivalence(before, after)


if __name__ == "__main__":
    unittest.main()
