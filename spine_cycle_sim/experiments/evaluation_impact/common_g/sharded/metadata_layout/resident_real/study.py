"""Run or package the declared 18-row resident chronological G study."""

import argparse
from functools import partial
import json
from pathlib import Path

from ...delivery import package
from ...study import run
from .analysis import analyze
from .preparation import STATUS, contract


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    execute = commands.add_parser("run")
    execute.add_argument("--output", required=True, type=Path)
    execute.add_argument("--prepared", required=True, type=Path)
    execute.add_argument("--core-build", required=True, type=Path)
    deliver = commands.add_parser("package")
    deliver.add_argument("--output", required=True, type=Path)
    deliver.add_argument("--matrix", required=True, type=Path)
    args = parser.parse_args()
    if args.command == "run":
        declared = contract(args.prepared.resolve())
        run(args.output.resolve(), args.core_build.resolve(), contract=declared,
            analyze_rows=partial(analyze, contract=declared), target="resident_real_metadata_g_execution",
            tag="RESIDENT_G_RESULT", status=STATUS)
    else:
        report = json.loads(args.matrix.read_text())
        result = package(args.output.resolve(), args.matrix.resolve(), status=STATUS,
                         analyze_rows=partial(analyze, contract=report["contract"]))
        print(json.dumps({key: result[key] for key in ("status", "prediction_rows", "copies_ten_percent_diagnostic_met")}))


if __name__ == "__main__":
    main()
