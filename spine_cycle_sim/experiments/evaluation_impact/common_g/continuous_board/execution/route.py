"""Admit only a completed new-search/full-cache route with final routed timing."""

import json
from pathlib import Path

from spine_cycle_sim.experiments.sharded_k4_stages.bitstream import admit_bitstream
from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity
from ...complete_pipeline.hardware.preparation import COUNTS
from ...search_pipeline.synthesis import unchanged


def review(route, original, output):
    manifest = json.loads((route / "manifest.json").read_text())
    if manifest.get("status") != "PREPARED_DIAGNOSTIC_LINK_NOT_BASELINE_ADMISSION" or \
            manifest.get("clock_mhz") != 150 or manifest.get("core_identity", {}).get("synthesizable_core_identical") is not True:
        raise ValueError("complete new-G route identity required; adapter-only route is not sufficient")
    kernels = manifest["kernel_inputs"]
    if set(kernels) != set(COUNTS) or any(type(value["replaced"]) is not bool for value in kernels.values()) or \
            {key for key, value in kernels.items() if value["replaced"] is True} != \
            {"bin_search", "process_cache"}:
        raise ValueError("both new search and full-cache exports must be linked")
    unchanged(manifest["pins"])
    pins = {pin["path"]: pin for pin in manifest["pins"]}
    for kernel in kernels.values():
        for name in ("source", "frozen"):
            if pins.get(kernel[name]["path"]) != kernel[name]:
                raise ValueError("linked XO missing from frozen route pins")
        if kernel["source"]["sha256"] != kernel["frozen"]["sha256"]:
            raise ValueError("linked XO differs from reviewed export")
    if not (route / "execution.json").is_file() or not (route / "summary.json").is_file():
        raise ValueError("complete new-G route still running or unfinished; no board programming")
    execution = json.loads((route / "execution.json").read_text())
    summary = json.loads((route / "summary.json").read_text())
    resources = execution.get("resources", {})
    if execution.get("status") != "LINK_PASS_AWAITING_TIMING_AND_BOARD" or \
            summary.get("status") != execution["status"] or summary.get("resources") != resources or \
            type(resources.get("exit_code")) is not int or resources["exit_code"] != 0 or \
            resources.get("stop_reason") != "process_exit" or "cleanup_snapshot_error" not in resources or \
            resources.get("cleanup_snapshot_error") is not None or summary.get("inputs_unchanged") is not True or \
            execution.get("inputs_unchanged") is not True or summary.get("xclbin") != execution.get("xclbin"):
        raise ValueError("successful unchanged final route execution required")
    checked = admit_bitstream(route, original, output)
    expected = {f"{name}:{name}_{i + 1}" for name, count in COUNTS.items() for i in range(count)}
    if {name for name, _ in checked["topology"]["kernels"]} != expected:
        raise ValueError("routed compute-unit budget differs from full G+R contract")
    checked["pins"] += [identity(route / "execution.json"), identity(Path(__file__))]
    return checked
