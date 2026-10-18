"""Explicit local vendor installation and platform closure, not historical PATH."""

import os
from pathlib import Path
import shutil
import subprocess

from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity
from spine_cycle_sim.experiments.sharded_k4_stages.empty_segment.route_environment.contract import (
    LICENSE_KEYS, SEARCH_PATHS, public_environment,
)


def capture(root, output, xilinx, platform, compatibility):
    settings = [xilinx / name / "2024.1/settings64.sh" for name in ("Vitis", "Vivado", "Vitis_HLS")]
    scripts = [*settings]
    for path in settings:
        for line in path.read_text().splitlines():
            if line.strip() and not line.startswith("#") and line.strip() != "exit":
                # Freeze the literal component loaders as well as their public wrappers.
                if line.startswith("source "):
                    scripts.append(Path(line.split(maxsplit=1)[1].strip('"')))
    before = [identity(path) for path in scripts]
    base = {"PATH": "/usr/bin:/bin", "HOME": str(Path.home()), "LANG": "C", "LC_ALL": "C"}
    base.update({key: os.environ[key] for key in ("USER", "LOGNAME", *LICENSE_KEYS) if key in os.environ})
    captured = subprocess.run(["/bin/bash", "--noprofile", "--norc", "-c",
        'set -eo pipefail; source "$1" >/dev/null; /usr/bin/env -0', "remote-route", str(settings[0])],
        env=base, capture_output=True, check=True, timeout=30)
    environment = dict(item.decode().split("=", 1) for item in captured.stdout.split(b"\0") if item)
    for key in ("PWD", "SHLVL", "_"):
        environment.pop(key, None)
    environment.update(SEARCH_PATHS)
    environment.update({key: str(output / "tmp") for key in ("TMPDIR", "TMP", "TEMP")})
    environment["XILINX_VITIS_DATA_DIR"] = str(output / "user-data")
    environment["CPLUS_INCLUDE_PATH"] = str(root / "gcc_compat")
    libraries = [compatibility / name for name in ("lib/x86_64-linux-gnu", "usr/lib/x86_64-linux-gnu")]
    if not all(path.is_dir() for path in libraries):
        raise ValueError("reviewed 2024.1 compatibility library directories required")
    environment["LD_LIBRARY_PATH"] = ":".join(map(str, libraries)) + ":" + environment.get("LD_LIBRARY_PATH", "")
    tools = {}
    for name in ("v++", "vivado", "gcc", "g++"):
        found = shutil.which(name, path=environment["PATH"])
        if found is None:
            raise ValueError("missing remote tool: " + name)
        tools[name] = {"invocation": found, **identity(Path(found))}
    if tools["v++"]["invocation"] != str(xilinx / "Vitis/2024.1/bin/v++"):
        raise ValueError("another Vitis installation selected")
    platform_files = [path for path in sorted(platform.parent.rglob("*")) if path.is_file()]
    if platform not in platform_files or len(platform_files) > 10000:
        raise ValueError("bounded complete platform directory required")
    compatibility_files = [path for path in sorted(compatibility.rglob("*")) if path.is_file()]
    if len(compatibility_files) > 10000:
        raise ValueError("bounded compatibility installation required")
    pins = [*before, identity(root / "gcc_compat/bits/gthr-default.h"),
            *[identity(Path(tool["invocation"])) for tool in tools.values()],
            *map(identity, platform_files), *map(identity, compatibility_files)]
    if [identity(path) for path in scripts] != before:
        raise ValueError("settings changed during capture")
    return environment, {"contract": "remote_explicit_2024.1_installation",
        "effective": public_environment(environment), "tools": tools, "pins": pins,
        "scope": "settings/loaders/launchers/host_compilers/platform/compatibility, not all vendor executables"}
