"""Rebuild both persistent hosts in a fresh directory using retained flags."""

import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess

from . import sources


def rebuild(previous, output):
    previous, output = previous.resolve(), output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    builds = {}
    for arm in ("spine", "gr"):
        target = output / arm
        target.mkdir()
        receipts = [path for path in (previous / arm).glob("*.txt")
                    if "command" in path.name]
        if len(receipts) != 1:
            raise ValueError("expected one retained command receipt for " + arm)
        commands, _ = sources.commands(receipts[0].read_text())
        commands = [[value.replace(str(previous), str(output)) for value in command]
                    for command in commands]
        (target / receipts[0].name).write_text(
            "\n".join(shlex.join(command) for command in commands) + "\n")
        for index, command in enumerate(commands):
            with (target / f"build-{index}.log").open("w") as log:
                subprocess.run(command, check=True, stdout=log,
                               stderr=subprocess.STDOUT, timeout=240)
        dependencies = set()
        for path in target.glob("*.d"):
            dependencies.update(sources.dependencies(path.read_text()))
        (target / "non_system_dependencies.sha256").write_text("".join(
            hashlib.sha256(path.read_bytes()).hexdigest() + "  " + str(path) + "\n"
            for path in sorted(dependencies)))
        binary = target / ("spine_persistent.host" if arm == "spine" else "gr_persistent")
        subprocess.run([str(binary), "--help"], check=True, timeout=10,
                       stdout=subprocess.DEVNULL)
        builds[arm] = dict(binary=str(binary),
                           sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
                           source_files=len(dependencies))
    (output / "build.json").write_text(json.dumps(builds, indent=2) + "\n")
    return builds


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--previous-build", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(rebuild(args.previous_build, args.output), indent=2))
