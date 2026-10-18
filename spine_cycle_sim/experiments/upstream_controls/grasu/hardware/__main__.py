"""Prepare or build a byte-exact original-G U55C control, never a board test."""

import argparse
from pathlib import Path

from . import preparation, study


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    prepare = sub.add_parser("prepare")
    for name in ("root", "upstream", "packet"):
        prepare.add_argument("--" + name, type=Path, required=True)
    build = sub.add_parser("build")
    for name in ("packet", "output", "environment-root", "xilinx", "platform", "compatibility"):
        build.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args(argv)
    if args.action == "prepare":
        result = preparation.prepare(args.root.resolve(), args.upstream.resolve(), args.packet.resolve())
        print("ORIGINAL_G_PACKET_PREPARED", len(result), flush=True)
    else:
        result = study.run(args.packet.resolve(), args.output.resolve(), args.environment_root.resolve(),
                           args.xilinx.resolve(), args.platform.resolve(), args.compatibility.resolve())
        print(result["status"], flush=True)


if __name__ == "__main__":
    main()
