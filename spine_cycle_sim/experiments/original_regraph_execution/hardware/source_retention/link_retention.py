"""Check the generated Vitis link command before spending a routing run."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import shlex


def validate(plan, *, image, temp, cache):
    commands = []
    for line in plan.replace("\\\n", " ").splitlines():
        words = shlex.split(line)
        if words and Path(words[0]).name == "v++":
            commands.append(words)
    if len(commands) != 1 or commands[0].count("-l") != 1:
        raise ValueError("expected exactly one Vitis link and no XO compilation")
    command = commands[0]
    if command.count("--save-temps") != 1 or "-c" in command:
        raise ValueError("the link itself must retain temporary evidence")
    for flag, expected in (("-o", image), ("--temp_dir", temp),
                           ("--remote_ip_cache", cache)):
        if command.count(flag) != 1:
            raise ValueError(f"link must declare exactly one {flag}")
        index = command.index(flag) + 1
        if index == len(command) or Path(command[index]) != expected:
            raise ValueError(f"link {flag} differs from the frozen path")
    return dict(status="LINK_RETENTION_PLAN_PASS_NOT_BUILD_COMPLETION",
                plan_sha256=sha256(plan.encode()).hexdigest(), command=command,
                image=str(image), temp=str(temp), cache=str(cache))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--temp", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(validate(args.plan.read_text(), image=args.image,
                              temp=args.temp, cache=args.cache), indent=2))


if __name__ == "__main__":
    main()
