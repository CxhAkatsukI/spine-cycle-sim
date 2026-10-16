"""Recheck clean-source compilation and fresh xclbin metadata before any launch."""

import json
from pathlib import Path

from spine_cycle_sim.experiments.upstream_controls.execution import run_bounded
from .. import artifact, checkpoint_run
from ..source_build import configuration as config, gates, snapshot
from .preparation import unique

STATUS = "ORIGINAL_R_ROUTED_CLOCK_TOPOLOGY_TIMING_PASS_AWAITING_BOARD"


def review(route, output, *, topology=config.DEFAULT_TOPOLOGY):
    config.counts(topology)
    result_path = route / "results.json"
    result = json.loads(result_path.read_text())
    if (result["status"] != config.routed_status(topology) or result["errors"] or
            result.get("configuration", config.DEFAULT_TOPOLOGY) != topology or
            any(result.get(key) is not False for key in
                ("board_programmed", "hardware_timing_measured", "publication_match"))):
        raise ValueError("successful fresh-source route required; prebuilt is not admitted")
    snapshot.unchanged(result["pins"])
    names = list(config.kernels(topology))
    if ([step["id"] for step in result["steps"]] != ["compile_" + name for name in names] + ["route"] or
            any(step["exit_code"] or step["stop_reason"] != "process_exit" or step["cleanup_snapshot_error"]
                for step in result["steps"]) or [xo["abi"]["kernel"] for xo in result["xos"]] != names):
        raise ValueError("complete selected-topology XO source build and route required")
    pins = [artifact.identity(result_path), *result["pins"]]
    for name, recorded in zip(names, result["xos"]):
        abi = gates.inspect_xo(route / "xo" / (name + ".hw.xo"), name, topology=topology)
        hls = gates.inspect_hls(route / "compile" / name, name)
        if recorded != {"abi": abi, "hls": hls}:
            raise ValueError("compiled ABI or HLS report changed")
        pins += [abi["xo"], hls["report"]]
    binary = artifact.identity(route / config.binary_name(topology))
    if result["xclbin"] != binary or artifact.identity(checkpoint_run.UTILITY) not in result["pins"]:
        raise ValueError("routed binary or extraction utility identity differs")
    output.mkdir(parents=True, exist_ok=False)
    metadata = output / "metadata"
    metadata.mkdir()
    extraction = run_bounded(artifact.dump_command(Path(binary["path"]), metadata, checkpoint_run.UTILITY),
        output, output / "extract", timeout=120, memory_gib=2, reserve_gib=32)
    if extraction["exit_code"] or extraction["timed_out"]:
        raise ValueError("fresh binary metadata extraction failed")
    inspected = gates.inspect_routed(metadata, route / "link/reports", configuration=topology)
    if inspected != result["analysis"]:
        raise ValueError("fresh binary or timing differs from routed admission")
    pins += [binary, inspected["timing"]["report"]]
    pins += [artifact.identity(path) for path in sorted(metadata.glob("*.json"))]
    snapshot.unchanged(pins)
    return {"status": config.routed_status(topology), "configuration": topology,
            "xclbin": binary, "analysis": inspected,
            "extraction": extraction, "pins": unique(pins)}
