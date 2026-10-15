"""Query physical or platform-pblock URAM capacity without admitting route fit."""

import argparse
import csv
import json
import os
from pathlib import Path
import shutil
from zipfile import ZipFile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.upstream_controls.execution import run_bounded
from ..search_pipeline.admission import wait
from ..search_pipeline.synthesis import unchanged
from ..study import ROOT

VIVADO = Path("/data/yxx/tools/xilinx/Vivado/2024.1/bin/vivado")


def capacity(path):
    with path.open(newline="", encoding="ascii") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != ["region", "uram_sites"]:
            raise ValueError("unexpected physical resource query columns")
        rows = list(reader)
    values = {row["region"]: int(row["uram_sites"]) for row in rows}
    if len(values) != len(rows) or set(values) != {"SLR0", "SLR1", "SLR2", "device"}:
        raise ValueError("missing or duplicate U55C regions")
    if any(value <= 0 for value in values.values()) or \
            values["device"] != sum(values[slr] for slr in ("SLR0", "SLR1", "SLR2")):
        raise ValueError("inconsistent physical site count")
    return values


def run(output, environment, previous_unit, route_unit, platform=None, timeout_seconds=300):
    if type(timeout_seconds) is not int or not 300 <= timeout_seconds <= 900:
        raise ValueError("resource query timeout must be between 300 and 900 seconds")
    output.mkdir(parents=True, exist_ok=False)
    sources = [Path(__file__), Path(__file__).with_suffix(".tcl"),
               Path(__file__).with_suffix(".v"),
               ROOT / "spine_cycle_sim/experiments/campaign_runtime.py",
               ROOT / "spine_cycle_sim/experiments/upstream_controls/execution.py",
               Path(__file__).parent.parent / "search_pipeline/admission.py",
               Path(__file__).parent.parent / "search_pipeline/synthesis.py", environment]
    pins = []
    for source in sources:
        target = output / "source" / (source.relative_to(ROOT) if source.is_relative_to(ROOT) else Path("environment.json"))
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        digest = sha256_file(source)
        if sha256_file(target) != digest:
            raise ValueError("resource probe input changed while freezing")
        pins.append({"original_path": str(source), "path": str(target), "sha256": digest})
    pins.append({"path": str(VIVADO), "sha256": sha256_file(VIVADO)})
    base = output / "source" / Path(__file__).parent.relative_to(ROOT)
    script, arguments = base / "resource_probe.tcl", [str(base / "resource_probe.v")]
    if platform is not None:
        digest = sha256_file(platform)
        pins.append({"path": str(platform), "sha256": digest})
        with ZipFile(platform) as archive:
            for member in ("hw_bb_locked.dcp", "tcl_hooks/impl.xdc"):
                target = output / "platform" / Path(member).name
                target.parent.mkdir(exist_ok=True)
                with archive.open(member) as source, target.open("wb") as destination:
                    shutil.copyfileobj(source, destination)
                pins.append({"path": str(target), "sha256": sha256_file(target)})
        source = Path(__file__).parent / "platform_resource_probe.tcl"
        script = base / source.name
        shutil.copy2(source, script)
        pins.append({"original_path": str(source), "path": str(script), "sha256": sha256_file(source)})
        arguments = [str(output / "platform/hw_bb_locked.dcp"), str(output / "platform/impl.xdc")]
    command = ["systemd-run", "--user", "--scope", "--quiet", "--property=MemoryHigh=7G",
        "--property=MemoryMax=8G", "--property=MemorySwapMax=0", "env", "MALLOC_ARENA_MAX=2",
        "taskset", "-c", "124", str(VIVADO), "-mode", "batch", "-source",
        str(script), "-tclargs", *arguments]
    report = {"status": "PREPARED", "errors": [], "source": pins, "command": command,
        "part": "xcu55c-fsvh2892-2L-e", "platform_available_resources_admitted": False,
        "complete_g_resource_fit_admitted": False, "hardware_timing_admitted": False,
        "resources": {"memory_max_gib": 8, "memory_high_gib": 7, "reserve_gib": 24,
                      "cpu_affinity": [124], "swap_max_bytes": 0, "timeout_seconds": timeout_seconds}}
    save = lambda: atomic_write_json(output / "results.json", report)
    save()
    try:
        reserve = wait(report, save, previous_unit, route_unit, maximum_wait=0)
        unchanged(pins)
        os.environ.update(json.loads(environment.read_text())["effective"]["values"])
        report["status"] = "RUNNING_PLATFORM_PBLOCK_QUERY" if platform else "RUNNING_PHYSICAL_RESOURCE_QUERY"
        save()
        report["execution"] = run_bounded(command, output, output / "execution", timeout=timeout_seconds,
                                          memory_gib=8, reserve_gib=reserve)
        unchanged(pins)
        if report["execution"]["exit_code"] or report["execution"]["timed_out"]:
            raise ValueError("resource query failed; raw attempt retained")
        table = output / ("platform_uram_capacity.csv" if platform else "uram_capacity.csv")
        report["platform_uram_capacity" if platform else "physical_capacity"] = capacity(table)
        report["artifacts"] = [{"path": str(path), "sha256": sha256_file(path)} for path in
                               (table, output / ("platform_utilization.rpt" if platform else "device_utilization.rpt"))]
        report["status"] = ("PLATFORM_PBLOCK_CAPACITY_QUERIED_NOT_ROUTE_ADMISSION" if platform else
                            "PHYSICAL_SITE_CAPACITY_QUERIED_NOT_ROUTE_ADMISSION")
    except Exception as error:
        report.update(status="FAILED_RETAINED", errors=[repr(error)])
        save()
        raise
    save()
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--environment", type=Path, required=True)
    parser.add_argument("--previous-unit", required=True)
    parser.add_argument("--route-unit", required=True)
    parser.add_argument("--platform", type=Path)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    args = parser.parse_args()
    run(args.output.resolve(), args.environment.resolve(), args.previous_unit, args.route_unit,
        args.platform.resolve() if args.platform else None, args.timeout_seconds)
