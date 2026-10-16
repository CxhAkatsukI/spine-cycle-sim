"""Use the existing routed admission, runtime identity and exclusive lease for native G."""

import argparse
import json
from pathlib import Path

from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity
from ..continuous_board.execution.study import Experiment, run
from . import analysis, delivery, preparation


def host_identity(preflight):
    report = json.loads((preflight / "results.json").read_text())
    delivery.validate(preflight, report)
    if report["status"] != analysis.PASS or report["contract"]["cases"] != [preparation.CASE]:
        raise ValueError("complete native host preflight required")
    source = (preflight / "source/continuous_board/xrt.hpp").read_text()
    if 'std::getenv("CONTINUOUS_G_EXPECT_BDF")' not in source or "CL_DEVICE_PCIE_BDF" not in source or \
            source.index("CL_DEVICE_PCIE_BDF") > source.index("cl::Program(context"):
        raise ValueError("pre-programming board identity guard missing")
    return report, [identity(preflight / "results.json"), identity(preflight / "probe"), *report["pins"]]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("preflight", "route", "original", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--device", type=int, default=0)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    experiment = Experiment(host_identity, analysis.analyze, "NATIVE_G_BOARD_MATRIX_PASS_NOT_BASELINE_ADMISSION",
        "isolated native five-shard hot/cold G ready-to-handoff; not algorithm convergence or original-G match",
        tuple(sorted(Path(__file__).parent.glob("*.py"))))
    report = run(*(path.resolve() for path in (args.preflight, args.route, args.original, args.output)),
                 device=args.device, repeats=args.repeats, execute=args.execute, experiment=experiment)
    print(report["status"], flush=True)


if __name__ == "__main__":
    main()
