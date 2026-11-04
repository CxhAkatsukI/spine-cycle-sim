"""Recheck clean-source compilation and fresh xclbin metadata before any launch."""

import json
from pathlib import Path

from spine_cycle_sim.experiments.upstream_controls.execution import run_bounded
from .. import artifact, checkpoint_run
from ..source_build import configuration as config, gates, portable_return, snapshot
from .preparation import unique

STATUS = "ORIGINAL_R_ROUTED_CLOCK_TOPOLOGY_TIMING_PASS_AWAITING_BOARD"
RETAINED_TOPOLOGY_ERROR = "ValueError('implemented HBM bank/argument bindings differ from author topology')"


def validate_result(result, topology, review_retained_analysis_failure=False, *, algorithm="pr"):
    expected = config.routed_status(topology, algorithm=algorithm)
    if type(review_retained_analysis_failure) is not bool:
        raise ValueError("retained analysis review requires an explicit boolean")
    if algorithm != "pr" and review_retained_analysis_failure:
        raise ValueError("active-min requires a clean routed pass")
    retained = (review_retained_analysis_failure is True and result["status"] == "FAILED_RETAINED" and
                result["errors"] == [RETAINED_TOPOLOGY_ERROR] and "analysis" not in result and
                result.get("extraction", {}).get("exit_code") == 0 and
                result.get("extraction", {}).get("timed_out") is False)
    if ((not retained and (result["status"] != expected or result["errors"])) or
            result.get("configuration", config.DEFAULT_TOPOLOGY) != topology or
            result.get("algorithm", "pr") != algorithm or
            any(result.get(key) is not False for key in
                ("board_programmed", "hardware_timing_measured", "publication_match"))):
        raise ValueError("successful fresh-source route required; prebuilt is not admitted")
    return retained


def review(route, output, *, topology=config.DEFAULT_TOPOLOGY, review_retained_analysis_failure=False,
           algorithm="pr"):
    result_path = route / "results.json"
    result = json.loads(result_path.read_text())
    retained = validate_result(result, topology, review_retained_analysis_failure, algorithm=algorithm)
    snapshot.unchanged(result["pins"])
    names = list(config.kernels(topology))
    if ([step["id"] for step in result["steps"]] != ["compile_" + name for name in names] + ["route"] or
            any(step["exit_code"] or step["stop_reason"] != "process_exit" or step["cleanup_snapshot_error"]
                for step in result["steps"]) or [xo["abi"]["kernel"] for xo in result["xos"]] != names):
        raise ValueError("complete selected-topology XO source build and route required")
    pins = [artifact.identity(result_path), *result["pins"]]
    for name, recorded in zip(names, result["xos"]):
        abi = gates.inspect_xo(route / "xo" / (name + ".hw.xo"), name, topology=topology,
                               algorithm=algorithm)
        hls = gates.inspect_hls(route / "compile" / name, name)
        if recorded != {"abi": abi, "hls": hls}:
            raise ValueError("compiled ABI or HLS report changed")
        pins += [abi["xo"], hls["report"]]
    binary = artifact.identity(route / config.binary_name(topology, algorithm=algorithm))
    if result["xclbin"] != binary or artifact.identity(checkpoint_run.UTILITY) not in result["pins"]:
        raise ValueError("routed binary or extraction utility identity differs")
    output.mkdir(parents=True, exist_ok=False)
    metadata = output / "metadata"
    metadata.mkdir()
    extraction = run_bounded(artifact.dump_command(Path(binary["path"]), metadata, checkpoint_run.UTILITY),
        output, output / "extract", timeout=120, memory_gib=2, reserve_gib=32)
    if extraction["exit_code"] or extraction["timed_out"]:
        raise ValueError("fresh binary metadata extraction failed")
    inspected = gates.inspect_routed(metadata, route / "link/reports", configuration=topology,
                                     algorithm=algorithm)
    # Routed results have passed through JSON, which represents tuples as lists.
    if not retained and json.loads(json.dumps(inspected)) != result["analysis"]:
        raise ValueError("fresh binary or timing differs from routed admission")
    pins += [binary, inspected["timing"]["report"]]
    pins += [artifact.identity(path) for path in sorted(metadata.glob("*.json"))]
    snapshot.unchanged(pins)
    checked = {"status": config.routed_status(topology, algorithm=algorithm), "configuration": topology,
            "xclbin": binary, "analysis": inspected,
            "extraction": extraction, "pins": unique(pins)}
    if retained:
        checked["retained_analysis_failure"] = {"result": artifact.identity(result_path),
            "status": result["status"], "errors": result["errors"], "original_result_modified": False,
            "scope": "independent full ABI/topology/clock/timing review, not a new implementation"}
    return checked


def review_returned_cc(route, capsule, digest, output):
    _, result, pins = portable_return.verify(route, digest, capsule)
    for name, recorded in zip(portable_return.NAMES, result["xos"]):
        local = {
            "abi": gates.inspect_xo(route / "xo" / (name + ".hw.xo"), name, topology="a4", algorithm="cc"),
            "hls": gates.inspect_hls(route / "compile" / name, name),
        }
        for field, key in (("abi", "xo"), ("hls", "report")):
            local[field][key] = {**local[field][key], "path": recorded[field][key]["path"]}
        if local != recorded:
            raise ValueError("returned public A4 CC ABI or HLS report differs")
    binary = artifact.identity(route / portable_return.BINARY)
    metadata = output / "metadata"
    metadata.mkdir(parents=True, exist_ok=False)
    utility = artifact.identity(checkpoint_run.UTILITY)
    extraction = run_bounded(artifact.dump_command(Path(binary["path"]), metadata, checkpoint_run.UTILITY),
        output, output / "extract", timeout=120, memory_gib=2, reserve_gib=32)
    if extraction["exit_code"] or extraction["timed_out"]:
        raise ValueError("returned public A4 CC metadata extraction failed")
    inspected = gates.inspect_routed(metadata, route / "timing", configuration="a4", algorithm="cc")
    pins += [utility, *[artifact.identity(path) for path in sorted(metadata.glob("*.json"))]]
    snapshot.unchanged(pins)
    return {"status": config.routed_status("a4", algorithm="cc"), "configuration": "a4",
            "xclbin": binary, "analysis": inspected, "extraction": extraction, "pins": unique(pins)}
