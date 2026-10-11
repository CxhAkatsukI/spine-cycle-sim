"""Reconstruct the frozen script's environment without executing its link command."""

import hashlib
import os
from pathlib import Path
import shlex
import shutil
import subprocess

from ...execution import identity

SETTINGS = Path("/data/yxx/tools/xilinx/Vitis/2024.1/settings64.sh")
LICENSE_KEYS = ("LM_LICENSE_FILE", "XILINXD_LICENSE_FILE")
SEARCH_PATHS = {
    "CPATH": "/usr/include/x86_64-linux-gnu:/usr/include",
    "C_INCLUDE_PATH": "/usr/include/x86_64-linux-gnu:/usr/include",
    "LIBRARY_PATH": "/usr/lib/x86_64-linux-gnu:/lib/x86_64-linux-gnu",
    "COMPILER_PATH": "/usr/bin",
}


def require_prefix(build: Path) -> list[Path]:
    lines = (build / "link_command.sh").read_text().splitlines()
    positions = [i for i, line in enumerate(lines) if line.startswith("v++ ")]
    exports = {"TMPDIR": str(build / "tmp"), "TMP": str(build / "tmp"), "TEMP": str(build / "tmp")}
    exports.update(SEARCH_PATHS)
    exports["CPLUS_INCLUDE_PATH"] = str(build / "gcc_compat")
    expected = ["#!/usr/bin/env bash", "set -euo pipefail", "source " + str(SETTINGS)]
    for key in ("TMPDIR", "TMP", "TEMP", "CPATH", "C_INCLUDE_PATH", "CPLUS_INCLUDE_PATH",
                "LIBRARY_PATH", "COMPILER_PATH"):
        suffix = "" if key in ("TMPDIR", "TMP", "TEMP") else "${" + key + ":+:${" + key + "}}"
        expected.append(f"export {key}={exports[key]}{suffix}")
    if len(positions) != 1 or lines[:positions[0]] != expected or positions[0] != len(lines) - 1:
        raise ValueError("frozen link shell prefix differs; environment contract needs review")
    scripts = [SETTINGS]
    for line in SETTINGS.read_text().splitlines():
        if line.strip() and not line.startswith("#"):
            tokens = shlex.split(line)
            if len(tokens) != 2 or tokens[0] != "source" or not Path(tokens[1]).is_absolute():
                raise ValueError("settings loader is no longer a literal source list")
            scripts.append(Path(tokens[1]))
    if any("source " in line or line.lstrip().startswith(". ")
           for path in scripts[1:] for line in path.read_text().splitlines() if not line.startswith("#")):
        raise ValueError("nested settings source requires explicit dependency review")
    return [build / "link_command.sh", build / "gcc_compat/bits/gthr-default.h", *scripts]


def public_environment(environment: dict[str, str]) -> dict:
    return {"values": {k: v for k, v in sorted(environment.items()) if k not in LICENSE_KEYS},
            "license_value_sha256": {k: hashlib.sha256(environment[k].encode()).hexdigest()
                                     for k in LICENSE_KEYS if k in environment}}


def reconstruct(build: Path, output: Path) -> tuple[dict, dict]:
    paths = require_prefix(build)
    before = [identity(path) for path in paths]
    base = {"PATH": "/usr/bin:/bin", "HOME": os.environ["HOME"], "LANG": "C", "LC_ALL": "C"}
    base.update({k: os.environ[k] for k in ("USER", "LOGNAME", *LICENSE_KEYS) if k in os.environ})
    captured = subprocess.run(["/bin/bash", "--noprofile", "--norc", "-c",
                               'set -eo pipefail; source "$1" >/dev/null; /usr/bin/env -0',
                               "route-settings", str(SETTINGS)], env=base,
                              capture_output=True, check=True, timeout=30)
    environment = dict(entry.decode().split("=", 1) for entry in captured.stdout.split(b"\0") if entry)
    for key in ("PWD", "SHLVL", "_"):
        environment.pop(key, None)
    environment.update(SEARCH_PATHS)
    environment["CPLUS_INCLUDE_PATH"] = str(build / "gcc_compat")
    environment.update({key: str(output / "tmp") for key in ("TMPDIR", "TMP", "TEMP")})
    tools = {}
    for name in ("v++", "vivado", "gcc", "g++"):
        found = shutil.which(name, path=environment["PATH"])
        if found is None:
            raise ValueError("required environment tool missing: " + name)
        tools[name] = {"invocation": found, **identity(Path(found))}
    if tools["v++"]["invocation"] != str(SETTINGS.parent / "bin/v++"):
        raise ValueError("PATH selects another Vitis compiler")
    if [identity(path) for path in paths] != before:
        raise ValueError("settings or compatibility shim changed during environment capture")
    pins = {pin["path"]: pin for pin in [*before, *[identity(Path(t["invocation"])) for t in tools.values()]]}
    report = {"contract": "reviewed_frozen_exports_clean_base_not_unknown_historical_environment",
              "base_path": base["PATH"], "effective": public_environment(environment),
              "tools": tools, "pins": list(pins.values()),
              "scope": "launchers_settings_shim_and_host_compilers_not_exhaustive_vendor_installation"}
    return environment, report


def require_unchanged(report: dict, environment: dict) -> None:
    if public_environment(environment) != report["effective"]:
        raise ValueError("effective route environment changed")
    if any(identity(Path(pin["path"])) != pin for pin in report["pins"]):
        raise ValueError("route environment dependency changed")
    for tool in report["tools"].values():
        if identity(Path(tool["invocation"])) != {k: tool[k] for k in ("path", "sha256")}:
            raise ValueError("route tool symlink/target changed")
