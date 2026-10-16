"""Prepare and optionally run a diagnostic full-cache G+R link."""

import argparse
import json
from pathlib import Path

from .preparation import LINK_TIMEOUTS, prepare
from .supervisor import run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    names = ("build", "basis", "search", "review", "cache", "composition", "fit", "output")
    for name in names:
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--link-timeout-seconds", type=int, choices=LINK_TIMEOUTS, default=21600)
    args = parser.parse_args()
    prepare(*(getattr(args, name).resolve() for name in names), link_timeout_seconds=args.link_timeout_seconds)
    if args.execute:
        result = run(args.build.resolve(), args.output.resolve())
        print(json.dumps({key: value for key, value in result.items() if key != "resources"}, sort_keys=True))
        return 0 if result["status"] == "LINK_PASS_AWAITING_TIMING_AND_BOARD" else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
