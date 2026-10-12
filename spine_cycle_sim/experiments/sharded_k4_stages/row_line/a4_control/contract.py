"""Fixed scope and historical identities; no fitted timing parameters."""

from pathlib import Path

from spine_cycle_sim.experiments.original_regraph_execution.sssp_partition_round.analysis import MATRIX

DOC = Path("docs/experiments/comparisons/grasu_regraph_stage_validation/actual_sharded_k4")
BASES = {
    "partition": ("matched_a4/sssp_partition_round/evidence/results.json",
                  "54ef87271652f4bb35096799d92940667a18fbfd53d900731105c4e02dca8206"),
    "numerical": ("matched_a4/sssp_real_round/evidence/results.json",
                  "2d459d2bb54ac4b71059a8023ccc5c71a7ac9c337521e11a226177e977d46784"),
    "sensitivity": ("adapter_optimization/empty_segment/sensitivity/evidence/results.json",
                    "d9bf7cc5b4c150ae52ab00877310f3c28319d27cae2093163fb02ab1b5cdf2a4"),
}
EXTRACTION_SHA = "e5ea73399606cf911964e516bddfd74936076c9b462064069e5c268963b07a36"
NUMERICAL_CHANGES = {"cpp/include/spine_sim/regraph_pma_adapter.hpp", "cpp/src/regraph_pma_adapter.cpp"}
HARNESS_CHANGE = "cpp/tests/routed_regraph/empty_segment/round.cpp"
HARNESS = Path("cpp/tests/routed_regraph/row_line")
ARMS = {"skip_empty": (0, 0), "whole_line": (0, 1)}
BOUNDARY = "resident_input_first_component_tick_to_all_state_write_acknowledgements_one_round"
STATUS = "passed_whole_line_A4_model_control_not_FPGA_or_resource_match"
LIMITS = {"max_cycles": 100000000, "reserve_gib": 16, "build_tree_gib": 6,
          "run_tree_gib": 3, "run_timeout_seconds": 180, "outer_tree_gib": 8,
          "outer_timeout_seconds": 1800, "affinity": "112-113", "parallel_workers": 1}
TARGETS = ("original_regraph_sssp_real_round", "routed_regraph_empty_segment_round",
           "routed_regraph_row_line_round")


def label(mode, latency, reverse, arm):
    return f"{mode}_lat{latency}_reverse{reverse}_{arm}"


def run_specs():
    return [(mode, latency, reverse, arm) for mode, latency, reverse in MATRIX
            for arm in ("original", "legacy_extracted", *ARMS)]
