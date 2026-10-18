"""Freeze a separate FullPR cohort and run the shared bounded board executor."""

import argparse
from pathlib import Path

from .. import board_study
from . import inputs, spine


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    cohort = commands.add_parser("inputs")
    cohort.add_argument("--manifest", type=Path, required=True)
    cohort.add_argument("--output", type=Path, required=True)
    freeze = commands.add_parser("freeze-spine")
    for field in ("source", "build", "artifacts", "output"):
        freeze.add_argument("--" + field, type=Path, required=True)
    run = commands.add_parser("run-spine")
    for field in ("preflight", "admission", "output"):
        run.add_argument("--" + field, type=Path, required=True)
    run.add_argument("--device", type=int, default=1)
    run.add_argument("--repeats", type=int, default=3)
    run.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    if args.action == "inputs":
        report = inputs.freeze(args.manifest.resolve(), args.output.resolve())
    elif args.action == "freeze-spine":
        report = spine.freeze(args.source.resolve(), args.build.resolve(), args.artifacts.resolve(),
                              args.output.resolve())
    else:
        report = board_study.run(args.preflight.resolve(), args.admission.resolve(), inputs.ALGORITHM,
            args.output.resolve(), device=args.device, repeats=args.repeats, execute=args.execute,
            experiment=spine.experiment())
    print(report["status"], flush=True)
    return 0 if report["status"] in (
        inputs.FROZEN, spine.FROZEN, spine.PASS, "BOARD_PREPARED_NOT_EXECUTED") else 1


if __name__ == "__main__":
    raise SystemExit(main())
