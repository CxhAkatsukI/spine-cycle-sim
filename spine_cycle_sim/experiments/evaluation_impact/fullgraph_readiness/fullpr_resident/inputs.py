"""Freeze a predeclared directed FullPR scope without external ID compaction."""

import json
from pathlib import Path
import shutil

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from .. import board_preparation, preparation

ALGORITHM = "full_pagerank"
DATASETS = ("AU", "SU", "WK")
FROZEN = "FULLPR_INPUTS_PINNED_NOT_CPU_OR_BOARD_VALIDATED"


def freeze(manifest, output):
    output.mkdir(parents=True, exist_ok=False)
    rows = preparation.matrix(manifest)
    selected = [{**row, "origin_algorithm": row["algorithm"], "algorithm": ALGORITHM}
                for row in rows if row["algorithm"] == "weighted_sssp" and row["dataset"] in DATASETS]
    if [row["dataset"] for row in selected] != list(DATASETS):
        raise ValueError("exact predeclared AU/SU/WK directed input scope required")
    fixture = Path(__file__).parent / "fixtures/dangling.graph"
    smoke_path = output / "dangling.smoke.graph"
    shutil.copy2(fixture, smoke_path)
    smoke = {"dataset": "SMOKE", "algorithm": ALGORITHM, "vertices": 4, "initial_edges": 3,
             "updates": 1, "source": 0, "graph": str(smoke_path)}
    pins = board_preparation.stamp_pins([preparation.identity(manifest), preparation.identity(fixture),
            preparation.identity(smoke_path), *[row["input_identity"] for row in selected]])
    report = {"status": FROZEN, "rows": selected, "smoke": smoke, "pins": pins,
              "semantics": {"initial_state": "old_graph_converged", "damping": .85,
                  "convergence": "global_l1", "epsilon": 1e-6, "limit": 256,
                  "edge_weights": "ignored", "dangling": "global_uniform_redistribution",
                  "vertex_id_transform": "none", "old_rank_warm_sweeps": 128},
              "scope": "three_complete_directed_inputs_not_eight_graphs_or_compact_FPGA",
              "board_programmed": False}
    atomic_write_json(output / "results.json", report)
    return report


def load(directory):
    path = directory / "results.json"
    report = json.loads(path.read_text())
    if report.get("status") != FROZEN or report.get("board_programmed") is not False or \
            [row["dataset"] for row in report["rows"]] != list(DATASETS) or \
            any(row["algorithm"] != ALGORITHM for row in [report["smoke"], *report["rows"]]):
        raise ValueError("complete frozen FullPR cohort required")
    pins = board_preparation.stamp_pins([*report["pins"], preparation.identity(path)])
    return report, pins
