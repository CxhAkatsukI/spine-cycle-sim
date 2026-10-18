"""Export, execute, return and qualify a production link relocation capsule."""

import argparse
from pathlib import Path

from . import admission, capsule, continuation, delivery, qualification, study
from .transport import Remote

parser = argparse.ArgumentParser(description=__doc__)
commands = parser.add_subparsers(dest="command", required=True)
prepare = commands.add_parser("prepare")
prepare.add_argument("--parent", type=Path, required=True)
prepare.add_argument("--output", type=Path, required=True)
execute = commands.add_parser("execute")
for name in ("capsule", "output", "xilinx", "platform", "compatibility"):
    execute.add_argument("--" + name, type=Path, required=True)
seal = commands.add_parser("seal")
for name in ("capsule", "attempt", "output"):
    seal.add_argument("--" + name, type=Path, required=True)
for name in ("unit", "invocation"):
    seal.add_argument("--" + name, required=True)
admit = commands.add_parser("admit")
for name in ("returned", "parent", "original", "output"):
    admit.add_argument("--" + name, type=Path, required=True)
admit.add_argument("--receipt-sha256", required=True)
qualify = commands.add_parser("qualify")
for name in ("native-preflight", "metadata-preflight", "gr-preflight", "returned", "parent", "original", "output"):
    qualify.add_argument("--" + name, type=Path, required=True)
qualify.add_argument("--receipt-sha256", required=True)
qualify.add_argument("--device", type=int, default=0)
qualify.add_argument("--repeats", type=int, default=3)
qualify.add_argument("--execute", action="store_true", required=True)
follow = commands.add_parser("follow")
for name in ("native-preflight", "metadata-preflight", "gr-preflight", "parent", "original", "output",
             "remote-runner", "remote-capsule", "remote-attempt", "remote-returned"):
    follow.add_argument("--" + name, type=Path, required=True)
for name in ("target", "route-unit", "route-invocation"):
    follow.add_argument("--" + name, required=True)
follow.add_argument("--port", type=int, default=22)
follow.add_argument("--device", type=int, default=0)
follow.add_argument("--repeats", type=int, default=3)
follow.add_argument("--maximum-wait", type=float, default=133200)
follow.add_argument("--poll-seconds", type=float, default=30)
follow.add_argument("--execute", action="store_true", required=True)
args = parser.parse_args()
if args.command == "prepare":
    packet = capsule.prepare(args.parent.resolve(), args.output.resolve())
    print("PREPARED_RELOCATION_NOT_ROUTED", packet["parent"]["sha256"], flush=True)
elif args.command == "execute":
    print(study.run(*(getattr(args, name).resolve() for name in
        ("capsule", "output", "xilinx", "platform", "compatibility")))["status"], flush=True)
elif args.command == "seal":
    result = delivery.seal(args.capsule.resolve(), args.attempt.resolve(), args.output.resolve(),
                           unit=args.unit, invocation=args.invocation)
    print(result["sha256"], flush=True)
elif args.command == "admit":
    print(admission.review(args.returned.resolve(), args.original.resolve(), args.output.resolve(),
        parent_directory=args.parent.resolve(), receipt_sha256=args.receipt_sha256)["status"], flush=True)
elif args.command == "qualify":
    print(qualification.run(*(getattr(args, name).resolve() for name in (
        "native_preflight", "metadata_preflight", "gr_preflight", "returned", "original", "output")),
        parent_directory=args.parent.resolve(), receipt_sha256=args.receipt_sha256,
        device=args.device, repeats=args.repeats)["status"], flush=True)
else:
    remote = Remote(args.target, args.port, args.remote_runner, args.remote_capsule, args.remote_attempt,
                    args.remote_returned, args.route_unit, args.route_invocation)
    print(continuation.run(remote, *(getattr(args, name).resolve() for name in (
        "native_preflight", "metadata_preflight", "gr_preflight", "parent", "original", "output")),
        device=args.device, repeats=args.repeats, maximum_wait=args.maximum_wait,
        poll_seconds=args.poll_seconds)["status"], flush=True)
