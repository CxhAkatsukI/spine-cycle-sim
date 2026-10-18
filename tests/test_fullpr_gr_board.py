"""Synthetic G+R FullPR admission tests; no FPGA or compiler execution."""

from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.evaluation_impact.fullgraph_readiness import preparation
from spine_cycle_sim.experiments.evaluation_impact.fullgraph_readiness.board_analysis import BOUNDARY
from spine_cycle_sim.experiments.evaluation_impact.fullgraph_readiness.fullpr_resident import gr, gr_preparation, inputs
from spine_cycle_sim.experiments.evaluation_impact.fullgraph_readiness.fullpr_resident.__main__ import main

BDF = "0000:c1:00.1"
ROW = {"dataset": "SMOKE", "algorithm": inputs.ALGORITHM, "vertices": 4,
       "initial_edges": 3, "updates": 1, "source": 0, "graph": "/cohort/dangling.graph"}
P = gr_preparation.PREFIX
INITIAL = (f"{P}_INPUT vertices=4 static_edges=3 logical_updates=1 physical_updates=1 final_edges=4 "
           "destination_partitions=1 pma_slots_total=256 hbm_graph_allocated_bytes=4096 "
           "damping=0.85 rounds=256 convergence=global_l1 epsilon=1e-6 warm_residual_checked=1")
LAYOUT = "GRASU_SHARDED_UPDATE_LAYOUT shard=0 destination_base=0 updates=1 cache_updates=1 ddr_updates=0"
PREP = (f"{P}_PREP status=PASS vertices=4 destination_partitions=1 pma_slots_total=256 "
        "pma_slots_max_shard=256 rank_sum=1 pma_destination_abi=local_dst19 "
        "k4_frontends=4 shared_regraph_downstream=1 conversion_cost=absent")


def log():
    lines = [f"GRASU_REGRAPH_DEVICE bdf={BDF}", INITIAL, LAYOUT,
             "GRASU_SHARDED_UPDATE_REPEAT_CONFIG repeats=1 restore_pma_between_repeats=1"]
    for r in range(4):
        lines.append(f"{P}_ROUND round={r + 1} l1_error={'9e-7' if r == 3 else '.01'} dangling=.1 active_vertices=4")
        for stage in ("adapter", "gather", "mux", "hbm", "apply") + (("source_prepare",) if r == 0 else ()):
            shard = 0 if stage in ("adapter", "gather", "mux") else -1
            start = 10 + r * 10
            lines.append(f"SHARDED_DEVICE_EVENT stage={stage} round={r} shard={shard} worker={shard} "
                         f"queued_ns=1 submit_ns=2 start_ns={start} end_ns={start + 10}")
    lines += [f"{P}_TIMING device_e2e_ms=.002 setup_inclusive_ms=.004",
              f"{P}_RESULT status=PASS rank_mismatches=0 degree_mismatches=0 max_abs_error=1e-7 "
              "pipeline_executions=4 rounds=4 convergence=global_l1 hardware_converged=1 final_l1_error=2e-6 "
              "probability_mass=1 epsilon=1e-6 vertices=4 final_edges=4 logical_updates=1 physical_updates=1 "
              "destination_partitions=1 k4_frontends=4 shared_regraph_downstream=1 pma_slots_total=256 "
              f"processed_edge_slots_per_execution=256 resident_state=old_graph_converged boundary={BOUNDARY} "
              "conversion_cost=absent"]
    return "\n".join(lines) + "\n"


