"""Prepare a fresh attempt, or supervise it inside a memory-bounded unit."""

import argparse
import json
from pathlib import Path

from .preparation import prepare
from .supervisor import run


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "supervise"))
    for key in ("build", "output"):
        parser.add_argument("--" + key, type=Path, required=True)
    for key in ("basis", "study", "host", "integration"):
        parser.add_argument("--" + key, type=Path)
    args = parser.parse_args(argv)
    if args.action == "prepare":
        names = ("build", "basis", "study", "host", "integration", "output")
        if any(getattr(args, name) is None for name in names):
            parser.error("prepare requires basis, study, host and integration")
        result = prepare(**{name: getattr(args, name).resolve() for name in names})
        print(json.dumps({"status": result["status"], "candidate_xo": result["candidate_xo"]}))
        return 0
    result = run(args.build.resolve(), args.output.resolve())
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "LINK_PASS_AWAITING_TIMING_AND_BOARD" else 2


if __name__ == "__main__":
    raise SystemExit(main())
