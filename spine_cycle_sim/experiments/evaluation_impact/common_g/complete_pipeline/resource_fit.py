"""Account complete candidate HLS resources against physical SLR capacity."""

import argparse
import json
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from ..search_pipeline.synthesis import unchanged
from .resource_probe import capacity

RESOURCES = ("LUT", "FF", "BRAM_18K", "URAM", "DSP")
SLRS = ("SLR0", "SLR1", "SLR2")


def topology(contents):
    section, kernels, placements = "", {}, {}
    for original in contents.splitlines():
        line = original.partition("#")[0].strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            continue
        if section != "connectivity":
            continue
        key, separator, value = line.partition("=")
        if not separator:
            raise ValueError("malformed connectivity entry")
        key, value = key.strip(), value.strip()
        if key == "nk":
            fields = value.split(":")
            if len(fields) not in (2, 3):
                raise ValueError("invalid kernel count entry")
            name, count = fields[:2]
            count = int(count)
            instances = fields[2].split(".") if len(fields) == 3 else [f"{name}_{i+1}" for i in range(count)]
            if name in kernels or count <= 0 or len(instances) != count or len(set(instances)) != count:
                raise ValueError("duplicate or inconsistent kernel instances")
            kernels[name] = instances
        elif key == "slr":
            instance, slr = value.split(":")
            if instance in placements or slr not in SLRS:
                raise ValueError("duplicate placement or unknown SLR")
            placements[instance] = slr
    instances = [instance for group in kernels.values() for instance in group]
    if not instances or len(instances) != len(set(instances)) or set(instances) != set(placements):
        raise ValueError("every unique compute unit needs an explicit SLR placement")
    return kernels, placements


def resources(path, kernel):
    root = ET.parse(path).getroot()
    if root.findtext("UserAssignments/TopModelName") != kernel:
        raise ValueError("HLS top identity differs from resource assignment")
    values = {name: int(root.findtext("AreaEstimates/Resources/" + name)) for name in RESOURCES}
    if any(value < 0 for value in values.values()):
        raise ValueError("negative HLS resources")
    return values


def account(kernels, placements, estimates, physical):
    if set(kernels) != set(estimates):
        raise ValueError("resource ledger must cover every kernel, with no extras")
    per_slr = {slr: dict.fromkeys(RESOURCES, 0) for slr in SLRS}
    rows = []
    for kernel, instances in kernels.items():
        for instance in instances:
            slr = placements[instance]
            values = estimates[kernel]
            for name in RESOURCES:
                per_slr[slr][name] += values[name]
            rows.append({"kernel": kernel, "instance": instance, "slr": slr, "hls_resources": values})
    totals = {name: sum(values[name] for values in per_slr.values()) for name in RESOURCES}
    oversubscribed = [slr for slr in SLRS if per_slr[slr]["URAM"] > physical[slr]]
    return {"instances": rows, "hls_totals": totals, "hls_per_slr": per_slr,
            "physical_uram_capacity": physical, "uram_oversubscribed_slrs": oversubscribed,
            "total_uram_capacity_exceeded": totals["URAM"] > physical["device"],
            "claim": "HLS_storage_placement_screen_not_platform_or_routing_admission",
            "complete_g_resource_fit_admitted": False, "hardware_timing_admitted": False}


def query_capacity(attempt, *, platform=False):
    query = json.loads((attempt / "results.json").read_text())
    expected = ("PLATFORM_PBLOCK_CAPACITY_QUERIED_NOT_ROUTE_ADMISSION" if platform else
                "PHYSICAL_SITE_CAPACITY_QUERIED_NOT_ROUTE_ADMISSION")
    if query["status"] != expected:
        raise ValueError("completed matching resource query required")
    if any(query.get(key) is not False for key in (
            "platform_available_resources_admitted", "complete_g_resource_fit_admitted", "hardware_timing_admitted")):
        raise ValueError("resource query overstates its admission boundary")
    unchanged(query["artifacts"])
    filename = "platform_uram_capacity.csv" if platform else "uram_capacity.csv"
    values = capacity(attempt / filename)
    if values != query["platform_uram_capacity" if platform else "physical_capacity"]:
        raise ValueError("capacity query changed")
    return values


