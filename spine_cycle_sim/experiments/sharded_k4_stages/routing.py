"""Prepare an ABI-checked, single-XO replacement of the frozen SSSP route."""

import json
import os
from pathlib import Path
import shlex
import xml.etree.ElementTree as ET
import zipfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from .execution import identity
from .link_runtime import run_link


def adapter_interface(xo: Path) -> tuple[dict, dict]:
    with zipfile.ZipFile(xo) as archive:
        names = [name for name in archive.namelist() if name.endswith("/kernel.xml")]
        if len(names) != 1:
            raise ValueError("one kernel XML required in adapter XO")
        kernel = ET.fromstring(archive.read(names[0])).find("kernel")
    if kernel is None or kernel.get("name") != "pma_to_regraph_adapter":
        raise ValueError("adapter kernel required")
    options = shlex.split(kernel.get("compileOptions", ""))
    defines = {}
    for index, option in enumerate(options):
        value = options[index + 1] if option == "-D" else option[2:] if option.startswith("-D") else ""
        if value:
            key, _, flag = value.partition("=")
            defines[key] = flag or "1"
    interface = {"kernel": kernel.get("name"), "control": kernel.get("hwControlProtocol"),
                 "ports": [dict(port.attrib) for port in kernel.findall("ports/port")],
                 "args": [dict(arg.attrib) for arg in kernel.findall("args/arg")]}
    return interface, defines


def relocate_config(contents: str, output: Path) -> str:
    # Repeated nk/sp/stream_connect keys are meaningful; do not use ConfigParser.
    replacements = {"messageDb": output / "route.mdb", "temp_dir": output / "link",
                    "report_dir": output / "reports", "log_dir": output / "logs",
                    "remote_ip_cache": output / "ip_cache"}
    seen = set()
    lines = []
    section = False
    for line in contents.splitlines(keepends=True):
        section |= line.lstrip().startswith("[")
        key, equal, _ = line.partition("=")
        if not section and equal and key in replacements:
            if key in seen:
                raise ValueError("duplicate route output setting")
            seen.add(key)
            lines.append(f"{key}={replacements[key]}\n")
        else:
            lines.append(line)
    if seen != replacements.keys():
        raise ValueError("incomplete frozen route output settings")
    return "".join(lines)


def prepare_route(build: Path, candidate: Path, synthesis: Path, cosim: Path,
                  output: Path) -> dict:
    build, candidate, output = build.resolve(), candidate.resolve(), output.resolve()
    command_file = build / "link_command.sh"
    commands = [shlex.split(line) for line in command_file.read_text().splitlines()
                if line.startswith("v++ ")]
    if len(commands) != 1:
        raise ValueError("one frozen v++ link command required")
    command = commands[0]
    if command[command.index("--kernel_frequency") + 1] != "150" or "--link" not in command:
        raise ValueError("expected frozen 150-MHz link command")
    old_xos = [Path(arg) for arg in command if arg.endswith(".xo")]
    original = [xo for xo in old_xos if xo.name == "pma_to_regraph_adapter.hw.xo"]
    if len(old_xos) != 11 or len(original) != 1:
        raise ValueError("expected eleven original XOs with one adapter")
    old_interface, _ = adapter_interface(original[0])
    interface, flags = adapter_interface(candidate)
    if interface != old_interface:
        raise ValueError("candidate changes the routed adapter ABI")
    expected = ("WEIGHTED_PMA", "SHARDED_PMA", "SHARE_ALL_MEMORY_PORTS", "ROW_PREFETCH", "STOP_AFTER_LAST")
    if any(flags.get("GRASU_REGRAPH_" + name) != "1" for name in expected) or "GRASU_REGRAPH_COSIM_DEPTH" in flags:
        raise ValueError("candidate must be production weighted/shared/sharded combined XO")
    synth = json.loads(synthesis.read_text())
    rtl = json.loads(cosim.read_text())
    if synth["status"] != "HLS_PASS_NOT_ROUTED" or rtl["status"] != "RTL_COSIM_PASS_NOT_BOARD" or rtl["mode"] != "weighted":
        raise ValueError("passing weighted synthesis and RTL gates required")
    if synth["runs"]["combined"]["xo"] != identity(candidate):
        raise ValueError("candidate differs from synthesized XO")
    rtl_source = {pin["path"]: pin["sha256"] for pin in rtl["source"]}
    if any(rtl_source.get(pin["path"]) != pin["sha256"] for pin in synth["source"]):
        raise ValueError("RTL and XO source identities differ")
    pins = synth["source"] + rtl["source"] + [identity(path) for path in
            [command_file, synthesis, cosim, candidate, *old_xos]]
    config = Path(command[command.index("--config") + 1])
    pins.append(identity(config))
    if any(identity(Path(pin["path"])) != pin for pin in pins):
        raise ValueError("a gate's pinned input has changed")
    output.mkdir(parents=True, exist_ok=False)
    config_out = output / "link.cfg"
    config_out.write_text(relocate_config(config.read_text(), output))
    command[0] = "/data/yxx/tools/xilinx/Vitis/2024.1/bin/v++"
    command[command.index("--config") + 1] = str(config_out)
    command[command.index("-o") + 1] = str(output / "candidate.hw.xclbin")
    command[command.index(str(original[0]))] = str(candidate)
    command += ["--vivado.synth.jobs", "2", "--vivado.impl.jobs", "2"]
    pins.append(identity(config_out))
    manifest = {"status": "PREPARED_NOT_ROUTED", "command": command, "pins": pins,
                "adapter_interface": interface, "replacement_flags": flags,
                "clock_mhz": 150, "synth_jobs": 2, "impl_jobs": 2,
                "tree_memory_gib": 40, "reserve_gib": 16, "timeout_seconds": 14400,
                "claim": "single_adapter_XO_replacement_same_K4_connectivity_not_speedup"}
    atomic_write_json(output / "manifest.json", manifest)
    return manifest


def execute_route(output: Path) -> dict:
    manifest = json.loads((output / "manifest.json").read_text())
    if (output / "route.resources.json").exists():
        raise FileExistsError("route attempt already exists; use a fresh preparation")
    if any(identity(Path(pin["path"])) != pin for pin in manifest["pins"]):
        raise ValueError("route inputs changed after preparation")
    temporary = output / "tmp"
    temporary.mkdir()
    environment = dict(os.environ, TMPDIR=str(temporary), TMP=str(temporary), TEMP=str(temporary))
    resources = run_link(manifest["command"], output, output / "route", environment=environment,
                         timeout=manifest["timeout_seconds"], tree_memory_gib=manifest["tree_memory_gib"],
                         reserve_gib=manifest["reserve_gib"])
    unchanged = all(identity(Path(pin["path"])) == pin for pin in manifest["pins"])
    xclbin = output / "candidate.hw.xclbin"
    success = resources["exit_code"] == 0 and resources["stop_reason"] == "process_exit" and unchanged and xclbin.is_file()
    result = {"status": "LINK_PASS_AWAITING_TIMING_AND_BOARD" if success else "LINK_FAILED",
              "resources": resources, "inputs_unchanged": unchanged,
              "xclbin": identity(xclbin) if xclbin.is_file() else None}
    atomic_write_json(output / "summary.json", result)
    return result
