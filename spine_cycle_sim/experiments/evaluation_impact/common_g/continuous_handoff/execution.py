"""Admit the frozen resident G-to-SSSP host through the shared bounded board runner."""

import argparse
import json
from pathlib import Path

from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity
from ..continuous_board.execution import study as board
from . import events
from .analysis import PASS
from .delivery import validate

BOARD_PASS = "CONTINUOUS_GR_BOARD_MATRIX_PASS_NOT_BASELINE_ADMISSION"
BOUNDARY = ("resident old-graph-converged SSSP through host net-policy/packing, G DMA/publication, "
            "seed/fallback DMA, all adapter/R rounds and result readback; diagnostics separate")


def host_identity(preflight):
    report = json.loads((preflight / "results.json").read_text())
    validate(preflight, report)
    if report["status"] != PASS:
        raise ValueError("complete handoff host preflight required before board execution")
    contract = report["contract"]
    if contract.get("algorithm") != "weighted SSSP" or contract.get("source_vertex") != 0 or \
            contract.get("round_limit") != 2048 or contract.get("initial_state") != "old_graph_converged" or \
            contract.get("cache_capacity_per_half") != 131072 or "warm_controls" not in contract:
        raise ValueError("native weighted SSSP warm/fallback contract required")
    source = preflight / "source/continuous_board/xrt.hpp"
    control = preflight / "source/continuous_handoff/control.cpp"
    if 'std::getenv("CONTINUOUS_G_EXPECT_BDF")' not in source.read_text() or \
            "CL_DEVICE_PCIE_BDF" not in source.read_text() or 'device->session.bdf' not in control.read_text():
        raise ValueError("preflight binary lacks the pre-programming and reported device identity guards")
    cases = []
    for case, result in zip(contract["cases"], report["cases"], strict=True):
        if case["case"] != result["case"] or case["partition_vertices"] != 65536 or case["shards"] != 1:
            raise ValueError("single-partition case/preflight identity disagreement")
        cases.append({**case, "expected_active_counts": [row["active_counts"] for row in result["rows"]]})
    return {**report, "contract": {**contract, "cases": cases}}, [identity(preflight / "results.json"),
            identity(preflight / "probe"), *report["source"], *report["dependencies"]]


def run(preflight, route, original, output, *, device=0, repeats=3, execute=False):
    spec = board.Experiment(host_identity, events.analyze, BOARD_PASS, BOUNDARY,
        tuple(Path(__file__).parent / name for name in ("execution.py", "events.py", "analysis.py", "delivery.py")))
    return board.run(preflight, route, original, output, device=device, repeats=repeats,
                     execute=execute, experiment=spec)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("preflight", "route", "original", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--device", type=int, default=0)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    result = run(*(path.resolve() for path in (args.preflight, args.route, args.original, args.output)),
                 device=args.device, repeats=args.repeats, execute=args.execute)
    print(result["status"], flush=True)


if __name__ == "__main__":
    main()
