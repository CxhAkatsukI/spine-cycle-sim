"""Replay the paired host outputs without treating a CPU preflight as device work."""

import json
from pathlib import Path
import subprocess
import sys

from spine_cycle_sim.experiments.evaluation_impact.fullgraph_readiness.board_analysis import single
from spine_cycle_sim.experiments.evaluation_impact.fullgraph_readiness.spine_resident.analysis import (
    analyze as spine_analysis,
)


PREFIX = "RESIDUAL_PR_PMA_NATIVE_SHARDED"
COMPARATOR_SHA256 = "0fcd0d63aab314b90e957ede40cad53fa9f257199ad9f9bb4e8ce8eca9709b3f"


def validate_gr(case, text, bdf):
    lines = text.splitlines()
    if single(lines, "GRASU_REGRAPH_DEVICE") != {"bdf": bdf}:
        raise ValueError("G+R did not use the leased board")
    record = single(lines, PREFIX + "_INPUT")
    repeats = single(lines, "GRASU_SHARDED_UPDATE_REPEAT_CONFIG")
    if any(repeats.get(key) != "1" for key in ("repeats", "restore_pma_between_repeats", "restore_degree")):
        raise ValueError("one update of the restored initial PMA and degree state required")
    expected = {"vertices": case["vertices"], "static_edges": case["edges"],
                "logical_updates": case["updates"], "physical_updates": case["updates"],
                "final_edges": case["edges"] + case["updates"], "damping": "0.85",
                "threshold_semantics": "direct_per_vertex", "oracle_converged": 1}
    if any(record.get(key) != str(value) for key, value in expected.items()) or float(record["epsilon"]) != 1e-6:
        raise ValueError("G+R workload or numeric policy differs from the frozen case")
    result = single(lines, PREFIX + "_RESULT")
    rounds = int(result["propagation_rounds"])
    if (not 0 <= rounds <= 256 or int(result["pipeline_executions"]) != rounds + 1
            or result["final_edges"] != record["final_edges"]
            or not 0 < int(record["pma_slots_total"]) == int(result["pma_slots_total"])
            == int(result["processed_edge_slots_per_execution"])):
        raise ValueError("G+R execution count, final graph or slot conservation differs")


def analyze(case, rows, comparator, output, bdf):
    logs = {arm: Path(row["stdout"]["path"]) for arm, row in rows.items()}
    spine = spine_analysis(case, logs["spine"].read_text(),
                           Path(rows["spine"]["stderr"]["path"]).read_text(), bdf=bdf)
    validate_gr(case, logs["gr"].read_text(), bdf)
    path = output / "pair.json"
    subprocess.run([sys.executable, str(comparator), "--algorithm", case["algorithm"],
                    "--source", str(case["source"]), "--gr-log", str(logs["gr"]),
                    "--spine-log", str(logs["spine"]), "--output", str(path)],
                   check=True, timeout=30)
    pair = json.loads(path.read_text())
    if pair["spine_rounds"] != spine["iterations"]:
        raise ValueError("paired and Spine-specific analyzers disagree")
    gr_rounds, spine_rounds = pair["gr_rounds"], pair["spine_rounds"]
    pair["equal_propagation_rounds"] = gr_rounds == spine_rounds
    pair["positive_propagation_on_both"] = min(gr_rounds, spine_rounds) > 0
    pair["meets_propagation_screen"] = (not case["requires_propagation"]
                                         or pair["positive_propagation_on_both"])
    return pair
