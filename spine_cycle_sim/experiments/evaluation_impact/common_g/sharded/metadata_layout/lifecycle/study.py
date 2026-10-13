"""Run or package the bounded multi-shard resident metadata lifecycle study."""

import argparse
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
    execute.add_argument("--core-build", required=True, type=Path)
    deliver = commands.add_parser("package")
    deliver.add_argument("--output", required=True, type=Path)
    deliver.add_argument("--matrix", required=True, type=Path)
    args = parser.parse_args()
    if args.command == "run":
        run(args.output.resolve(), args.core_build.resolve(), contract=contract(), analyze_rows=analyze,
            target="resident_metadata_g_execution", tag="RESIDENT_G_RESULT", status=STATUS)
    else:
        package(args.output.resolve(), args.matrix.resolve(), status=STATUS, analyze_rows=analyze)


if __name__ == "__main__":
    main()
