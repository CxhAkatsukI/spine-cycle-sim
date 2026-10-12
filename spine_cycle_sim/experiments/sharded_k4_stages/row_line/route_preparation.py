"""Bind the whole-line XO and padded host to an unchanged production route."""

import json
from pathlib import Path
import shlex

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from ..empty_segment.production import COMPILER, PLATFORM
from ..execution import identity
from ..routing import adapter_interface, relocate_config
from .delivery import recheck, recheck_host
from .study import INTEGRATION_FILES
from .validation import require_xos

CLAIM = "whole_line_XO_and_padded_host_same_K4_connectivity_not_board_timing"


def current_sources(study: Path, host: Path, integration: Path) -> list[dict]:
    pins = {}
    for directory in (study, host):
        manifest = json.loads((directory / "manifest.json").read_text())
        selected = [pin for pin in manifest["pins"] if Path(pin["path"]).is_relative_to(integration)]
        if not selected:
            raise ValueError("prerequisite belongs to another integration checkout")
        for pin in selected:
            if identity(Path(pin["path"])) != pin or pins.setdefault(pin["path"], pin) != pin:
                raise ValueError("production HLS/host source changed after prerequisite")
    if not {str(integration / name) for name in INTEGRATION_FILES} <= pins.keys():
        raise ValueError("incomplete production HLS prerequisite")
    return list(pins.values())


def prepare(build: Path, study: Path, host: Path, integration: Path, output: Path) -> dict:
    if output.exists():
        raise FileExistsError("fresh whole-line route preparation required")
    gate, host_gate = recheck(study), recheck_host(host)
    paths = current_sources(study, host, integration)
    command_file = build / "link_command.sh"
    commands = [shlex.split(line) for line in command_file.read_text().splitlines() if line.startswith("v++ ")]
    if len(commands) != 1:
        raise ValueError("one frozen v++ link command required")
    command = commands[0]
    for flag, value in (("--target", "hw"), ("--kernel_frequency", "150")):
        if command.count(flag) != 1 or command[command.index(flag) + 1] != value:
            raise ValueError("production route target/clock differs")
    if (command.count("--link") != 1 or command.count("--config") != 1 or command.count("-o") != 1
            or any(arg.startswith("--vivado.") for arg in command)):
        raise ValueError("ambiguous production route command")
    xos = [Path(arg) for arg in command if arg.endswith(".xo")]
    original = [xo for xo in xos if xo.name == "pma_to_regraph_adapter.hw.xo"]
    if len(xos) != 11 or len(set(xos)) != 11 or len(original) != 1:
        raise ValueError("eleven distinct original XOs with one adapter required")
    study_manifest = json.loads((study / "manifest.json").read_text())
    reference = Path(study_manifest["reference"]["path"])
    candidate = study / "production/adapter.hw.xo"
    if identity(reference) != study_manifest["reference"] or identity(candidate) != gate["xo"]:
        raise ValueError("current production XO differs from prerequisite")
    contract = require_xos(reference, candidate)
    if adapter_interface(original[0])[0] != contract["interface"]:
        raise ValueError("whole-line XO differs from original route ABI")
    host_fields = dict(line.split("=", 1) for line in (host / "candidate/sssp/manifest.txt").read_text().splitlines())
    native_host = host / "candidate/sssp/sharded_k4_sssp_native_host"
    if (host_fields["HOST"] != str(native_host) or host_fields["ROW_LINE_READ"] != "1"
            or host_fields["ALGORITHM"] != "weighted_sssp" or host_fields["PIPELINE_MODE"] != "sharded-k4"
            or host_gate["hardware_executed"] is not False):
        raise ValueError("exact padded SSSP host required")
    config = Path(command[command.index("--config") + 1])
    contents = config.read_text()
    if [line for line in contents.splitlines() if line.startswith("platform=")] != [f"platform={PLATFORM}"]:
        raise ValueError("route platform differs from production synthesis")
    route_manifest = Path(study_manifest["route_manifest"]["path"])
    if identity(route_manifest) != study_manifest["route_manifest"]:
        raise ValueError("historical route manifest differs from prerequisite")
    route_pins = {pin["path"]: pin for pin in json.loads(route_manifest.read_text())["pins"]}
    if any(route_pins.get(str(path)) != identity(path) for path in (command_file, config, *xos)):
        raise ValueError("original kernels/connectivity differ from historical routed inputs")
    files = [command_file, config, *xos, reference, candidate, native_host, route_manifest, COMPILER, PLATFORM]
    files += [directory / name for directory in (study, host) for name in ("manifest.json", "results.json")]
    files += sorted(Path(__file__).parent.glob("*.py"))
    files += [Path(__file__).parent.parent / name for name in (
        "routing.py", "execution.py", "link_runtime.py", "process_cleanup.py")]
    pins = {pin["path"]: pin for pin in paths}
    pins.update({str(path): identity(path) for path in files})
    if any(identity(Path(pin["path"])) != pin for pin in pins.values()):
        raise ValueError("production route input changed during preparation")
    output.mkdir(parents=True)
    config_out = output / "link.cfg"
    config_out.write_text(relocate_config(contents, output))
    command[0] = str(COMPILER)
    command[command.index("--config") + 1] = str(config_out)
    command[command.index("-o") + 1] = str(output / "candidate.hw.xclbin")
    command[command.index(str(original[0]))] = str(candidate)
    command += ["--vivado.synth.jobs", "2", "--vivado.impl.jobs", "2"]
    manifest = {"status": "PREPARED_NOT_ROUTED", "claim": CLAIM, "command": command,
                "pins": [*pins.values(), identity(config_out)], "adapter_interface": contract["interface"],
                "replacement_flags": contract["flags"]["candidate"], "row_memory_contract": contract["row_memory_contract"],
                "candidate_xo": identity(candidate), "padded_host": identity(native_host),
                "prerequisites": {"production": identity(study / "results.json"), "host": identity(host / "results.json")},
                "clock_mhz": 150, "synth_jobs": 2, "impl_jobs": 2,
                "tree_memory_gib": 40, "reserve_gib": 16, "timeout_seconds": 14400,
                "FPGA_timing_admitted": False, "A4_comparison_complete": False}
    atomic_write_json(output / "manifest.json", manifest)
    return manifest
