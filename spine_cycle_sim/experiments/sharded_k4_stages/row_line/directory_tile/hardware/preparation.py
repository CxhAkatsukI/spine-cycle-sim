"""Freeze eleven link inputs, changing only the admitted adapter artifact."""

import json
from pathlib import Path
import shutil

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from ....empty_segment.production import COMPILER, PLATFORM
from ....empty_segment.route_environment.contract import reconstruct
from ....empty_segment.route_environment.probe import run as preflight
from ....execution import identity
from ....routing import adapter_interface, relocate_config
from ...delivery import recheck_host
from ..recheck import hls, hls_sources

BASIS_SHA = "e5e260191bde3ae17284a0d275182572e7a8f92207fc8c557dd17ba7c7889281"
CANDIDATE_SHA = "5dda403d8d07956f0a9f94211faeaa0e976bdc11d9f91863a2fe8da9a5e5ea5e"
RESULT_SHA = "83057b7a13d791489fcc769c3f59bb4577512a19a2f56d38c613953fb53bb8e6"


def link_inputs(previous: dict, candidate: Path) -> tuple[list, Path, list]:
    command = list(previous["command"])
    expected = (("--target", "hw"), ("--kernel_frequency", "150"),
                ("--vivado.synth.jobs", "2"), ("--vivado.impl.jobs", "2"))
    if (previous["status"] != "PREPARED_NOT_ROUTED" or previous["FPGA_timing_admitted"] is not False
            or command[0] != str(COMPILER)):
        raise ValueError("exact unexecuted V3 route basis required")
    for flag, value in expected:
        if command.count(flag) != 1 or command[command.index(flag) + 1] != value:
            raise ValueError("changed route target, clock or concurrency")
    if any(command.count(flag) != 1 for flag in ("--link", "--config", "-o")):
        raise ValueError("ambiguous link command")
    xos = [Path(arg) for arg in command if arg.endswith(".xo")]
    old = Path(previous["candidate_xo"]["path"])
    if len(xos) != 11 or len(set(xos)) != 11 or xos.count(old) != 1:
        raise ValueError("eleven distinct XOs including one adapter required")
    config = Path(command[command.index("--config") + 1])
    pins = {pin["path"]: pin for pin in previous["pins"]}
    for path in [config, *xos, COMPILER, PLATFORM, Path(previous["padded_host"]["path"])]:
        if pins.get(str(path)) != identity(path):
            raise ValueError("frozen route input changed: " + str(path))
    interface, flags = adapter_interface(candidate)
    if interface != previous["adapter_interface"]:
        raise ValueError("candidate changed the complete adapter ABI")
    expected_flags = {"WEIGHTED_PMA": "1", "SHARDED_PMA": "1", "SHARE_ALL_MEMORY_PORTS": "1",
        "ROW_PREFETCH": "1", "STOP_AFTER_LAST": "1", "SKIP_EMPTY_SEGMENT": "1", "ROW_LINE_READ": "1",
        "CROSS_ROW_PIPELINE": "1", "DIRECTORY_TILE_ROWS": "1024", "PACKET_PIPELINE": "1",
        "BANK_STREAM": "1", "BANK_FIFO_LINES": "256"}
    if {k: v for k, v in flags.items() if k.startswith("GRASU_")} != {
            "GRASU_REGRAPH_" + k: v for k, v in expected_flags.items()}:
        raise ValueError("exact admitted production adapter flags required")
    return command, config, xos


