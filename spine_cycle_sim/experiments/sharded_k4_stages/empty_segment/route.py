"""Prepare an exact single-XO replacement; persist any memory admission refusal."""

import argparse
import json
from pathlib import Path
import shlex

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.upstream_controls.execution import available_memory_bytes
from ..execution import identity
from ..routing import execute_route, relocate_config
from .production import COMPILER, PLATFORM, require_xo
from .production_validation import recheck


def prepare(build: Path, production: Path, output: Path) -> dict:
    if output.exists():
        raise FileExistsError("fresh route preparation required")
    gate = recheck(production, current_inputs=True)
    command_file = build / "link_command.sh"
    commands = [shlex.split(line) for line in command_file.read_text().splitlines() if line.startswith("v++ ")]
    if len(commands) != 1:
        raise ValueError("one frozen v++ link command required")
    command = commands[0]
    if ("--link" not in command or command[command.index("--target") + 1] != "hw"
            or command[command.index("--kernel_frequency") + 1] != "150"
            or any(arg.startswith("--vivado.") for arg in command)):
        raise ValueError("frozen production link configuration differs")
    xos = [Path(arg) for arg in command if arg.endswith(".xo")]
    original = [xo for xo in xos if xo.name == "pma_to_regraph_adapter.hw.xo"]
    if len(xos) != 11 or len(set(xos)) != 11 or len(original) != 1:
        raise ValueError("eleven distinct original XOs with one adapter required")
    if identity(original[0]) != gate["manifest"]["reference_xo"]:
        raise ValueError("route adapter differs from production ABI reference")
    candidate = production / "adapter.hw.xo"
    contract = require_xo(candidate, original[0])
    config = Path(command[command.index("--config") + 1])
    contents = config.read_text()
    if [line for line in contents.splitlines() if line.startswith("platform=")] != [f"platform={PLATFORM}"]:
        raise ValueError("route platform differs from production synthesis")
    paths = [command_file, config, *xos, production / "manifest.json", production / "results.json",
             production / "compile.resources.json", production.with_name(production.name + "_watchdog.resources.json"),
             Path(__file__), Path(__file__).with_name("production_validation.py")]
    pins = {pin["path"]: pin for pin in gate["manifest"]["pins"]}
    pins.update({str(path): identity(path) for path in [candidate, *paths]})
    if any(identity(Path(pin["path"])) != pin for pin in pins.values()):
        raise ValueError("route input changed during preparation")
    output.mkdir(parents=True)
    config_out = output / "link.cfg"
    config_out.write_text(relocate_config(contents, output))
    command[0] = str(COMPILER)
    command[command.index("--config") + 1] = str(config_out)
    command[command.index("-o") + 1] = str(output / "candidate.hw.xclbin")
    command[command.index(str(original[0]))] = str(candidate)
    command += ["--vivado.synth.jobs", "2", "--vivado.impl.jobs", "2"]
    manifest = {"status": "PREPARED_NOT_ROUTED", "command": command,
                "pins": [*pins.values(), identity(config_out)], "adapter_interface": contract["interface"],
                "replacement_flags": contract["flags"], "clock_mhz": 150,
                "synth_jobs": 2, "impl_jobs": 2, "tree_memory_gib": 40, "reserve_gib": 16,
                "timeout_seconds": 14400, "production": identity(production / "results.json"),
                "claim": "single_empty_helper_XO_replacement_same_K4_connectivity_not_speedup"}
    atomic_write_json(output / "manifest.json", manifest)
    return manifest


def admit(output: Path) -> dict:
    manifest = json.loads((output / "manifest.json").read_text())
    admission = output / "admission.json"
    if admission.exists():
        raise FileExistsError("route admission already recorded; prepare a fresh attempt")
    if any(identity(Path(pin["path"])) != pin for pin in manifest["pins"]):
        raise ValueError("route input changed after preparation")
    available = available_memory_bytes()
    required = (manifest["tree_memory_gib"] + manifest["reserve_gib"]) * 1024**3
    result = {"status": "ADMISSION_REJECTED_NOT_STARTED" if available < required else "MEMORY_ADMITTED_NOT_STARTED",
              "available_bytes": available, "required_bytes": required,
              "tree_memory_gib": manifest["tree_memory_gib"], "reserve_gib": manifest["reserve_gib"],
              "command": manifest["command"], "route_started": False}
    atomic_write_json(admission, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, required=True)
    parser.add_argument("--production", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    output = args.output.resolve()
    prepare(args.build.resolve(), args.production.resolve(), output)
    result = admit(output)
    if args.execute and result["status"] == "MEMORY_ADMITTED_NOT_STARTED":
        try:
            result = execute_route(output)
        except Exception as error:
            atomic_write_json(output / "failure.json", {"status": "ROUTE_EXECUTION_FAILED", "error": str(error)})
            raise
    print(json.dumps({"status": result["status"]}))


if __name__ == "__main__":
    main()
