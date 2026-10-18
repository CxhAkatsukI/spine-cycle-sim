"""Prepare, compile, inspect or experimentally link one declared algorithm."""

import argparse
from pathlib import Path

from . import inputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    prepare = sub.add_parser("prepare")
    for name in ("integration", "grasu", "regraph", "output"):
        prepare.add_argument("--" + name, type=Path, required=True)
    execute = sub.add_parser("execute")
    execute.add_argument("--algorithm", choices=inputs.ALGORITHMS, required=True)
    for name in ("sources", "output", "xilinx", "platform", "compatibility", "shim"):
        execute.add_argument("--" + name, type=Path, required=True)
    review = sub.add_parser("review")
    for name in ("compilation", "storage", "output"):
        review.add_argument("--" + name, type=Path, required=True)
    route = sub.add_parser("route-experiment")
    for name in ("compilation", "storage", "output", "xilinx", "platform", "compatibility", "shim"):
        route.add_argument("--" + name, type=Path, required=True)
    rtl = sub.add_parser("adapter-rtl")
    for name in ("compilation", "storage", "output", "xilinx", "platform", "compatibility", "shim"):
        rtl.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    if args.action == "prepare":
        result = inputs.prepare(args.integration, args.grasu, args.regraph, args.output)
        print("PREPARED_NOT_COMPILED", len(result["files"]))
    elif args.action == "execute":
        from .study import run
        result = run(args.sources, args.output, args.algorithm, args.xilinx,
                     args.platform, args.compatibility, args.shim)
        print(result["status"])
    elif args.action == "review":
        from .review import run
        print(run(args.compilation, args.storage, args.output)["status"])
    elif args.action == "route-experiment":
        from .route_study import run
        print(run(args.compilation, args.storage, args.output, args.xilinx,
                  args.platform, args.compatibility, args.shim)["status"])
    else:
        from .adapter_rtl import run
        print(run(args.compilation, args.storage, args.output, args.xilinx,
                  args.platform, args.compatibility, args.shim)["status"])


if __name__ == "__main__":
    main()