def prepare(build: Path, basis: Path, study: Path, host: Path,
            integration: Path, output: Path, *, allow_bounded_builds: bool = False,
            background_memory_gib: int = 0) -> dict:
    if type(background_memory_gib) is not int or not 0 <= background_memory_gib <= 40:
        raise ValueError("background workload reserve must be between zero and 40 GiB")
    if output.exists():
        raise FileExistsError("fresh hardware attempt required")
    basis_file = basis / "manifest.json"
    candidate = study / "production/adapter.hw.xo"
    if (sha256_file(basis_file) != BASIS_SHA or sha256_file(candidate) != CANDIDATE_SHA
            or sha256_file(study / "results.json") != RESULT_SHA):
        raise ValueError("immutable basis and final 256-line-bank candidate required")
    previous = json.loads(basis_file.read_text())
    command, config, xos = link_inputs(previous, candidate)
    contents = config.read_text()
    if [line for line in contents.splitlines() if line.startswith("platform=")] != [f"platform={PLATFORM}"]:
        raise ValueError("production platform changed")
    recheck_host(host)
    native_host = host / "candidate/sssp/sharded_k4_sssp_native_host"
    host_manifest = native_host.parent / "manifest.txt"
    fields = dict(line.split("=", 1) for line in host_manifest.read_text().splitlines())
    if (identity(native_host) != previous["padded_host"] or
            [fields[key] for key in ("ROW_LINE_READ", "ALGORITHM", "PIPELINE_MODE")]
            != ["1", "weighted_sssp", "sharded-k4"]):
        raise ValueError("checked padded host changed")
    source_pins = []
    for path, blob in hls_sources(study).items():
        path = Path(path)
        if path.is_relative_to(integration):
            if path.read_bytes() != blob:
                raise ValueError("HLS integration source changed: " + str(path))
            source_pins.append(identity(path))
    if not source_pins:
        raise ValueError("candidate integration sources missing")
    output.mkdir(parents=True)
    check = output / "prerequisite"
    check.mkdir()
    (check / "hls").symlink_to(study, target_is_directory=True)
    reference = next(Path(pin["path"]) for pin in json.loads((study / "manifest.json").read_text())["pins"]
                     if Path(pin["path"]).suffix == ".xo")
    shutil.copy2(reference, check / "reference.xo")
    atomic_write_json(check / "hls_recheck.json", hls(check))
    inputs = output / "inputs"
    inputs.mkdir()
    original = Path(previous["candidate_xo"]["path"])
    copies = []
    for path in xos:
        selected = candidate if path == original else path
        destination = inputs / ("pma_to_regraph_adapter.hw.xo" if path == original else path.name)
        shutil.copy2(selected, destination)
        if sha256_file(selected) != sha256_file(destination):
            raise ValueError("XO copy changed")
        command[command.index(str(path))] = str(destination)
        copies += [identity(selected), identity(destination)]
    relocated = output / "link.cfg"
    relocated.write_text(relocate_config(contents, output))
    command[command.index("--config") + 1] = str(relocated)
    command[command.index("-o") + 1] = str(output / "candidate.hw.xclbin")
    (output / "tmp").mkdir()
    environment, contract = reconstruct(build, output)
    atomic_write_json(output / "environment.json", contract)
    preflight(output, environment, contract)
    paths = [basis_file, config, study / "manifest.json", study / "results.json", study / "sources.tar.gz",
             native_host, host_manifest, host / "results.json", check / "hls_recheck.json",
             relocated, output / "environment.json", output / "preflight/results.json"]
    paths += sorted(Path(__file__).parent.glob("*.py"))
    owner = Path(__file__).parents[3]
    paths += [owner / name for name in ("routing.py", "link_runtime.py", "process_cleanup.py", "execution.py")]
    paths += sorted((owner / "empty_segment/route_environment").glob("*.py"))
    pins = {pin["path"]: pin for pin in [*source_pins, *copies, *contract["pins"], *map(identity, paths)]}
    manifest = {"status": "PREPARED_NOT_ROUTED", "command": command, "pins": list(pins.values()),
        "candidate_xo": identity(inputs / "pma_to_regraph_adapter.hw.xo"),
        "source_candidate_xo": identity(candidate), "padded_host": identity(native_host),
        "row_memory_contract": previous["row_memory_contract"], "clock_mhz": 150,
        "synth_jobs": 2, "impl_jobs": 2, "tree_memory_gib": 40, "reserve_gib": 24,
        "timeout_seconds": 21600, "queue_timeout_seconds": 86400,
        "allow_bounded_builds": allow_bounded_builds, "background_memory_gib": background_memory_gib,
        "claim": "four_bank_stream_adapters_same_sharded_K4_connectivity_not_board_speedup",
        "FPGA_timing_admitted": False, "A4_comparison_complete": False}
    atomic_write_json(output / "manifest.json", manifest)
    return manifest
