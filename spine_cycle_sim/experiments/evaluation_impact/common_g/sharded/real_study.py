"""Run or package compact real-topology controls using the shared G runner."""

import argparse
from functools import partial
import json
from pathlib import Path

from .delivery import package
from .real_analysis import analyze
from .real_inputs import STATUS, contract
from .study import run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    execute = commands.add_parser("run")
    execute.add_argument("--output", type=Path, required=True)
    execute.add_argument("--core-build", type=Path, required=True)
    deliver = commands.add_parser("package")
    deliver.add_argument("--output", type=Path, required=True)
    deliver.add_argument("--matrix", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "run":
        declared = contract()
        run(args.output.resolve(), args.core_build.resolve(), contract=declared,
            analyze_rows=partial(analyze, contract=declared), target="real_sharded_g_execution",
            tag="REAL_G_RESULT", status=STATUS)
    else:
        report = json.loads(args.matrix.read_text())
        result = package(args.output.resolve(), args.matrix.resolve(), status=STATUS,
                         analyze_rows=partial(analyze, contract=report["contract"]))
        print(json.dumps({key: result[key] for key in ("status", "prediction_rows")}))


if __name__ == "__main__":
    main()