class GrFullPRTests(unittest.TestCase):
    def test_kernel_revision_check_ignores_readme_only_not_source_or_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def git(*args):
                return subprocess.check_output(["git", *args], cwd=root, text=True).strip()
            def commit():
                git("add", ".")
                git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                    "commit", "-qm", "synthetic kernel identity")
                return git("rev-parse", "HEAD")
            git("init", "-q")
            (root / "kernels").mkdir()
            (root / "include").mkdir()
            for name in ("kernels/README.md", "kernels/core.cpp", "kernels/provenance.json",
                         "kernels/build.cfg", "include/interface.hpp"):
                (root / name).write_text("original\n")
            routed = commit()
            (root / "kernels/README.md").write_text("updated evidence checkpoint\n")
            host = commit()
            gr.verify_kernel_sources(root, routed, host)
            for name in ("kernels/core.cpp", "kernels/provenance.json", "kernels/build.cfg",
                         "include/interface.hpp"):
                (root / name).write_text("different\n")
                with self.subTest(name=name), self.assertRaises(subprocess.CalledProcessError):
                    gr.verify_kernel_sources(root, host, commit())
                (root / name).write_text("original\n")
                host = commit()

    def test_prepare_command_cannot_program_and_has_distinct_macro_and_dependencies(self):
        command = gr_preparation.command(Path("/host"), ROW, Path("/result"))
        self.assertEqual(command, ["/host", "--prepare-only", ROW["graph"], "/result", "--resident-fullpr"])
        compiled = preparation.compile_command(Path("/g++"), Path("/source"), inputs.ALGORITHM,
                                              Path("/binary"), Path("/xrt"), Path("/hls"))
        self.assertIn("-DGRASU_REGRAPH_FULL_PAGERANK=1", compiled)
        self.assertIn("-MD", compiled)
        self.assertIn("-DGRASU_REGRAPH_HOST_ROW_LINE_READ=1", compiled)
        self.assertIn("/source/tools/sharded_k4_pagerank_native_host.cpp", compiled)
        self.assertNotIn("-DGRASU_REGRAPH_RESIDUAL_PAGERANK=1", compiled)
        self.assertEqual(gr_preparation.protocol(Path("/cohort")).algorithms, (inputs.ALGORITHM,))

    def test_cpu_scope_and_all_three_rows_required(self):
        report = gr_preparation.analyze(ROW, "\n".join((INITIAL, LAYOUT, PREP)), "")
        self.assertIn("not_FPGA", report["claim"])
        cases = [{**report, "dataset": name} for name in inputs.DATASETS]
        self.assertEqual(gr_preparation.decision(cases), gr_preparation.PASS)
        for invalid in (cases[:2], cases[::-1], cases + cases[:1],
                        [*cases[:2], {**cases[-1], "status": "FAILED_RETAINED"}]):
            self.assertEqual(gr_preparation.decision(invalid), "FAILED_RETAINED")

    def test_cpu_rejects_fixed_rounds_missing_warm_or_lost_updates(self):
        text = "\n".join((INITIAL, LAYOUT, PREP))
        for old, new in (("warm_residual_checked=1", "warm_residual_checked=0"),
                ("rounds=256", "rounds=3"), ("global_l1", "fixed_rounds"),
                ("local_dst19", "global_dst19"), ("cache_updates=1", "cache_updates=0"),
                ("rank_sum=1", "rank_sum=nan"), ("physical_updates=1", "physical_updates=2"),
                ("final_edges=4", "final_edges=3"),
                ("k4_frontends=4", "k4_frontends=1")):
            with self.subTest(new=new), self.assertRaises(ValueError):
                gr_preparation.analyze(ROW, text.replace(old, new), "")
        with self.assertRaises(ValueError):
            gr_preparation.analyze(ROW, text + "\nGRASU_REGRAPH_DEVICE bdf=" + BDF, "")

    def test_board_keeps_last_sweep_delta_separate_from_cpu_reference_error(self):
        result = gr.analyze(ROW, log(), "", bdf=BDF)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["last_iteration_l1_delta"], 9e-7)
        self.assertEqual(result["final_cpu_reference_l1_error"], 2e-6)
        self.assertEqual(result["resident_wall_ms"], .004)
        self.assertEqual(result["compute_timeline"]["event_count"], 21)
        self.assertEqual(gr.command({"binary": "/host", "candidate": {"path": "/new.xclbin"}}, ROW, "/result"),
                         ["/host", "/new.xclbin", ROW["graph"], "/result", "--resident-fullpr"])

    def test_board_rejects_wrong_geometry_cold_state_bad_mass_and_incomplete_trace(self):
        for old, new in ((BDF, "0000:41:00.1"), ("global_l1", "fixed_rounds"),
                ("rounds=4", "rounds=3"), ("pipeline_executions=4", "pipeline_executions=3"),
                ("processed_edge_slots_per_execution=256", "processed_edge_slots_per_execution=128"),
                ("old_graph_converged", "uniform_fixed_rounds"), ("final_l1_error=2e-6", "final_l1_error=.0003"),
                ("probability_mass=1", "probability_mass=.99"), ("max_abs_error=1e-7", "max_abs_error=nan"),
                ("l1_error=9e-7", "l1_error=2e-6"), ("l1_error=.01", "l1_error=9e-7"),
                ("round=4 l1_error", "round=3 l1_error"), ("setup_inclusive_ms=.004", "setup_inclusive_ms=0"),
                ("SHARDED_DEVICE_EVENT stage=apply round=3", "MISSING stage=apply round=3"),
                ("worker=0 queued_ns=1", "worker=0 worker=0 queued_ns=1"),
                ("status=PASS", "status=PASS status=PASS")):
            with self.subTest(new=new), self.assertRaises(ValueError):
                gr.analyze(ROW, log().replace(old, new), "", bdf=BDF)
        with self.assertRaises(ValueError):
            gr.analyze(ROW, log(), "warning\n", bdf=BDF)

    def test_cli_selects_fullpr_not_legacy_residual_protocol_and_does_not_promote_failure(self):
        owner = "spine_cycle_sim.experiments.evaluation_impact.fullgraph_readiness.fullpr_resident.__main__.board_study.run"
        for status, code in ((gr.PASS, 0), ("FAILED_RETAINED", 1)):
            with patch(owner, return_value={"status": status}) as run:
                self.assertEqual(main(["run-gr", "--preflight", "/preflight", "--admission", "/admission",
                                       "--output", "/unused"]), code)
                self.assertEqual(run.call_args.kwargs["experiment"].name, "new_production_gr_fullpr_resident")


if __name__ == "__main__":
    unittest.main()
