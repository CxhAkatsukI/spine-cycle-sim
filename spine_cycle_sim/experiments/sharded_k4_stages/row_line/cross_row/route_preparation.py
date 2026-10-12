"""Bind V3 to frozen whole-line connectivity, without relabeling old evidence."""

import json
from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from ...empty_segment.production import COMPILER, PLATFORM
from ...execution import identity
from ...routing import relocate_config
from ..delivery import recheck_host
from ..route_preparation import CLAIM as BASIS_CLAIM, current_sources
from .model_contract import TARGET
from .recheck import recheck
from .validation import REFERENCE_SHA, require_xos

BASIS_SHA = "61ea41c7401e8a084eb14970bd3142aed3920c1c23772478ddd8d09ee6da27b0"
CLAIM = "cross_row_V3_single_XO_same_K4_connectivity_padded_host_not_board_timing"


def prepare(build: Path, basis: Path, study: Path, host: Path, integration: Path, output: Path) -> dict:
    if output.exists():
        raise FileExistsError("fresh cross-row route preparation required")
    basis_file = basis / "manifest.json"
    if sha256_file(basis_file) != BASIS_SHA:
        raise ValueError("exact immutable whole-line route basis required")
    previous = json.loads(basis_file.read_text())
    if (previous["claim"] != BASIS_CLAIM or previous["status"] != "PREPARED_NOT_ROUTED"
            or previous["FPGA_timing_admitted"] is not False
            or previous["A4_comparison_complete"] is not False
            or [previous[key] for key in ("clock_mhz", "synth_jobs", "impl_jobs",
                                        "tree_memory_gib", "reserve_gib", "timeout_seconds")]
            != [150, 2, 2, 40, 16, 14400]):
        raise ValueError("route basis scope or budgets differ")
    command = list(previous["command"])
    for flag, value in (("--target", "hw"), ("--kernel_frequency", "150"),
                        ("--vivado.synth.jobs", "2"), ("--vivado.impl.jobs", "2")):
        if command.count(flag) != 1 or command[command.index(flag) + 1] != value:
            raise ValueError("route target, clock or concurrency differs")
    if any(command.count(flag) != 1 for flag in ("--link", "--config", "-o")):
        raise ValueError("ambiguous frozen route command")
    xos = [Path(arg) for arg in command if arg.endswith(".xo")]
    reference = Path(previous["candidate_xo"]["path"])
    config = Path(command[command.index("--config") + 1])
    if (len(xos) != 11 or len(set(xos)) != 11 or xos.count(reference) != 1
            or previous["candidate_xo"]["sha256"] != REFERENCE_SHA):
        raise ValueError("eleven unchanged kernels including whole-line reference required")
    old_pins = {pin["path"]: pin for pin in previous["pins"]}
    original_files = [build / "link_command.sh", config, *xos, COMPILER, PLATFORM]
    if command[0] != str(COMPILER):
        raise ValueError("frozen route compiler differs")
    if any(old_pins.get(str(path)) != identity(path) for path in original_files):
        raise ValueError("frozen route kernels or connectivity changed")
    gate, host_gate = recheck(study), recheck_host(host)
    candidate = study / "production/adapter.hw.xo"
    if (identity(candidate) != gate["xo"] or gate["xo"]["sha256"] != TARGET["candidate_adapter_xo_sha256"]
            or host_gate["hardware_executed"] is not False):
        raise ValueError("exact successful V3 synthesis/RTL and padded-host gates required")
    contract = require_xos(reference, candidate)
    if contract["interface"] != previous["adapter_interface"]:
        raise ValueError("V3 changed frozen routed ABI")
    native_host = host / "candidate/sssp/sharded_k4_sssp_native_host"
    fields = dict(line.split("=", 1) for line in (native_host.parent / "manifest.txt").read_text().splitlines())
    if (identity(native_host) != previous["padded_host"] or fields["HOST"] != str(native_host)
            or [fields[key] for key in ("ROW_LINE_READ", "ALGORITHM", "PIPELINE_MODE")]
            != ["1", "weighted_sssp", "sharded-k4"]):
        raise ValueError("unchanged checked padded SSSP host required")
    pins = {pin["path"]: pin for pin in current_sources(study, host, integration)}
    required = {str(integration / name) for name in (
        "kernels/pma_to_regraph_adapter/cross_row_pipeline.hpp", "scripts/check_pma_adapter_cross_row.sh")}
    if not required <= pins.keys():
        raise ValueError("V3-specific production sources are not pinned")
    files = [basis_file, *original_files, candidate, native_host, native_host.parent / "manifest.txt"]
    files += [directory / name for directory in (study, host) for name in ("manifest.json", "results.json")]
    files += sorted(Path(__file__).parent.glob("*.py"))
    files += sorted(Path(__file__).parent.parent.glob("*.py"))
    owner = Path(__file__).parent.parent.parent
    files += [owner / name for name in ("routing.py", "execution.py", "link_runtime.py", "process_cleanup.py")]
    for path in files:
        pin = identity(path)
        if pins.setdefault(pin["path"], pin) != pin:
            raise ValueError("conflicting cross-row route dependency")
    if any(identity(Path(pin["path"])) != pin for pin in pins.values()):
        raise ValueError("cross-row route input changed during preparation")
    contents = relocate_config(config.read_text(), output)
    output.mkdir(parents=True)
    relocated = output / "link.cfg"
    relocated.write_text(contents)
    command[command.index("--config") + 1] = str(relocated)
    command[command.index("-o") + 1] = str(output / "candidate.hw.xclbin")
    command[command.index(str(reference))] = str(candidate)
    manifest = {key: previous[key] for key in (
        "clock_mhz", "synth_jobs", "impl_jobs", "tree_memory_gib", "reserve_gib", "timeout_seconds",
        "row_memory_contract", "FPGA_timing_admitted", "A4_comparison_complete")}
    manifest.update(status="PREPARED_NOT_ROUTED", claim=CLAIM, command=command,
                    pins=[*pins.values(), identity(relocated)], adapter_interface=contract["interface"],
                    replacement_flags=contract["flags"]["candidate"], candidate_xo=identity(candidate),
                    padded_host=identity(native_host), basis=identity(basis_file),
                    prerequisites={name: identity(path / "results.json") for name, path in (
                        ("production", study), ("host", host))})
    atomic_write_json(output / "manifest.json", manifest)
    return manifest