def platform_screen(ledger, physical, platform):
    if any(platform[key] > physical[key] for key in (*SLRS, "device")):
        raise ValueError("platform capacity exceeds the part's physical capacity")
    conflicts = [slr for slr in SLRS if ledger["hls_per_slr"][slr]["URAM"] > platform[slr]]
    return {"platform_uram_capacity": platform, "uram_oversubscribed_slrs": conflicts,
            "total_uram_capacity_exceeded": ledger["hls_totals"]["URAM"] > platform["device"],
            "claim": "hard_pblock_storage_screen_not_shell_free_capacity_or_routing_admission",
            "complete_g_resource_fit_admitted": False, "hardware_timing_admitted": False}


def run(output, config, old_build, search, cache, adapter, capacity_attempt, platform_attempt=None):
    kernels, placements = topology(config.read_text())
    physical = query_capacity(capacity_attempt)
    overrides = {"bin_search": search, "process_cache": cache, "pma_to_regraph_adapter": adapter}
    inputs = {kernel: overrides.get(kernel, old_build / kernel / kernel / kernel / kernel /
                                   "solution/syn/report" / (kernel + "_csynth.xml")) for kernel in kernels}
    estimates = {kernel: resources(path, kernel) for kernel, path in inputs.items()}
    result = account(kernels, placements, estimates, physical)
    balanced = dict(placements)
    # Relocate one existing Little CU; do not remove a cache or shrink capacity.
    if balanced.get("lksg_stream_4") == "SLR0":
        balanced["lksg_stream_4"] = "SLR1"
    result["single_cu_relocation_screen"] = account(kernels, balanced, estimates, physical)
    result["status"] = ("URAM_PLACEMENT_CONFLICT_REQUIRES_NEW_CONFIG" if
                        result["uram_oversubscribed_slrs"] or result["total_uram_capacity_exceeded"] else
                        "PHYSICAL_URAM_SCREEN_PASS_PLATFORM_AND_ROUTING_UNPROVEN")
    if platform_attempt is not None:
        platform = query_capacity(platform_attempt, platform=True)
        for ledger in (result, result["single_cu_relocation_screen"]):
            ledger["platform_storage_screen"] = platform_screen(ledger, physical, platform)
        if result["platform_storage_screen"]["uram_oversubscribed_slrs"] or \
                result["platform_storage_screen"]["total_uram_capacity_exceeded"]:
            result["status"] = "PLATFORM_URAM_PLACEMENT_CONFLICT_REQUIRES_NEW_CONFIG"
    output.mkdir(parents=True, exist_ok=False)
    sources = {"link.cfg": config, "capacity.json": capacity_attempt / "results.json",
               "uram_capacity.csv": capacity_attempt / "uram_capacity.csv", **{
                   "hls/" + name + ".xml": path for name, path in inputs.items()}}
    sources.update({"runner/" + name: Path(__file__).parent / name for name in
                    ("resource_fit.py", "resource_probe.py")})
    if platform_attempt is not None:
        sources.update({"platform/" + name: platform_attempt / name for name in
                        ("results.json", "platform_uram_capacity.csv")})
    pins = []
    for name, path in sources.items():
        target = output / "source" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        digest = sha256_file(path)
        if sha256_file(target) != digest:
            raise ValueError("resource fit input changed while freezing")
        pins.append({"original_path": str(path), "path": str(target), "sha256": digest})
    result["source"] = pins
    unchanged(pins)
    atomic_write_json(output / "results.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("output", "config", "old-build", "search", "cache", "adapter", "capacity-attempt"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--platform-attempt", type=Path)
    args = parser.parse_args()
    run(*(getattr(args, name).resolve() for name in
          ("output", "config", "old_build", "search", "cache", "adapter", "capacity_attempt")),
        platform_attempt=args.platform_attempt.resolve() if args.platform_attempt else None)
