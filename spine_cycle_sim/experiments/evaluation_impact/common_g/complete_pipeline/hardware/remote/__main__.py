"""Export or execute a production link relocation capsule."""

import argparse
from pathlib import Path

from . import capsule, study

parser = argparse.ArgumentParser(description=__doc__)
commands = parser.add_subparsers(dest="command", required=True)
prepare = commands.add_parser("prepare")
prepare.add_argument("--parent", type=Path, required=True)
prepare.add_argument("--output", type=Path, required=True)
execute = commands.add_parser("execute")
for name in ("capsule", "output", "xilinx", "platform", "compatibility"):
    execute.add_argument("--" + name, type=Path, required=True)
args = parser.parse_args()
if args.command == "prepare":
    packet = capsule.prepare(args.parent.resolve(), args.output.resolve())
    print("PREPARED_RELOCATION_NOT_ROUTED", packet["parent"]["sha256"], flush=True)
else:
    print(study.run(*(getattr(args, name).resolve() for name in
        ("capsule", "output", "xilinx", "platform", "compatibility")))["status"], flush=True)
