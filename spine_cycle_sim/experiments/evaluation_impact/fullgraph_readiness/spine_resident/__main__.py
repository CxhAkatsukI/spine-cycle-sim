"""Freeze fixed Spine inputs or execute the shared safe convergence matrix."""

import argparse
from pathlib import Path

from .. import board_study, board_protocol, preparation as common
from ..board_analysis import BOUNDARY
from . import analysis, preparation


def environment(device, bdf):
    return {"XCL_DEVICE_INDEX": str(device), "SPINE_EXPECT_BDF": bdf}


def experiment():
    return board_protocol.Experiment("fixed_spine_resident", BOUNDARY, analysis.PASS,
        preparation.prepare, preparation.command, analysis.analyze, environment, False)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    freeze = commands.add_parser("freeze")
    for field in ("spine", "build", "artifacts", "output"):
        freeze.add_argument("--" + field, type=Path, required=True)
    run = commands.add_parser("run")
    for field in ("preflight", "admission", "output"):
        run.add_argument("--" + field, type=Path, required=True)
    run.add_argument("--algorithm", choices=common.ALGORITHMS, required=True)
    run.add_argument("--device", type=int, default=0)
    run.add_argument("--repeats", type=int, default=3)
    run.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    if args.action == "freeze":
        report = preparation.freeze(args.spine.resolve(), args.build.resolve(),
                                    args.artifacts.resolve(), args.output.resolve())
    else:
        report = board_study.run(args.preflight.resolve(), args.admission.resolve(), args.algorithm,
            args.output.resolve(), device=args.device, repeats=args.repeats,
            execute=args.execute, experiment=experiment())
    print(report["status"], flush=True)
    return 0 if report["status"] in (
        preparation.FROZEN, analysis.PASS, "BOARD_PREPARED_NOT_EXECUTED") else 1


if __name__ == "__main__":
    raise SystemExit(main())
